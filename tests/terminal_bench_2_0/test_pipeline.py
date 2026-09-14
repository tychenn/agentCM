import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from trajectory_graph.cli import parser, run
from trajectory_graph.deepseek_client import CapacityError, Client, InvalidResponse, prompt
from trajectory_graph.adapters.terminal_bench_2_0.normalize import (
    OBSERVATION_WARNING_PREFIX, align_observations_by_source_call_id,
    clean_observation_content, load, materialize_alignment, prepare)
from trajectory_graph.validate import (Invalid, agent_turns, alignment_assignments,
                                         dependency_choice, dependency_evidence,
                                         local_graphs, root_query, strict_json, tree)


def ref(eid, text, cid=None, field='thought'):
    return {'event_id': eid, 'tool_call_id': cid, 'field': field, 'quote': text}


def summary(goal, event_ids, result=None, reason='这些连续节点共同完成该局部目标'):
    return {
        'goal': goal,
        'completion_condition': goal + '已完成',
        'status': 'completed',
        'reason': reason,
        'result': result,
        'source_event_ids': event_ids,
    }


def fixture():
    steps = [{'step_id': 1, 'source': 'user', 'message': '读取数据，汇总并绘图'}]
    messages = ['读取数据', '安装缺少的依赖', '恢复读取数据', '按月汇总', '生成图表']
    outputs = ['ModuleNotFoundError\n', 'Installed\n', 'Loaded\n', 'Aggregated\n', 'Saved\n']
    for i, (message, output) in enumerate(zip(messages, outputs), 2):
        steps.append({'step_id': i, 'source': 'agent', 'message': message, 'tool_calls': [
            {'tool_call_id': f'c{i}', 'function_name': 'bash_command',
             'arguments': {'keystrokes': f'command-{i}\n', 'duration': 1}}],
            'observation': {'results': [{'content': output}]}})
    steps.append({'step_id': 7, 'source': 'agent', 'message': '任务完成'})
    return {
        'schema_version': 'ATIF-v1.7',
        'agent': {'name': 'terminus-2', 'version': '2.0.0'},
        'steps': steps,
    }


class Model:
    def __init__(self, invalid_first=False, bad_split=False):
        self.requests = []
        self.invalid_first = invalid_first
        self.bad_split = bad_split

    def __call__(self, payload):
        self.requests.append(payload)
        system, user = [m['content'] for m in payload['messages']]
        if 'You extract' in system:
            value = {'title': '销售分析', 'query': '读取数据，汇总并绘图', 'review_flags': []}
        elif "Locate the start of each supplied ordered tool call's text" in system:
            step, _ = json.JSONDecoder().raw_decode(user.split('INPUT\n', 1)[1])
            chunks = step['combined_observation'].splitlines(keepends=True)
            assignments = [
                {'tool_call_id': call['tool_call_id'],
                 'start_anchor': ('invented' if self.bad_split and i == 0 else
                                  chunks[i] if i < len(chunks) else None)}
                for i, call in enumerate(step['tool_calls'])
            ]
            value = {'assignments': assignments}
        elif 'Create one atomic execution-turn annotation' in system:
            event = json.loads(user.split('AGENT EVENT\n')[1])
            quote = event['thought']
            observed = '\n'.join(c['observation']['raw'] for c in event['tool_calls']
                                 if c['observation']['raw'])
            turn = {'event_id': event['event_id'], 'goal': quote,
                    'status': 'completed', 'result': observed or quote,
                    'tool_call_results': [
                        {'tool_call_id': call['tool_call_id'],
                         'result': call['observation']['raw'].strip() or None}
                        for call in event['tool_calls']],
                    'source_refs': [ref(event['event_id'], quote)]}
            value = {'turn': turn, 'review_flags': []}
        elif 'Identify which earlier tool-call results directly informed' in system:
            current, _ = json.JSONDecoder().raw_decode(user.split('TARGET AGENT TURN\n')[1])
            choices = {
                'event-0002': ['c2'],
                'event-0003': ['c2', 'c3'],
                'event-0004': ['c4'],
                'event-0005': ['c5'],
                'event-0006': ['c6'],
            }
            value = {'target_event_id': current['event_id'],
                     'trigger_tool_call_ids': choices[current['event_id']]}
        elif 'Write one concise review label for every supplied task' in system:
            supplied = json.loads(user.split('DEPENDENCY EDGES WITH EVIDENCE\n')[1])
            value = {'edges': [
                {
                    'source_task_id': edge['source_task']['task_id'],
                    'target_task_id': edge['target_task']['task_id'],
                    'reason': 'Source tool results determine the target task actions.',
                }
                for edge in supplied
            ]}
        elif 'Decide the first leaf-task boundary' in system:
            data = json.loads(user.split('LOCAL GROUPING INPUT\n')[1])
            cards = data['candidates']
            if cards[0]['node_id'] == 'event-0005' and len(cards) >= 2:
                chosen = cards[:2]
                value = {
                    'action': 'merge',
                    'member_ids': [card['node_id'] for card in chosen],
                    'task': summary('生成图表并完成任务',
                                    [card['node_id'] for card in chosen], '图表已保存'),
                    'review_flags': [],
                }
            else:
                card = cards[0]
                value = {
                    'action': 'keep', 'member_ids': [card['node_id']],
                    'task': summary(card['goal'], card['evidence_event_ids'], card['result']),
                    'review_flags': [],
                }
        elif 'Decide whether the anchor and following task nodes form one meaningful' in system:
            data = json.loads(user.split('LOCAL GROUPING INPUT\n')[1])
            cards = data['candidates']
            goals = [card['goal'] for card in cards]
            if goals[:3] == ['读取数据', '安装缺少的依赖', '恢复读取数据']:
                chosen = cards[:3]
                evidence = [event_id for card in chosen
                            for event_id in card['evidence_event_ids']]
                value = {
                    'action': 'merge',
                    'member_ids': [card['node_id'] for card in chosen],
                    'task': summary('准备并读取数据', evidence, '数据读取已恢复'),
                    'review_flags': [],
                }
            else:
                value = {'action': 'keep', 'member_ids': [cards[0]['node_id']],
                         'task': None, 'review_flags': []}
        elif 'Review only the most recently formed boundary' in system:
            value = {
                'action': 'keep_boundary', 'move_count': 0,
                'left_task': None, 'right_task': None, 'merged_task': None,
                'review_flags': [],
            }
        elif 'Summarize the supplied completed task-tree frontier' in system:
            value = {'status': 'completed', 'result': '读取、汇总和绘图均已完成',
                     'review_flags': []}
        else:
            raise AssertionError('Unexpected model request:\n' + system)
        content = json.dumps(value, ensure_ascii=False)
        if self.invalid_first and len(self.requests) == 1:
            content = '```json\n' + content + '\n```'
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}


