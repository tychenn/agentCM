"""Select, project, and explain task information dependencies."""
import copy

from .validate import (atomic_nodes, dependency_choice, dependency_reasons,
                       local_graphs, require, tasks)


def build_dependency_evidence(
        trace, turns, client, *, card_builder, eligible_prior, system_prompt,
        user_prompt, evidence_validator):
    """Ask only which earlier tool results directly inform each later turn."""
    events = {event['event_id']: event for event in trace['events']}
    records = []
    for index, turn in enumerate(turns):
        target_event_id = turn['event_id']
        if index == 0:
            choice = {'target_event_id': target_event_id, 'trigger_tool_call_ids': []}
        else:
            prior_turns = [
                card_builder(prior, events)
                for prior in turns[:index]
                if eligible_prior(events[prior['event_id']], events[target_event_id])
            ]
            prior_call_ids = [
                call['tool_call_id']
                for prior in prior_turns
                for call in prior['tool_calls']
            ]
            if prior_call_ids:
                choice = client.ask(
                    f'depend-{target_event_id}', [system_prompt],
                    user_prompt,
                    {
                        'root_query_json': {
                            'title': trace['query']['title'],
                            'text': trace['query']['text'],
                        },
                        'prior_turns_json': prior_turns,
                        'target_turn_json': card_builder(turn, events),
                    },
                    lambda value, target=target_event_id, calls=prior_call_ids:
                        dependency_choice(value, target, calls),
                    output_tokens=client.max_tokens,
                    thinking=True,
                )
            else:
                choice = {'target_event_id': target_event_id,
                          'trigger_tool_call_ids': []}
        records.append(choice)
        selected = ', '.join(choice['trigger_tool_call_ids']) or '无直接来源'
        print(f'[{target_event_id}] 信息依赖：{selected}', flush=True)
    result = {'dependencies': records, 'review_flags': []}
    evidence_validator(result, trace, turns)
    return result


def project_local_graphs(execution_tree, dependency_data, trace, *,
                         evidence_validator):
    """Lift exact call-to-turn evidence to sibling tasks at its lowest scope."""
    evidence_validator(
        dependency_data, trace, list(atomic_nodes(execution_tree['root'])))
    ordered_tasks = list(tasks(execution_tree['root']))
    parent = {}
    leaf_owner = {}

    def index_task(task, parent_id=None):
        if parent_id is not None:
            parent[task['id']] = parent_id
        if task['turns']:
            for turn in task['turns']:
                require(turn['event_id'] not in leaf_owner,
                        'Atomic node belongs to more than one leaf task')
                leaf_owner[turn['event_id']] = task['id']
        for child in task['subtasks']:
            index_task(child, task['id'])

    index_task(execution_tree['root'])
    calls = {
        call['tool_call_id']: event['event_id']
        for event in trace['events']
        for call in event['tool_calls']
    }

    def ancestors(task_id):
        result = [task_id]
        while task_id in parent:
            task_id = parent[task_id]
            result.append(task_id)
        return result

    def direct_child(ancestor_id, leaf_id):
        current = leaf_id
        while parent.get(current) != ancestor_id:
            current = parent[current]
        return current

    projected = {task['id']: [] for task in ordered_tasks}
    edge_index = {task['id']: {} for task in ordered_tasks}
    for dependency in dependency_data['dependencies']:
        target_event_id = dependency['target_event_id']
        target_leaf = leaf_owner[target_event_id]
        for call_id in dependency['trigger_tool_call_ids']:
            source_leaf = leaf_owner[calls[call_id]]
            if source_leaf == target_leaf:
                continue
            target_ancestors = set(ancestors(target_leaf))
            common = next(task_id for task_id in ancestors(source_leaf)
                          if task_id in target_ancestors)
            source_task_id = direct_child(common, source_leaf)
            target_task_id = direct_child(common, target_leaf)
            require(source_task_id != target_task_id,
                    'Projected dependency endpoints must differ')
            pair = (source_task_id, target_task_id)
            if pair not in edge_index[common]:
                edge_index[common][pair] = len(projected[common])
                projected[common].append({
                    'source_task_id': source_task_id,
                    'target_task_id': target_task_id,
                    'evidence': [],
                })
            edge = projected[common][edge_index[common][pair]]
            edge['evidence'].append({
                'tool_call_id': call_id,
                'target_event_id': target_event_id,
            })

    result = {'local_graphs': [
        {'task_id': task['id'], 'edges': projected[task['id']]}
        for task in ordered_tasks
    ]}
    local_graphs(result, execution_tree, trace, dependency_data,
                 require_reasons=False)
    return result


def add_dependency_reasons(
        execution_tree, skeleton, dependency_data, trace, client, *,
        target_context):
    """Have DeepSeek write one concise reason for every fixed task edge."""
    local_graphs(skeleton, execution_tree, trace, dependency_data,
                 require_reasons=False)
    flat_edges = [
        edge
        for local in skeleton['local_graphs']
        for edge in local['edges']
    ]
    if not flat_edges:
        local_graphs(skeleton, execution_tree, trace, dependency_data)
        return skeleton

    task_by_id = {task['id']: task for task in tasks(execution_tree['root'])}
    turn_by_id = {node['event_id']: node for node in atomic_nodes(execution_tree['root'])}
    event_by_id = {event['event_id']: event for event in trace['events']}
    calls = {
        call['tool_call_id']: (event, call)
        for event in trace['events']
        for call in event['tool_calls']
    }

    def task_card(task_id):
        task = task_by_id[task_id]
        return {
            'task_id': task_id,
            'goal': task['goal'],
            'result': task['result'],
        }

    supplied_edges = []
    for edge in flat_edges:
        evidence_cards = []
        for evidence in edge['evidence']:
            call_id = evidence['tool_call_id']
            target_event_id = evidence['target_event_id']
            source_event, call = calls[call_id]
            source_turn = turn_by_id[source_event['event_id']]
            target_turn = turn_by_id[target_event_id]
            brief_result = next(
                item['result'] for item in source_turn['tool_calls']
                if item['tool_call_id'] == call_id)
            evidence_card = {
                'tool_call_id': call_id,
                'source_event_id': source_event['event_id'],
                'source_turn_goal': source_turn['goal'],
                'tool_result': brief_result,
                'observation': call['observation']['raw'],
                'target_event_id': target_event_id,
                'target_turn_goal': target_turn['goal'],
            }
            evidence_card.update(target_context(event_by_id[target_event_id]))
            evidence_cards.append(evidence_card)
        supplied_edges.append({
            'source_task': task_card(edge['source_task_id']),
            'target_task': task_card(edge['target_task_id']),
            'evidence': evidence_cards,
        })

    response = client.ask(
        'explain-dependencies', ['explain_dependencies_v1'],
        'explain_dependencies_user',
        {'dependency_edges_json': supplied_edges},
        lambda value: dependency_reasons(value, skeleton),
        output_tokens=client.max_tokens,
        thinking=True,
    )
    for edge in response['edges']:
        print(f'[dependency {edge["source_task_id"]} -> '
              f'{edge["target_task_id"]}] {edge["reason"]}', flush=True)
    reasons = {
        (edge['source_task_id'], edge['target_task_id']): edge['reason']
        for edge in response['edges']
    }
    result = copy.deepcopy(skeleton)
    for local in result['local_graphs']:
        for edge in local['edges']:
            edge['reason'] = reasons[(edge['source_task_id'], edge['target_task_id'])]
    local_graphs(result, execution_tree, trace, dependency_data)
    return result
