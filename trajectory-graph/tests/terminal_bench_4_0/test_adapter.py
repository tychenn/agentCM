import json
import os
import tempfile
import unittest
from pathlib import Path

from trajectory_graph.adapters.terminal_bench_4_0.annotation import (
    ACTION_TYPES, _compact_image_observation, annotate_event, attach_tool_calls)
from trajectory_graph.adapters.terminal_bench_4_0.normalize import (
    derive_goal_seed, load, normalize, prepare)
from trajectory_graph.cli import parser, run
from trajectory_graph.deepseek_client import Client
from trajectory_graph.render import render_tree
from trajectory_graph.validate import Invalid, agent_turns


def fixture():
    return {
        'schema_version': 'ATIF-v1.7',
        'session_id': 'tb4-test',
        'agent': {
            'name': 'claude-code',
            'version': '2.1.257',
            'model_name': 'claude-opus-5',
        },
        'steps': [
            {'step_id': 1, 'source': 'user', 'message': '检查输入，生成并验证报告'},
            {
                'step_id': 2,
                'source': 'agent',
                'message': '',
                'tool_calls': [
                    {
                        'tool_call_id': 'call-read',
                        'function_name': 'Bash',
                        'arguments': {
                            'command': 'ls -la /app/data',
                            'description': 'Inspect input files',
                        },
                    },
                    {
                        'tool_call_id': 'call-schema',
                        'function_name': 'Bash',
                        'arguments': {
                            'command': 'head /app/data/schema.json',
                            'description': 'Inspect report schema',
                        },
                    },
                ],
                'observation': {'results': [
                    {
                        'source_call_id': 'call-read',
                        'content': 'input.csv\nschema.json\n',
                        'extra': {'tool_result_is_error': False},
                    },
                    {
                        'source_call_id': 'call-schema',
                        'content': '{"required":["result"]}\n',
                        'extra': {'tool_result_is_error': False},
                    },
                ]},
            },
            {
                'step_id': 3,
                'source': 'agent',
                'message': 'The inputs are ready.',
                'tool_calls': [{
                    'tool_call_id': 'call-write',
                    'function_name': 'Bash',
                    'arguments': {
                        'command': 'python make_report.py',
                        'description': 'Generate and validate report',
                    },
                }],
                'observation': {'results': [{
                    'source_call_id': 'call-write',
                    'content': 'saved /app/output/report.json\nvalidation passed\n',
                    'extra': {'tool_result_is_error': False},
                }]},
            },
            {
                'step_id': 4,
                'source': 'agent',
                'message': 'Report complete.',
            },
        ],
    }


class Model:
    def __init__(self):
        self.annotation_inputs = []
        self.dependency_inputs = []

    @staticmethod
    def response(value):
        return {'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps(value, ensure_ascii=False),
        }}]}

    def __call__(self, payload):
        system, user = [message['content'] for message in payload['messages']]
        if 'You extract' in system:
            return self.response({
                'title': '报告生成', 'query': '检查输入，生成并验证报告',
                'review_flags': [],
            })
        if 'Annotate one fixed Terminal-Bench 4.0 tool-call node' in system:
            event = json.loads(user.split('TOOL-CALL NODE\n', 1)[1])
            self.annotation_inputs.append(event)
            call = event['tool_calls'][0]
            descriptions = {
                'call-read': ('inspect', '/app/data', 'Found input.csv and schema.json.', []),
                'call-schema': ('inspect', '/app/data/schema.json',
                                'Found the required result field.', []),
                'call-write': ('validate', '/app/output/report.json',
                               'Created the report and validation passed.',
                               ['/app/output/report.json']),
            }
            action, target, result, artifacts = descriptions[call['tool_call_id']]
            return self.response({
                'tool_call_id': call['tool_call_id'],
                'goal': event['goal_seed'],
                'action_type': action,
                'target': target,
                'status': 'completed',
                'result': result,
                'artifacts': artifacts,
                'review_flags': [],
            })
        if 'Decide the first leaf-task boundary' in system:
            data = json.loads(user.split('LOCAL GROUPING INPUT\n', 1)[1])
            cards = data['candidates']
            return self.response({
                'action': 'merge',
                'member_ids': [card['node_id'] for card in cards],
                'task': {
                    'goal': '检查输入并生成报告',
                    'completion_condition': '报告生成且校验通过',
                    'status': 'completed',
                    'reason': '这些调用共同完成报告交付',
                    'result': '报告已生成并通过校验',
                    'source_event_ids': [card['node_id'] for card in cards],
                },
                'review_flags': [],
            })
        if 'Summarize the supplied completed task-tree frontier' in system:
            return self.response({
                'status': 'completed', 'result': '报告已生成并通过校验',
                'review_flags': [],
            })
        if 'Identify which earlier tool-call results directly informed' in system:
            target = json.loads(user.split('TARGET TOOL-CALL NODE\n', 1)[1])
            prior = json.loads(
                user.split('PRIOR TOOL-CALL NODES IN TRAJECTORY ORDER\n', 1)[1]
                    .split('\nTARGET TOOL-CALL NODE\n', 1)[0])
            self.dependency_inputs.append((target['event_id'], prior))
            return self.response({
                'target_event_id': target['event_id'],
                'trigger_tool_call_ids': [],
            })
        raise AssertionError('Unexpected model request:\n' + system)


