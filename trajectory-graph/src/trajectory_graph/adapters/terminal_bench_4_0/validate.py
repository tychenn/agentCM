"""Terminal-Bench 4.0 node, dependency, and tree validation."""
import copy

from ... import validate as common


NODE_FIELDS = set(
    'event_id goal action_type target status result artifacts source_refs tool_calls'.split())


def _artifacts(value):
    common.require(isinstance(value, list), 'artifacts must be an array')
    common.require(len(value) <= 20, 'artifacts exceeds 20 entries')
    common.require(all(
        isinstance(item, str) and bool(item.strip()) and len(item) <= 300
        for item in value),
        'artifacts must contain non-empty strings of at most 300 characters')
    common.require(len(value) == len(set(value)),
                   'artifacts must not contain duplicates')


def _atomic_node(node, evidence):
    common.require(isinstance(node, dict) and set(node) == NODE_FIELDS,
                   'Invalid Terminal-Bench 4.0 tool-call node fields')
    event_id = node['event_id']
    common.require(isinstance(event_id, str) and event_id in evidence.events,
                   'Unknown tool-call event')
    event = evidence.events[event_id]
    common.require(event.get('node_kind') == 'tool_call',
                   'Terminal-Bench 4.0 tree can contain only tool-call nodes')
    common.string(node['goal'])
    common.require(len(node['goal']) <= 240, 'Tool-call goal exceeds 240 characters')
    common.require(node['action_type'] in {
        'inspect', 'search', 'compute', 'write', 'edit', 'execute', 'validate',
        'communicate', 'delegate', 'control', 'other',
    }, 'Invalid action_type')
    if node['target'] is not None:
        common.string(node['target'])
        common.require(len(node['target']) <= 300,
                       'Tool-call target exceeds 300 characters')
    common.require(node['status'] in common.TURN_STATUS,
                   'Invalid tool-call node status')
    if node['result'] is not None:
        common.string(node['result'])
        common.require(len(node['result']) <= 300,
                       'Tool-call result exceeds 300 characters')
    _artifacts(node['artifacts'])
    evidence.refs(node['source_refs'], event_id)
    common.require(isinstance(node['tool_calls'], list),
                   'tool_calls must be an array')
    for call in node['tool_calls']:
        common.keys(call, 'tool_call_id result')
        if call['result'] is not None:
            common.string(call['result'])
    common.require(
        [call['tool_call_id'] for call in node['tool_calls']] ==
        [call['tool_call_id'] for call in event['tool_calls']],
        'Tool-call node must contain its one original call')


def node_annotations(value, trace):
    """Validate the complete ordered Terminal-Bench 4.0 node list."""
    common.keys(value, 'turns review_flags')
    common.flags(value['review_flags'])
    common.require(isinstance(value['turns'], list), 'turns must be an array')
    evidence = common.Evidence(trace, node_evidence_field='goal_seed')
    expected = [event['event_id'] for event in trace['events']]
    actual = []
    for node in value['turns']:
        _atomic_node(node, evidence)
        actual.append(node['event_id'])
    common.require(actual == expected,
                   'Tool-call nodes must match every normalized event in order')


def dependency_evidence(value, trace, canonical_nodes):
    """Reject dependencies between calls emitted in the same source step."""
    common.keys(value, 'dependencies review_flags')
    common.flags(value['review_flags'])
    common.require(isinstance(value['dependencies'], list),
                   'dependencies must be an array')
    expected = [event['event_id'] for event in trace['events']]
    common.require([node['event_id'] for node in canonical_nodes] == expected,
                   'Canonical tool-call nodes do not match the trace')
    common.require(len(value['dependencies']) == len(expected),
                   'Dependency evidence needs one record per tool-call node')
    events = {event['event_id']: event for event in trace['events']}
    prior_calls = []
    for expected_target, item, node in zip(
            expected, value['dependencies'], canonical_nodes):
        target_step = events[expected_target]['step_id']
        eligible = [call_id for call_id, step_id in prior_calls
                    if step_id != target_step]
        common.dependency_choice(item, expected_target, eligible)
        prior_calls.extend(
            (call['tool_call_id'], target_step) for call in node['tool_calls'])


def tree(value, trace, canonical_nodes=None):
    """Validate a recursive tree containing 4.0 tool-call nodes."""
    common.tree(
        value, trace, canonical_nodes,
        atomic_validator=_atomic_node,
        node_evidence_field='goal_seed',
    )


def expand_grouping(value, trace, canonical_nodes):
    """Materialize exact evidence and nodes, then apply the 4.0 schema."""
    result = common.canonicalize_root(value, trace)
    result = common.materialize_group_evidence(result, trace, canonical_nodes)
    result = common.expand_turn_refs(result, canonical_nodes)
    tree(result, trace, canonical_nodes)
    return result


def attach_nodes(value, trace):
    result = copy.deepcopy(value['turns'])
    node_annotations({'turns': result, 'review_flags': value['review_flags']}, trace)
    return result
