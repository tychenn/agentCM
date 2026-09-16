"""Strict structural and source-evidence validation, independent of the model."""
import copy
import json


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def keys(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected.split()),
            f"Expected exactly fields: {expected}")


def string(value):
    require(isinstance(value, str) and bool(value.strip()), "Expected non-empty string")


def flags(value):
    require(isinstance(value, list) and all(isinstance(x, str) for x in value),
            "review_flags must be an array of strings")


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def constant(value):
        raise Invalid(f"Invalid JSON constant: {value}")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def root_query(value):
    keys(value, "title query review_flags")
    string(value['title'])
    string(value['query'])
    flags(value['review_flags'])


def alignment_assignments(value, tool_calls):
    keys(value, 'assignments')
    require(isinstance(value['assignments'], list), 'assignments must be an array')
    ids = []
    for item in value['assignments']:
        keys(item, 'tool_call_id start_anchor')
        string(item['tool_call_id'])
        anchor = item['start_anchor']
        require(anchor is None or (isinstance(anchor, str) and bool(anchor)),
                'start_anchor must be a non-empty string or null')
        ids.append(item['tool_call_id'])
    require(ids == [call['tool_call_id'] for call in tool_calls],
            'Assignments must match input calls in order')


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


class Evidence:
    def __init__(self, trace, node_evidence_field=None):
        self.trace = trace
        self.node_evidence_field = node_evidence_field
        self.events = {e['event_id']: e for e in trace['events']}
        self.calls = {c['tool_call_id']: (e, c) for e in trace['events'] for c in e['tool_calls']}

    def refs(self, refs, event_id=None):
        require(isinstance(refs, list) and bool(refs), 'Node needs source evidence')
        has_node_evidence = False
        for ref in refs:
            keys(ref, 'event_id tool_call_id field quote')
            string(ref['quote'])
            eid, cid, field = ref['event_id'], ref['tool_call_id'], ref['field']
            if event_id is not None:
                require(eid == event_id, 'Atomic-node evidence must stay in its own event')
            if eid == 'query':
                require(cid is None and field == 'source_raw', 'Invalid query reference')
                texts = [self.trace['query']['source_raw']]
            else:
                require(isinstance(eid, str) and eid in self.events, 'Unknown event reference')
                if cid is None:
                    require(field == self.node_evidence_field and
                            field in self.events[eid],
                            f'Node-level reference must use {self.node_evidence_field}')
                    texts = [self.events[eid][field]]
                    has_node_evidence = True
                else:
                    require(isinstance(cid, str) and cid in self.calls, 'Unknown call reference')
                    event, call = self.calls[cid]
                    require(event['event_id'] == eid, 'Call and event reference disagree')
                    require(field in ('arguments', 'observation.raw'), 'Invalid tool evidence field')
                    texts = strings(call['arguments']) if field == 'arguments' else [call['observation']['raw']]
            require(any(ref['quote'] in s for s in texts), 'Evidence quote does not match source')
        if event_id is not None:
            require(has_node_evidence,
                    f'Atomic node needs current {self.node_evidence_field} evidence for its goal')


TURN_STATUS = {'completed', 'failed', 'incomplete', 'uncertain'}
TASK_STATUS = {'active', 'suspended', 'completed', 'failed', 'abandoned', 'uncertain'}


def dependency_choice(value, target_event_id, prior_call_ids):
    keys(value, 'target_event_id trigger_tool_call_ids')
    require(value['target_event_id'] == target_event_id,
            'Dependency target event changed')
    trigger_ids = value['trigger_tool_call_ids']
    require(isinstance(trigger_ids, list),
            'trigger_tool_call_ids must be an array')
    require(all(isinstance(call_id, str) and bool(call_id.strip())
                for call_id in trigger_ids),
            'trigger_tool_call_ids must contain non-empty strings')
    require(len(trigger_ids) == len(set(trigger_ids)),
            'trigger_tool_call_ids must not contain duplicates')
    prior_positions = {call_id: index for index, call_id in enumerate(prior_call_ids)}
    require(all(call_id in prior_positions for call_id in trigger_ids),
            'Every trigger_tool_call_id must belong to an eligible prior node')
    positions = [prior_positions[call_id] for call_id in trigger_ids]
    require(positions == sorted(positions),
            'trigger_tool_call_ids must follow prior trajectory order')


def expand_turn_refs(value, canonical_nodes):
    """Replace model-returned event references with immutable program nodes."""
    result = copy.deepcopy(value)
    canonical = {node['event_id']: node for node in canonical_nodes}
    def walk(node):
        require(isinstance(node, dict), 'Invalid task')
        require(isinstance(node.get('subtasks'), list) and
                isinstance(node.get('turn_event_ids'), list), 'Invalid task contents')
        node['turns'] = []
        for event_id in node.pop('turn_event_ids'):
            require(event_id in canonical, 'Unknown atomic event reference')
            node['turns'].append(copy.deepcopy(canonical[event_id]))
        for child in node['subtasks']:
            walk(child)
    keys(result, 'root review_flags')
    walk(result['root'])
    return result