class ExpandingModel(Model):
    def __init__(self):
        super().__init__()
        self.expanded = False

    def __call__(self, payload):
        system, user = [message['content'] for message in payload['messages']]
        if 'Decide the first leaf-task boundary' in system:
            data = json.loads(user.split('LOCAL GROUPING INPUT\n')[1])
            if (not self.expanded and data['candidates'][0]['node_id'] == 'event-0001'
                    and data['can_extend']):
                self.expanded = True
                self.requests.append(payload)
                value = {'action': 'need_more_context', 'member_ids': [],
                         'task': None, 'review_flags': ['anchor boundary is outside this window']}
                return {'choices': [{'finish_reason': 'stop', 'message': {
                    'content': json.dumps(value)}}]}
        return super().__call__(payload)


class BoundaryShiftModel(Model):
    def __init__(self):
        super().__init__()
        self.initial_merge = False
        self.shifted = False

    def __call__(self, payload):
        system, user = [message['content'] for message in payload['messages']]
        if 'Decide the first leaf-task boundary' in system:
            data = json.loads(user.split('LOCAL GROUPING INPUT\n')[1])
            cards = data['candidates']
            if (not self.initial_merge and cards[0]['node_id'] == 'event-0001'
                    and len(cards) >= 2):
                self.initial_merge = True
                self.requests.append(payload)
                chosen = cards[:2]
                value = {
                    'action': 'merge',
                    'member_ids': [card['node_id'] for card in chosen],
                    'task': summary('初步读取和修复',
                                    [card['node_id'] for card in chosen]),
                    'review_flags': [],
                }
                return {'choices': [{'finish_reason': 'stop', 'message': {
                    'content': json.dumps(value, ensure_ascii=False)}}]}
        if 'Review only the most recently formed boundary' in system and not self.shifted:
            self.shifted = True
            self.requests.append(payload)
            value = {
                'action': 'shift_right', 'move_count': 1,
                'left_task': summary('读取数据', ['event-0001']),
                'right_task': summary('安装依赖并恢复读取',
                                      ['event-0002', 'event-0003']),
                'merged_task': None, 'review_flags': [],
            }
            return {'choices': [{'finish_reason': 'stop', 'message': {
                'content': json.dumps(value, ensure_ascii=False)}}]}
        return super().__call__(payload)


class NonPrefixModel(Model):
    def __call__(self, payload):
        system, user = [message['content'] for message in payload['messages']]
        if 'Decide the first leaf-task boundary' in system:
            data = json.loads(user.split('LOCAL GROUPING INPUT\n')[1])
            cards = data['candidates']
            if len(cards) >= 3:
                self.requests.append(payload)
                chosen = [cards[0], cards[2]]
                value = {
                    'action': 'merge',
                    'member_ids': [card['node_id'] for card in chosen],
                    'task': summary('非法跳跃归并',
                                    [card['node_id'] for card in chosen]),
                    'review_flags': [],
                }
                return {'choices': [{'finish_reason': 'stop', 'message': {
                    'content': json.dumps(value, ensure_ascii=False)}}]}
        return super().__call__(payload)


class StageOneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.input = self.base / 'input.json'
        self.input.write_text(json.dumps(fixture(), ensure_ascii=False))
        self.out = self.base / 'run'

    def args(self, *extra):
        return parser().parse_args(['build', '--input', str(self.input), '--output', str(self.out), *extra])

    def build(self, model=None, *extra):
        model = model or Model()
        run(self.args(*extra), transport=model)
        return (strict_json((self.out / 'execution_tree.json').read_text()),
                strict_json((self.out / 'normalized_trace.json').read_text()), model)

    def test_pipeline_bottom_up_tasks_dependencies_resume_and_source_hash(self):
        before = hashlib.sha256(self.input.read_bytes()).hexdigest()
        value, trace, model = self.build(Model(invalid_first=True))
        tree(value, trace)
        self.assertEqual(trace['source']['adapter'], 'terminal-bench-2.0')
        self.assertEqual(value['root']['subtasks'][0]['subtasks'][1]['goal'], '安装缺少的依赖')
        self.assertEqual(value['root']['source_refs'], [{
            'event_id': 'query', 'tool_call_id': None, 'field': 'source_raw',
            'quote': trace['query']['source_raw'],
        }])
        self.assertEqual(value['root']['subtasks'][0]['subtasks'][0]['source_refs'],
                         value['root']['subtasks'][0]['subtasks'][0]['turns'][0]['source_refs'])
        self.assertEqual(len(value['root']['subtasks']), 3)
        self.assertEqual([c['tool_call_id'] for c in
                          value['root']['subtasks'][0]['subtasks'][0]['turns'][0]['tool_calls']], ['c2'])
        self.assertEqual(before, hashlib.sha256(self.input.read_bytes()).hexdigest())
        self.assertNotIn('duration', trace['events'][0]['tool_calls'][0]['arguments'])
        self.assertIn('VALIDATION ERRORS', model.requests[1]['messages'][1]['content'])
        split_user = model.requests[2]['messages'][1]['content']
        self.assertNotIn('按月汇总', split_user)
        annotate_requests = [request for request in model.requests
            if 'Create one atomic execution-turn annotation' in request['messages'][0]['content']]
        self.assertEqual(len(annotate_requests), 6)
        self.assertNotIn('按月汇总', annotate_requests[0]['messages'][1]['content'])
        self.assertTrue(all(request['thinking'] == {'type': 'enabled'}
                            and request['reasoning_effort'] == 'high'
                            and request['max_tokens'] == 32768
                            for request in annotate_requests))
        dependency_requests = [request for request in model.requests
            if 'Identify which earlier tool-call results directly informed' in
               request['messages'][0]['content']]
        self.assertEqual(len(dependency_requests), 5)
        first_dependency = dependency_requests[0]['messages'][1]['content']
        self.assertIn('event-0001', first_dependency)
        self.assertNotIn('按月汇总', first_dependency)
        later_dependency = dependency_requests[2]['messages'][1]['content']
        prior_turns, _ = json.JSONDecoder().raw_decode(
            later_dependency.split('PRIOR AGENT TURNS IN TRAJECTORY ORDER\n')[1])
        self.assertEqual([turn['event_id'] for turn in prior_turns],
                         ['event-0001', 'event-0002', 'event-0003'])
        self.assertTrue(all('thought' in turn for turn in prior_turns))
        self.assertEqual(prior_turns[-1]['tool_calls'][0]['input'], 'command-4\n')
        self.assertEqual(prior_turns[-1]['tool_calls'][0]['observation'], 'Loaded\n')
        dependencies = strict_json((self.out / 'dependency_evidence.json').read_text())
        dependency_evidence(dependencies, trace, list(agent_turns(value['root'])))
        self.assertEqual(dependencies['dependencies'][1], {
            'target_event_id': 'event-0002', 'trigger_tool_call_ids': ['c2']})
        self.assertEqual(dependencies['dependencies'][2], {
            'target_event_id': 'event-0003', 'trigger_tool_call_ids': ['c2', 'c3']})
        self.assertEqual(dependencies['dependencies'][0]['trigger_tool_call_ids'], [])
        reason_requests = [request for request in model.requests
            if 'Write one concise review label for every supplied task' in
               request['messages'][0]['content']]
        self.assertEqual(len(reason_requests), 1)
        self.assertIn('ModuleNotFoundError', reason_requests[0]['messages'][1]['content'])
        bad_graph = copy.deepcopy(dependencies)
        bad_graph['dependencies'][1]['trigger_tool_call_ids'] = ['c6']
        with self.assertRaises(Invalid):
            dependency_evidence(bad_graph, trace, list(agent_turns(value['root'])))
        graphs = strict_json((self.out / 'local_graphs.json').read_text())
        local_graphs(graphs, value, trace, dependencies)
        read_task = value['root']['subtasks'][0]
        read_graph = next(item for item in graphs['local_graphs']
                          if item['task_id'] == read_task['id'])
        reason = 'Source tool results determine the target task actions.'
        self.assertEqual(read_graph['edges'], [
            {'source_task_id': read_task['subtasks'][0]['id'],
             'target_task_id': read_task['subtasks'][1]['id'],
             'reason': reason,
             'evidence': [{'tool_call_id': 'c2', 'target_event_id': 'event-0002'}]},
            {'source_task_id': read_task['subtasks'][0]['id'],
             'target_task_id': read_task['subtasks'][2]['id'],
             'reason': reason,
             'evidence': [{'tool_call_id': 'c2', 'target_event_id': 'event-0003'}]},
            {'source_task_id': read_task['subtasks'][1]['id'],
             'target_task_id': read_task['subtasks'][2]['id'],
             'reason': reason,
             'evidence': [{'tool_call_id': 'c3', 'target_event_id': 'event-0003'}]},
        ])
        bad_local = copy.deepcopy(graphs)
        next(item for item in bad_local['local_graphs']
             if item['task_id'] == read_task['id'])['edges'].pop()
        with self.assertRaisesRegex(Invalid, 'preserve every cross-task dependency'):
            local_graphs(bad_local, value, trace, dependencies)
        bad_local = copy.deepcopy(graphs)
        bad_edge = next(item for item in bad_local['local_graphs']
                        if item['task_id'] == read_task['id'])['edges'][0]
        bad_edge['source_task_id'], bad_edge['target_task_id'] = (
            bad_edge['target_task_id'], bad_edge['source_task_id'])
        with self.assertRaisesRegex(Invalid, 'follow task execution order'):
            local_graphs(bad_local, value, trace, dependencies)
        bad_local = copy.deepcopy(graphs)
        del next(item for item in bad_local['local_graphs']
                 if item['task_id'] == read_task['id'])['edges'][0]['reason']
        with self.assertRaisesRegex(Invalid, 'Expected exactly fields'):
            local_graphs(bad_local, value, trace, dependencies)
        group_requests = [request for request in model.requests
            if 'LOCAL GROUPING INPUT' in request['messages'][1]['content']]
        self.assertGreater(len(group_requests), 1)
        self.assertTrue(all('COMPLETE NORMALIZED TRAJECTORY' not in
                            request['messages'][1]['content']
                            for request in group_requests))
        grouping_steps = [json.loads(line) for line in
                          (self.out / 'grouping_steps.jsonl').read_text().splitlines()]
        self.assertTrue(any(step['type'] == 'local_decision' for step in grouping_steps))
        self.assertTrue(any(step['type'] == 'boundary_review' for step in grouping_steps))
        self.assertTrue(any(step['type'] == 'round_end' and
                            step['phase'] == 'merge-tasks' and step['reduction'] == 0
                            for step in grouping_steps))
        calls = len(model.requests)
        run(self.args(), transport=model)
        self.assertEqual(len(model.requests), calls)
        data = fixture()
        data['steps'][0]['message'] += 'changed'
        self.input.write_text(json.dumps(data))
        with self.assertRaises(Invalid):
            run(self.args('--resume'), transport=model)

    def test_grouping_expands_a_local_window_without_sending_the_full_trace(self):
        model = ExpandingModel()
        value, trace, _ = self.build(
            model, '--merge-window', '2', '--merge-window-max', '4',
            '--merge-lookback', '0')
        tree(value, trace)
        leaf_requests = [request for request in model.requests
            if 'Decide the first leaf-task boundary' in request['messages'][0]['content']]
        first_two = [json.loads(request['messages'][1]['content'].split(
            'LOCAL GROUPING INPUT\n')[1]) for request in leaf_requests[:2]]
        self.assertEqual([len(item['candidates']) for item in first_two], [2, 4])
        self.assertEqual(first_two[0]['candidates'][0]['node_id'], 'event-0001')
        self.assertTrue(first_two[0]['can_extend'])
        self.assertFalse(any('thought' in card or 'source_refs' in card
                             for item in first_two for card in item['candidates']))
        steps = [json.loads(line) for line in
                 (self.out / 'grouping_steps.jsonl').read_text().splitlines()]
        decisions = [step for step in steps if step['type'] == 'local_decision'
                     and step['anchor_id'] == 'event-0001']
        self.assertEqual([step['response']['action'] for step in decisions[:2]],
                         ['need_more_context', 'keep'])

    def test_finite_lookback_shifts_only_the_latest_leaf_boundary(self):
        model = BoundaryShiftModel()
        value, trace, _ = self.build(model, '--merge-window', '4',
                                     '--merge-window-max', '8',
                                     '--merge-lookback', '1')
        tree(value, trace)
        first, second = value['root']['subtasks'][:2]
        self.assertEqual([turn['event_id'] for turn in first['turns']], ['event-0001'])
        self.assertEqual([turn['event_id'] for turn in second['turns']],
                         ['event-0002', 'event-0003'])
        reviews = [json.loads(line) for line in
                   (self.out / 'grouping_steps.jsonl').read_text().splitlines()
                   if json.loads(line)['type'] == 'boundary_review']
        shifted = next(review for review in reviews
                       if review['response']['action'] == 'shift_right')
        self.assertEqual(shifted['before'],
                         [['event-0001', 'event-0002'], ['event-0003']])
        self.assertEqual(shifted['after'],
                         [['event-0001'], ['event-0002', 'event-0003']])

    def test_grouping_rejects_a_non_prefix_merge(self):
        model = NonPrefixModel()
        with self.assertRaisesRegex(InvalidResponse, 'continuous prefix'):
            self.build(model, '--retries', '0')
        self.assertFalse((self.out / 'execution_tree.json').exists())

    def test_single_turn_is_promoted_into_the_root_without_a_unary_task(self):
        data = fixture()
        data['steps'] = data['steps'][:2]
        self.input.write_text(json.dumps(data, ensure_ascii=False))
        value, trace, _ = self.build(Model())
        tree(value, trace)
        self.assertEqual(value['root']['subtasks'], [])
        self.assertEqual([turn['event_id'] for turn in value['root']['turns']],
                         ['event-0001'])

    def test_invalid_split_stops_after_three_requests(self):
        data = fixture()
        data['steps'][1]['tool_calls'].append({
            'tool_call_id': 'c2-extra', 'function_name': 'bash_command',
            'arguments': {'keystrokes': 'second-command\n', 'duration': 1}})
        self.input.write_text(json.dumps(data, ensure_ascii=False))
        model = Model(bad_split=True)
        with self.assertRaises(InvalidResponse):
            self.build(model, '--retries', '10')
        split_requests = [request for request in model.requests
            if "Locate the start of each supplied ordered tool call's text" in
               request['messages'][0]['content']]
        self.assertEqual(len(split_requests), 3)
        self.assertFalse((self.out / 'normalized_trace.json').exists())

    def test_split_fast_path_and_model_split_terminal_summary(self):
        data = fixture()
        data['steps'][2]['tool_calls'].append({
            'tool_call_id': 'c3-extra', 'function_name': 'bash_command',
            'arguments': {'keystrokes': 'second-command\n', 'duration': 1}})
        data['steps'][2]['observation']['results'].append({'content': 'Second output\n'})
        self.input.write_text(json.dumps(data, ensure_ascii=False))
        model = Model()
        stream = StringIO()
        with redirect_stdout(stream):
            _, trace, model = self.build(model)
        split_requests = [request for request in model.requests
            if "Locate the start of each supplied ordered tool call's text" in
               request['messages'][0]['content']]
        self.assertEqual(len(split_requests), 1)
        self.assertEqual(split_requests[0]['thinking'], {'type': 'disabled'})
        self.assertEqual(split_requests[0]['temperature'], 0)
        self.assertNotIn('reasoning_effort', split_requests[0])
        split_user = split_requests[0]['messages'][1]['content']
        self.assertIn('"combined_observation"', split_user)
        self.assertIn('"input": "command-3\\n"', split_user)
        self.assertNotIn('"observation_contents"', split_user)
        self.assertNotIn('"arguments"', split_user)
        self.assertNotIn('"duration"', split_user)
        output = stream.getvalue()
        self.assertIn('[split-2] 结果（本地直接对齐，未调用模型）', output)
        self.assertIn('分配：c2=20字符', output)
        self.assertNotIn('arguments   =', output)
        self.assertNotIn('observation <-', output)
        self.assertNotIn('ModuleNotFoundError', output)
        self.assertIn('[split-3] 需要模型判断：2 个 tool call，2 段 observation', output)
        self.assertIn('分配：c3=10字符, c3-extra=14字符', output)
        self.assertNotIn('Second output', output)
        self.assertEqual(trace['events'][1]['tool_calls'][1]['observation']['raw'], 'Second output\n')

    def test_source_call_ids_use_local_alignment_in_tool_call_order(self):
        data = fixture()
        data['steps'][2]['tool_calls'].append({
            'tool_call_id': 'c3-extra', 'function_name': 'bash_command',
            'arguments': {'keystrokes': 'second-command\n', 'duration': 1}})
        data['steps'][2]['observation']['results'] = [
            {'source_call_id': 'c3-extra', 'content': 'Second output\n'},
            {'source_call_id': 'c3', 'content': 'Installed\n'},
        ]
        self.input.write_text(json.dumps(data, ensure_ascii=False))
        model = Model()
        stream = StringIO()
        with redirect_stdout(stream):
            _, trace, model = self.build(model)
        split_requests = [request for request in model.requests
            if "Locate the start of each supplied ordered tool call's text" in
               request['messages'][0]['content']]
        self.assertEqual(split_requests, [])
        calls = trace['events'][1]['tool_calls']
        self.assertEqual([call['observation']['raw'] for call in calls],
                         ['Installed\n', 'Second output\n'])
        self.assertIn(
            '[split-3] 结果（按 source_call_id 本地直接对齐，未调用模型）',
            stream.getvalue())
        self.assertIn('分配：c3=10字符, c3-extra=14字符', stream.getvalue())
        self.assertNotIn('Second output', stream.getvalue())

    def test_source_call_id_must_match_a_call_in_the_same_step(self):
        calls = [{'tool_call_id': 'a'}, {'tool_call_id': 'b'}]
        observations = [{'source_call_id': 'outside', 'content': 'output\n'}]
        with self.assertRaisesRegex(Invalid, 'does not match a tool call'):
            align_observations_by_source_call_id(calls, observations)

    def test_alignment_uses_anchors_to_slice_exact_source(self):
        calls = [{'tool_call_id': 'a'}, {'tool_call_id': 'b'}]
        contents = ['A1\nB1\n']
        response = {'assignments': [
            {'tool_call_id': 'a', 'start_anchor': 'A1\n'},
            {'tool_call_id': 'b', 'start_anchor': 'B1\n'}]}
        assignments = materialize_alignment(response, calls, contents)
        self.assertEqual([item['observation_raw'] for item in assignments], ['A1\n', 'B1\n'])
        response['assignments'][1]['start_anchor'] = 'missing'
        with self.assertRaises(Invalid):
            materialize_alignment(response, calls, contents)
        response['assignments'][1] = {'tool_call_id': 'b'}
        with self.assertRaises(Invalid):
            alignment_assignments(response, calls)

    def test_alignment_preserves_terminal_wraps_and_final_newline(self):
        calls = [{'tool_call_id': 'a'}, {'tool_call_id': 'b'}, {'tool_call_id': 'c'}]
        contents = [
            'New Terminal Output:\n\nprompt# mv wIQEB5n\nR79b2.pdf\n',
            "prompt# python3 << 'EOF'\ndone\n",
            'prompt# cat summary.csv\ntotal,1.00\n',
        ]
        response = {'assignments': [
            {'tool_call_id': 'a', 'start_anchor': 'New Terminal Output:\n\n'},
            {'tool_call_id': 'b', 'start_anchor': "prompt# python3 << 'EOF'\n"},
            {'tool_call_id': 'c', 'start_anchor': 'prompt# cat summary.csv\n'},
        ]}
        assignments = materialize_alignment(response, calls, contents)
        self.assertEqual([item['observation_raw'] for item in assignments], contents)
        self.assertIn('wIQEB5n\nR79b2.pdf', assignments[0]['observation_raw'])
        self.assertTrue(assignments[-1]['observation_raw'].endswith('\n'))
        response['assignments'][0]['start_anchor'] = (
            'New Terminal Output:\n\nprompt# mv wIQEB5nR79b2.pdf')
        with self.assertRaisesRegex(
                Invalid, "first difference at source character .*expected source '\\\\n'"):
            materialize_alignment(response, calls, contents)

    def test_known_observation_warning_is_removed_before_alignment(self):
        terminal_output = 'New Terminal Output:\n\nModuleNotFoundError\n'
        data = fixture()
        data['steps'][1]['observation']['results'][0]['content'] = (
            OBSERVATION_WARNING_PREFIX + terminal_output)
        prepared, _ = prepare(data)
        self.assertEqual(prepared[0][1], [
            {'source_call_id': None, 'content': terminal_output}])
        self.assertEqual(clean_observation_content(
            OBSERVATION_WARNING_PREFIX.replace('\n', '\r\n') + terminal_output), terminal_output)
        embedded = 'prefix\n' + OBSERVATION_WARNING_PREFIX + terminal_output
        self.assertEqual(clean_observation_content(embedded), embedded)

    def test_tree_rejects_duplicate_future_evidence_and_user_judgment(self):
        value, trace, _ = self.build()
        bad = copy.deepcopy(value)
        bad['root']['subtasks'][1]['turns'].append(copy.deepcopy(next(agent_turns(bad['root']))))
        with self.assertRaises(Invalid): tree(bad, trace)
        bad = copy.deepcopy(value)
        bad['root']['subtasks'][0]['subtasks'][0]['turns'][0]['source_refs'][0]['quote'] = 'invented'
        with self.assertRaises(Invalid): tree(bad, trace)
        bad = copy.deepcopy(value)
        bad['root']['subtasks'][0], bad['root']['subtasks'][1] = (
            bad['root']['subtasks'][1], bad['root']['subtasks'][0])
        with self.assertRaises(Invalid): tree(bad, trace)
        trace['events'][-1]['source'] = 'user'
        with self.assertRaises(Invalid): tree(value, trace)

    def test_tree_rejects_redundant_unary_composite(self):
        value, trace, _ = self.build()
        bad = copy.deepcopy(value)
        bad['root']['subtasks'][0]['subtasks'] = [bad['root']['subtasks'][0]['subtasks'][0]]
        with self.assertRaisesRegex(Invalid, 'at least two direct subtasks'):
            tree(bad, trace)

    def test_fallback_ids_do_not_collide_with_originals(self):
        raw = fixture()
        raw['steps'][1]['tool_calls'][0]['tool_call_id'] = None
        raw['steps'][2]['tool_calls'][0]['tool_call_id'] = '2:tool:1'
        events, flags = prepare(raw)
        ids = [c['tool_call_id'] for e, _ in events for c in e['tool_calls']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('2:tool:1', ids)
        self.assertTrue(flags)

    def test_json_rejects_duplicate_keys_and_nonfinite_values(self):
        for content in ['{"x":1,"x":2}', '{"x":NaN}', '```json\n{}\n```']:
            with self.assertRaises(ValueError): strict_json(content)

    def test_dependency_choice_requires_prior_order_and_allows_empty(self):
        calls = ['c2', 'c3']
        dependency_choice({'target_event_id': 'event-0002',
                           'trigger_tool_call_ids': ['c2', 'c3']},
                          'event-0002', calls)
        dependency_choice({'target_event_id': 'event-0002',
                           'trigger_tool_call_ids': []}, 'event-0002', calls)
        with self.assertRaises(Invalid):
            dependency_choice({'target_event_id': 'event-0099',
                               'trigger_tool_call_ids': ['c2']}, 'event-0002', calls)
        with self.assertRaises(Invalid):
            dependency_choice({'target_event_id': 'event-0002',
                               'trigger_tool_call_ids': ['c9']}, 'event-0002', calls)
        with self.assertRaises(Invalid):
            dependency_choice({'target_event_id': 'event-0002'}, 'event-0002', calls)
        with self.assertRaises(Invalid):
            dependency_choice({'target_event_id': 'event-0002',
                               'trigger_tool_call_ids': ['c2', 'c2']}, 'event-0002', calls)
        with self.assertRaises(Invalid):
            dependency_choice({'target_event_id': 'event-0002',
                               'trigger_tool_call_ids': ['c3', 'c2']}, 'event-0002', calls)

    def test_capacity_stops_before_transport(self):
        model = Model()
        client = Client(self.out, transport=model, context_tokens=10)
        with self.assertRaises(CapacityError):
            client.ask('root', ['extract_root_v1'], 'extract_root_user',
                       {'first_user_message_json': 'task'}, root_query)
        self.assertFalse(model.requests)

    def test_truncated_output_is_retried_not_accepted(self):
        model = Model()
        def truncated(payload):
            value = model(payload)
            if len(model.requests) == 1:
                value['choices'][0]['finish_reason'] = 'length'
            return value
        client = Client(self.out, transport=truncated, max_tokens=512)
        client.ask('root', ['extract_root_v1'], 'extract_root_user',
                   {'first_user_message_json': 'task'}, root_query, output_tokens=128)
        self.assertEqual(len(model.requests), 2)
        self.assertEqual([request['max_tokens'] for request in model.requests], [128, 256])
        self.assertIn('Response incomplete', model.requests[1]['messages'][1]['content'])

    def test_normalize_only_preserves_later_user_message(self):
        data = fixture()
        data['steps'].append({'step_id': 8, 'source': 'user', 'message': '再保留一份原始数据'})
        self.input.write_text(json.dumps(data))
        args = parser().parse_args(['normalize', '--input', str(self.input), '--output', str(self.out / 'trace.json')])
        run(args, transport=Model())
        trace = json.loads((self.out / 'trace.json').read_text())
        self.assertEqual(trace['events'][-1]['source'], 'user')
        self.assertEqual(trace['events'][-1]['thought'], '再保留一份原始数据')
        self.assertFalse((self.out / 'execution_tree.json').exists())

    def test_redaction_request_logs_cache_and_evidence_restoration(self):
        secret = 'sk-' + 'z' * 32
        client = Client(self.out, transport=lambda p: {'choices': [{'finish_reason': 'stop', 'message':
            {'content': json.dumps({'title': 'task', 'query': json.loads(p['messages'][1]['content'].split(
                'FIRST USER MESSAGE\n')[1]), 'review_flags': []})}}]})
        result = client.ask('root', ['extract_root_v1'], 'extract_root_user',
                            {'first_user_message_json': secret}, root_query)
        self.assertEqual(result['query'], secret)
        for path in self.out.rglob('*'):
            if path.is_file(): self.assertNotIn(secret, path.read_text())

    def test_http_transport_payload_and_authorization(self):
        model = Model()
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path, self.headers.get('Authorization')))
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                response = json.dumps(model(payload)).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            def log_message(self, *args): pass
        try:
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        except PermissionError:
            self.skipTest('current sandbox does not allow binding a local test port')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-key', 'no_proxy': '127.0.0.1', 'NO_PROXY': '127.0.0.1'}):
                run(self.args('--base-url', f'http://127.0.0.1:{server.server_port}'))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertTrue(all(p == '/chat/completions' and key == 'Bearer test-key' for p, key in received))
        self.assertEqual(model.requests[0]['response_format'], {'type': 'json_object'})
        annotation = next(request for request in model.requests
            if 'Create one atomic execution-turn annotation' in request['messages'][0]['content'])
        dependency = next(request for request in model.requests
            if 'Identify which earlier tool-call results directly informed' in
               request['messages'][0]['content'])
        grouping = next(request for request in model.requests
            if 'Decide the first leaf-task boundary' in
               request['messages'][0]['content'])
        boundary = next(request for request in model.requests
            if 'Review only the most recently formed boundary' in
               request['messages'][0]['content'])
        explanation = next(request for request in model.requests
            if 'Write one concise review label for every supplied task' in
               request['messages'][0]['content'])
        self.assertEqual(annotation['max_tokens'], 32768)
        self.assertEqual(annotation['thinking'], {'type': 'enabled'})
        self.assertNotIn('temperature', annotation)
        self.assertEqual(dependency['max_tokens'], 32768)
        self.assertEqual(dependency['thinking'], {'type': 'enabled'})
        self.assertEqual(dependency['reasoning_effort'], 'high')
        self.assertNotIn('temperature', dependency)
        for request in (grouping, boundary):
            self.assertEqual(request['max_tokens'], 32768)
            self.assertEqual(request['thinking'], {'type': 'enabled'})
            self.assertEqual(request['reasoning_effort'], 'high')
            self.assertNotIn('temperature', request)
        self.assertEqual(explanation['max_tokens'], 32768)
        self.assertEqual(explanation['thinking'], {'type': 'enabled'})
        self.assertEqual(explanation['reasoning_effort'], 'high')

    def test_prompt_files_are_linked_in_readme(self):
        root = Path(__file__).parents[2]
        readme = (root / 'README.md').read_text()
        for path in (root / 'src/trajectory_graph').rglob('prompts/*.md'):
            relative = path.relative_to(root).as_posix()
            self.assertIn(f']({relative})', readme, path.name)

    def test_leaf_prompt_preserves_causal_phase_boundaries(self):
        root = Path(__file__).parents[2]
        leaf_prompt = (root / 'src/trajectory_graph/prompts/group_leaf_v1.md').read_text()
        self.assertIn('smallest closed operational unit', leaf_prompt)
        self.assertRegex(
            leaf_prompt,
            r'Agent turns are already the\s+atomic execution nodes')
        self.assertRegex(
            leaf_prompt,
            r'one primary output, and one completion condition')
        self.assertIn('does not by itself require a split', leaf_prompt)
        self.assertRegex(
            leaf_prompt,
            r'partial batch, or isolated fact is not sufficient')
        self.assertIn('earliest supported boundary', leaf_prompt)
        self.assertRegex(
            leaf_prompt,
            r'discovery or diagnosis to remediation or\s+installation')
        self.assertIn('same completion condition', leaf_prompt)

    def test_default_output_flash_and_render(self):
        from trajectory_graph.render import render_tree
        previous = Path.cwd()
        try:
            os.chdir(self.base)
            with patch.dict(os.environ, {}, clear=True):
                args = parser().parse_args(['build', '--input', str(self.input)])
            self.assertEqual(args.model, 'deepseek-flash')
            self.assertEqual(args.adapter, 'terminal-bench-2.0')
            self.assertEqual((args.merge_window, args.merge_window_max,
                              args.merge_input_tokens, args.merge_lookback),
                             (16, 64, 65536, 1))
            run(args, transport=Model())
            directory = self.base / 'runs/terminal-bench-2.0/input'
            run(parser().parse_args(['render', '--input', str(directory)]))
            page = (directory / 'tree.html').read_text()
            self.assertIn('安装缺少的依赖', page)
            self.assertIn('ModuleNotFoundError', page)
            self.assertIn('event-0002', page)
            self.assertIn('Agent 回合', page)
            self.assertIn("class:'task-dependency-edge'", page)
            self.assertIn("marker-end', 'url(#task-arrow)'", page)
            self.assertNotIn('cross-trigger-edge', page)
            self.assertNotIn('return-edge', page)
            embedded = json.loads(re.search(
                r'<script id="tree-data" type="application/json">(.*?)</script>',
                page, re.S).group(1))
            self.assertEqual(set(embedded), {'turn_nodes', 'task_groups', 'root_group_id',
                                             'task_edges'})
            self.assertEqual(len(embedded['turn_nodes']), 6)
            self.assertTrue(all('children' not in node and node['owner_group_id']
                                for node in embedded['turn_nodes']))
            self.assertTrue(all('items' in group and 'turn_ids' in group and 'leaf' in group
                                for group in embedded['task_groups']))
            self.assertTrue(any(group['parent_group_id'] is not None
                                for group in embedded['task_groups']))
            self.assertNotIn('.task-node.task', page)
            self.assertIn("groupFillLayer = el('g', {class:'group-fill-layer'})", page)
            self.assertIn("groupOutlineLayer = el('g', {class:'group-outline-layer'})", page)
            self.assertIn('viewport.append(defs, groupFillLayer, edgeLayer, nodeLayer, groupOutlineLayer)', page)
            self.assertIn('const taskEdges = graph.task_edges || []', page)
            self.assertEqual(len(embedded['task_edges']), 5)
            self.assertTrue(all(edge['reason'] ==
                                'Source tool results determine the target task actions.'
                                for edge in embedded['task_edges']))
            self.assertTrue(any(edge['trigger_tool_call_ids'] == ['c2'] and
                                edge['target_event_ids'] == ['event-0002']
                                for edge in embedded['task_edges']))
            self.assertTrue(any(edge['trigger_tool_call_ids'] == ['c4'] and
                                edge['target_event_ids'] == ['event-0004']
                                for edge in embedded['task_edges']))
            self.assertIn("markerUnits:'userSpaceOnUse'", page)
            self.assertIn('.task-dependency-edge{', page)
            self.assertIn('蓝色箭头和标签：子任务信息依赖及原因', page)
            self.assertIn("const collapsed = new Set();", page)
            self.assertIn('默认展开全部任务', page)
            self.assertIn('function dependencyLayers(group)', page)
            self.assertIn("layoutDirection === 'down'", page)
            self.assertIn('const manualOffsets = new Map()', page)
            self.assertIn('function startItemDrag(event, id)', page)
            self.assertIn('function freeEdgeRoute(source, target)', page)
            self.assertIn('function resizeGroupsToContents()', page)
            self.assertIn('黄色框与依赖边随节点实时重绘', page)
            self.assertIn('edge.reason', page)
            self.assertIn('function applyConnectionFocus()', page)
            self.assertIn('.focus-active .turn-node.focus-dimmed', page)
            trace_path = directory / 'normalized_trace.json'
            trace = json.loads(trace_path.read_text())
            trace['events'][-2]['tool_calls'][0]['observation']['raw'] = '</pre><script>alert(1)</script>'
            trace_path.write_text(json.dumps(trace))
            render_tree(directory / 'execution_tree.json', trace_path, directory / 'tree.html')
            page = (directory / 'tree.html').read_text()
            self.assertNotIn('<script>alert(1)</script>', page)
            self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)
            with self.assertRaises(Invalid):
                render_tree(directory / 'execution_tree.json', trace_path, trace_path)
        finally:
            os.chdir(previous)

    def test_terminal_bench_2_adapter_rejects_claude_code_trajectory(self):
        data = fixture()
        data['agent'] = {'name': 'claude-code', 'version': '2.1.257'}
        self.input.write_text(json.dumps(data, ensure_ascii=False))
        with self.assertRaisesRegex(
                Invalid, "terminal-bench-2.0 adapter requires agent.name='terminus-2'"):
            load(self.input)


if __name__ == '__main__':
    unittest.main()
