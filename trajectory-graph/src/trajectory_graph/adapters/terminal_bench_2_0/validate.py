"""Terminal-Bench 2.0 validation contracts."""

from ... import validate as common


NODE_FIELDS = 'event_id goal status result source_refs tool_calls'


def _atomic_node(turn, evidence):
    common.keys(turn, NODE_FIELDS)
    event_id = turn['event_id']
    common.require(isinstance(event_id, str) and event_id in evidence.events,
                   'Unknown Agent turn event')
    event = evidence.events[event_id]
    common.require(event['source'] == 'agent',
                   'Only agent events can be Agent turns')
    common.string(turn['goal'])
    common.require(turn['status'] in common.TURN_STATUS,
                   'Invalid Agent turn status')
    if turn['result'] is not None:
        common.string(turn['result'])
    evidence.refs(turn['source_refs'], event_id)
    common.require(isinstance(turn['tool_calls'], list),
                   'tool_calls must be an array')
    for call in turn['tool_calls']:
        common.keys(call, 'tool_call_id result')
        if call['result'] is not None:
            common.string(call['result'])
    common.require(
        [call['tool_call_id'] for call in turn['tool_calls']] ==
        [call['tool_call_id'] for call in event['tool_calls']],
        'Agent turn must contain all and only its original tool calls in order',
    )


def node_annotations(value, trace):
    common.keys(value, 'turns review_flags')
    common.flags(value['review_flags'])
    common.require(isinstance(value['turns'], list), 'turns must be an array')
    evidence = common.Evidence(trace, node_evidence_field='thought')
    expected = [
        event['event_id'] for event in trace['events']
        if event['source'] == 'agent'
    ]
    actual = []
    for turn in value['turns']:
        common.keys(turn, NODE_FIELDS)
        common.string(turn['event_id'])
        common.string(turn['goal'])
        common.require(len(turn['goal']) <= 240,
                       'Turn goal exceeds 240 characters')
        common.require(turn['status'] in common.TURN_STATUS,
                       'Invalid Agent turn status')
        if turn['result'] is not None:
            common.string(turn['result'])
            common.require(len(turn['result']) <= 600,
                           'Turn result exceeds 600 characters')
        evidence.refs(turn['source_refs'], turn['event_id'])
        common.require(isinstance(turn['tool_calls'], list),
                       'tool_calls must be an array')
        expected_calls = [
            call['tool_call_id']
            for call in evidence.events[turn['event_id']]['tool_calls']
        ]
        actual_calls = []
        for call in turn['tool_calls']:
            common.keys(call, 'tool_call_id result')
            actual_calls.append(call['tool_call_id'])
            if call['result'] is not None:
                common.string(call['result'])
                common.require(len(call['result']) <= 300,
                               'Tool call result exceeds 300 characters')
        common.require(actual_calls == expected_calls,
                       'Agent turn tool calls changed or reordered')
        actual.append(turn['event_id'])
    common.require(actual == expected,
                   'Agent turns must match all agent events exactly once and in order')


def dependency_evidence(value, trace, canonical_nodes):
    common.keys(value, 'dependencies review_flags')
    common.flags(value['review_flags'])
    common.require(isinstance(value['dependencies'], list),
                   'dependencies must be an array')
    event_ids = [
        event['event_id'] for event in trace['events']
        if event['source'] == 'agent'
    ]
    canonical_ids = [node['event_id'] for node in canonical_nodes]
    common.require(canonical_ids == event_ids,
                   'Canonical Agent turns do not match the trace')
    common.require(len(value['dependencies']) == len(event_ids),
                   'Dependency evidence needs one record for every Agent turn')
    prior_call_ids = []
    for index, (expected_target, item) in enumerate(
            zip(event_ids, value['dependencies'])):
        if index == 0:
            common.keys(item, 'target_event_id trigger_tool_call_ids')
            common.require(
                item['target_event_id'] == expected_target and
                item['trigger_tool_call_ids'] == [],
                'First Agent turn must have no prior information dependency',
            )
        else:
            common.dependency_choice(item, expected_target, prior_call_ids)
        prior_call_ids.extend(
            call['tool_call_id'] for call in canonical_nodes[index]['tool_calls']
        )


def tree(value, trace, canonical_nodes=None):
    common.tree(
        value,
        trace,
        canonical_nodes,
        atomic_validator=_atomic_node,
        node_evidence_field='thought',
    )


def expand_grouping(value, trace, canonical_nodes):
    result = common.canonicalize_root(value, trace)
    result = common.materialize_group_evidence(result, trace, canonical_nodes)
    result = common.expand_turn_refs(result, canonical_nodes)
    tree(result, trace, canonical_nodes)
    return result