def canonicalize_root(value, trace):
    """Root identity comes from preprocessing, not model transcription."""
    result = copy.deepcopy(value)
    require(isinstance(result, dict) and isinstance(result.get('root'), dict), 'Missing root task')
    result['root']['goal'] = trace['query']['text']
    result['root']['reason'] = None
    return result


def materialize_group_evidence(value, trace, canonical_nodes):
    """Copy exact, already validated evidence after the model selects event IDs."""
    result = copy.deepcopy(value)
    keys(result, 'root review_flags')
    canonical = {node['event_id']: node for node in canonical_nodes}

    def walk(node, is_root=False):
        require(isinstance(node, dict), 'Invalid composite task')
        keys(node, 'id goal status reason result source_event_ids subtasks turn_event_ids')
        selected = node.pop('source_event_ids')
        require(isinstance(selected, list) and all(
            isinstance(event_id, str) and event_id in canonical for event_id in selected),
            'source_event_ids must contain known atomic-node IDs')
        require(len(selected) == len(set(selected)),
                'source_event_ids must not contain duplicates')
        descendants = []
        require(isinstance(node['subtasks'], list), 'subtasks must be an array')
        require(isinstance(node['turn_event_ids'], list), 'turn_event_ids must be an array')
        has_subtasks, has_turns = bool(node['subtasks']), bool(node['turn_event_ids'])
        require(has_subtasks != has_turns,
                'Each task must contain either subtasks or atomic nodes')
        if has_subtasks:
            require(len(node['subtasks']) >= 2,
                    'Composite task needs at least two direct subtasks')
            for child in node['subtasks']:
                descendants.extend(walk(child))
        else:
            require(len(node['turn_event_ids']) == len(set(node['turn_event_ids'])),
                    'Leaf task turn_event_ids must not contain duplicates')
            for event_id in node['turn_event_ids']:
                require(event_id in canonical, 'Unknown atomic event reference')
                descendants.append(event_id)
        if is_root:
            require(not selected, 'Root source_event_ids must be empty')
            node['source_refs'] = [{
                'event_id': 'query', 'tool_call_id': None, 'field': 'source_raw',
                'quote': trace['query']['source_raw'],
            }]
        else:
            require(bool(selected), 'Non-root composite task needs source_event_ids')
            require(set(selected).issubset(descendants),
                    'Composite evidence event must be one of its descendants')
            selected_set = set(selected)
            node['source_refs'] = []
            for event_id in descendants:
                if event_id in selected_set:
                    node['source_refs'].extend(copy.deepcopy(canonical[event_id]['source_refs']))
        return descendants

    walk(result['root'], True)
    return result


def tasks(node):
    yield node
    for child in node['subtasks']:
        yield from tasks(child)


def atomic_nodes(node):
    for atomic_node in node['turns']:
        yield atomic_node
    for child in node['subtasks']:
        yield from atomic_nodes(child)


# Compatibility name for the persisted schema, whose atomic-node array remains
# named ``turns`` so existing Terminal-Bench 2.0 artifacts stay readable.
agent_turns = atomic_nodes


def tree(value, trace, canonical_nodes=None, *, atomic_validator,
         node_evidence_field):
    keys(value, 'root review_flags')
    flags(value['review_flags'])
    evidence = Evidence(trace, node_evidence_field=node_evidence_field)
    ids, turns_seen = set(), []
    canonical = ({node['event_id']: node for node in canonical_nodes}
                 if canonical_nodes is not None else None)
    def visit(node, is_root=False):
        keys(node, 'id goal status reason result source_refs subtasks turns')
        string(node['id'])
        require(node['id'] not in ids, 'Duplicate task ID')
        ids.add(node['id'])
        string(node['goal'])
        require(node['status'] in TASK_STATUS, 'Invalid task status')
        if is_root:
            require(node['reason'] is None, 'Root reason must be null')
            require(node['goal'] == trace['query']['text'], 'Root goal must equal supplied query')
        else:
            string(node['reason'])
        if node['result'] is not None:
            string(node['result'])
        evidence.refs(node['source_refs'])
        require(isinstance(node['subtasks'], list), 'subtasks must be an array')
        require(isinstance(node['turns'], list), 'turns must be an array')
        has_subtasks, has_turns = bool(node['subtasks']), bool(node['turns'])
        require(has_subtasks != has_turns,
                'Each task must contain either subtasks or atomic nodes')
        if has_subtasks:
            require(len(node['subtasks']) >= 2,
                    'Composite task needs at least two direct subtasks')
            for child in node['subtasks']:
                require(isinstance(child, dict), 'Invalid child task')
                visit(child)
        else:
            for atomic_node in node['turns']:
                require(isinstance(atomic_node, dict), 'Invalid atomic node')
                atomic_validator(atomic_node, evidence)
                if canonical is not None:
                    require(atomic_node == canonical.get(atomic_node['event_id']),
                            'Atomic node was changed while grouping')
                turns_seen.append(atomic_node['event_id'])
    visit(value['root'], True)
    expected = [e['event_id'] for e in trace['events'] if e['source'] == 'agent']
    require(turns_seen == expected, 'Atomic nodes omitted, duplicated, or reordered')