class TerminalBench4AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.input = self.base / 'input.json'
        self.input.write_text(json.dumps(fixture(), ensure_ascii=False))

    def tearDown(self):
        self.temp.cleanup()

    def test_prepare_expands_calls_and_aligns_observations_locally(self):
        source, metadata = load(self.input)
        prepared, flags = prepare(source)
        events = [event for event, observations in prepared]
        self.assertEqual(metadata['adapter'], 'terminal-bench-4.0')
        self.assertEqual(len(events), 3)
        self.assertTrue(all(not observations for _, observations in prepared))
        self.assertEqual([event['step_id'] for event in events], [2, 2, 3])
        self.assertEqual(events[0]['goal_seed'], 'Inspect input files')
        self.assertNotIn('thought', events[0])
        self.assertEqual(events[0]['goal_seed_source'], 'arguments.description')
        self.assertEqual(events[0]['tool_calls'][0]['observation']['raw'],
                         'input.csv\nschema.json\n')
        self.assertFalse(events[0]['tool_calls'][0]['observation']['is_error'])
        self.assertEqual(events[-1]['following_context_messages'], [{
            'step_id': 4, 'source': 'agent', 'message': 'Report complete.',
        }])
        self.assertEqual(flags, [])

    def test_goal_seed_fallback_for_tool_without_description(self):
        seed, source = derive_goal_seed({
            'function_name': 'Read',
            'arguments': {'file_path': '/tmp/result.json'},
        })
        self.assertEqual(seed, 'Read /tmp/result.json')
        self.assertEqual(source, 'derived_from_tool_call')

    def test_adapter_semantics_do_not_leak_into_shared_engines(self):
        root = Path(__file__).resolve().parents[2]
        for relative in (
                'src/trajectory_graph/grouping.py',
                'src/trajectory_graph/dependencies.py',
                'src/trajectory_graph/validate.py',
                'src/trajectory_graph/render.py'):
            source = (root / relative).read_text(encoding='utf-8')
            for adapter_field in (
                    'goal_seed', 'action_type', 'source_tool_index', 'thought'):
                self.assertNotIn(adapter_field, source, relative)

        tb2 = root / 'src/trajectory_graph/adapters/terminal_bench_2_0'
        tb4 = root / 'src/trajectory_graph/adapters/terminal_bench_4_0'
        for adapter in (tb2, tb4):
            for module in ('normalize.py', 'annotation.py', 'grouping.py',
                           'dependencies.py', 'validate.py', 'render.py'):
                self.assertTrue((adapter / module).is_file(), str(adapter / module))
            for prompt in ('group_leaf_v1.md', 'group_leaf_user.md',
                           'select_dependencies_v1.md',
                           'select_dependencies_user.md'):
                self.assertTrue((adapter / 'prompts' / prompt).is_file(),
                                str(adapter / 'prompts' / prompt))

    def test_load_rejects_non_local_or_reordered_observation(self):
        data = fixture()
        data['steps'][1]['observation']['results'].reverse()
        self.input.write_text(json.dumps(data))
        with self.assertRaisesRegex(Invalid, 'observations must match tool calls'):
            load(self.input)

    def test_annotation_adds_semantics_and_program_source_reference(self):
        source, metadata = load(self.input)
        event = prepare(source)[0][0][0]
        model = Model()
        client = Client(self.base / 'run', transport=model)
        result = annotate_event(client, event, client.max_tokens)
        turn = result['turn']
        self.assertEqual(turn['action_type'], 'inspect')
        self.assertEqual(turn['target'], '/app/data')
        self.assertEqual(turn['artifacts'], [])
        self.assertEqual(turn['source_refs'][0]['quote'], 'Inspect input files')
        self.assertEqual(set(ACTION_TYPES), {
            'inspect', 'search', 'compute', 'write', 'edit', 'execute',
            'validate', 'communicate', 'delegate', 'control', 'other',
        })
        trace = normalize(source, metadata, client)
        turns = attach_tool_calls({'turns': [turn], 'review_flags': []}, {
            **trace, 'events': trace['events'][:1],
        })
        self.assertEqual(turns, [turn])

    def test_image_observation_is_compacted_only_for_model_input(self):
        source, _ = load(self.input)
        event = prepare(source)[0][0][0]
        image = {
            'type': 'image',
            'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'AAAA'},
            'dimensions': {'width': 10, 'height': 20},
        }
        event['tool_calls'][0]['observation']['raw'] = json.dumps(image)
        model_event, flag = _compact_image_observation(event)
        compacted = json.loads(model_event['tool_calls'][0]['observation']['raw'])
        self.assertEqual(json.loads(event['tool_calls'][0]['observation']['raw']), image)
        self.assertNotIn('data', compacted['source'])
        self.assertTrue(compacted['source']['data_omitted'])
        self.assertEqual(compacted['source']['encoded_length'], 4)
        self.assertIn('complete source observation is still saved', flag)

    def test_trailing_reply_is_not_sent_as_tool_call_evidence(self):
        source, _ = load(self.input)
        event = prepare(source)[0][-1][0]
        self.assertIn('following_context_messages', event)
        model_event, flag = _compact_image_observation(event)
        self.assertNotIn('following_context_messages', model_event)
        self.assertIsNone(flag)

    def test_build_reuses_recursive_tree_and_excludes_same_step_dependencies(self):
        previous = Path.cwd()
        model = Model()
        output = self.base / 'run'
        try:
            os.chdir(self.base)
            args = parser().parse_args([
                'build', '--adapter', 'terminal-bench-4.0',
                '--input', str(self.input), '--output', str(output),
            ])
            run(args, transport=model)
        finally:
            os.chdir(previous)
        trace = json.loads((output / 'normalized_trace.json').read_text())
        tree = json.loads((output / 'execution_tree.json').read_text())
        turns = list(agent_turns(tree['root']))
        self.assertEqual(len(trace['events']), 3)
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[-1]['artifacts'], ['/app/output/report.json'])
        self.assertEqual([item[0] for item in model.dependency_inputs], ['event-0003'])
        self.assertEqual(
            [node['event_id'] for node in model.dependency_inputs[0][1]],
            ['event-0001', 'event-0002'])
        render_tree(output / 'execution_tree.json', output / 'normalized_trace.json',
                    output / 'tree.html', output / 'local_graphs.json')
        page = (output / 'tree.html').read_text()
        self.assertIn('工具调用语义', page)
        self.assertIn('本次调用结果', page)
        self.assertIn('工具调用 1 · step 2', page)
        self.assertIn('3 个 工具调用', page)
        self.assertIn('任务、工具调用与依赖详情', page)
        self.assertIn('后续最终回复', page)


if __name__ == '__main__':
    unittest.main()