def stable_ids(value):
    result = copy.deepcopy(value)
    mapping = {n['id']: f'task-{i:04d}' for i, n in enumerate(tasks(result['root']), 1)}
    for node in tasks(result['root']):
        node['id'] = mapping[node['id']]
    return result, mapping


def dependency_reasons(value, skeleton):
    keys(value, 'edges')
    require(isinstance(value['edges'], list), 'Dependency reasons edges must be an array')
    expected = [
        (edge['source_task_id'], edge['target_task_id'])
        for local in skeleton['local_graphs']
        for edge in local['edges']
    ]
    actual = []
    for edge in value['edges']:
        keys(edge, 'source_task_id target_task_id reason')
        string(edge['source_task_id'])
        string(edge['target_task_id'])
        string(edge['reason'])
        require(len(edge['reason']) <= 100,
                'Dependency reason exceeds 100 characters')
        actual.append((edge['source_task_id'], edge['target_task_id']))
    require(actual == expected,
            'Dependency reason response must preserve every supplied edge in order')


def local_graphs(value, execution_tree, trace, dependencies=None, require_reasons=True):
    keys(value, 'local_graphs')
    require(isinstance(value['local_graphs'], list), 'local_graphs must be an array')
    require(all(isinstance(entry, dict) for entry in value['local_graphs']),
            'Every local graph must be an object')
    ordered_tasks = list(tasks(execution_tree['root']))
    require([entry.get('task_id') for entry in value['local_graphs']] ==
            [task['id'] for task in ordered_tasks],
            'local_graphs must contain every task exactly once in tree order')
    evidence = Evidence(trace)
    event_order = {event['event_id']: index for index, event in enumerate(trace['events'])}
    descendant_turns = {
        task['id']: [node['event_id'] for node in atomic_nodes(task)]
        for task in ordered_tasks
    }
    seen_evidence = []
    for task, entry in zip(ordered_tasks, value['local_graphs']):
        keys(entry, 'task_id edges')
        require(entry['task_id'] == task['id'], 'Local graph task ID changed')
        require(isinstance(entry['edges'], list), 'Local graph edges must be an array')
        child_ids = [child['id'] for child in task['subtasks']]
        child_position = {child_id: index for index, child_id in enumerate(child_ids)}
        edge_pairs = set()
        for edge in entry['edges']:
            keys(edge, ('source_task_id target_task_id reason evidence'
                        if require_reasons else
                        'source_task_id target_task_id evidence'))
            source_id, target_id = edge['source_task_id'], edge['target_task_id']
            if require_reasons:
                string(edge['reason'])
                require(len(edge['reason']) <= 100,
                        'Dependency reason exceeds 100 characters')
            require(source_id in child_position and target_id in child_position,
                    'Dependency endpoints must be direct subtasks of the local task')
            require(child_position[source_id] < child_position[target_id],
                    'Information dependency must follow task execution order')
            pair = (source_id, target_id)
            require(pair not in edge_pairs, 'Duplicate local dependency edge')
            edge_pairs.add(pair)
            require(isinstance(edge['evidence'], list) and bool(edge['evidence']),
                    'Dependency edge needs evidence')
            local_seen = set()
            for item in edge['evidence']:
                keys(item, 'tool_call_id target_event_id')
                call_id, target_event_id = item['tool_call_id'], item['target_event_id']
                require((call_id, target_event_id) not in local_seen,
                        'Duplicate dependency evidence')
                local_seen.add((call_id, target_event_id))
                require(call_id in evidence.calls, 'Unknown dependency tool call')
                source_event, _ = evidence.calls[call_id]
                require(source_event['event_id'] in descendant_turns[source_id],
                        'Dependency tool call must belong to the source task')
                require(target_event_id in descendant_turns[target_id],
                        'Dependency target event must belong to the target task')
                require(event_order[source_event['event_id']] < event_order[target_event_id],
                        'Dependency source must precede its target event')
                seen_evidence.append((call_id, target_event_id))
    if dependencies is not None:
        expected = []
        call_event = {call_id: event['event_id'] for call_id, (event, _) in evidence.calls.items()}
        leaf_owner = {}
        for task in ordered_tasks:
            if task['turns']:
                for turn in task['turns']:
                    leaf_owner[turn['event_id']] = task['id']
        for item in dependencies['dependencies']:
            target = item['target_event_id']
            for call_id in item['trigger_tool_call_ids']:
                if leaf_owner[call_event[call_id]] != leaf_owner[target]:
                    expected.append((call_id, target))
        require(sorted(seen_evidence) == sorted(expected),
                'Local graphs must preserve every cross-task dependency exactly once')
