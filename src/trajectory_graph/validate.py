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
    def __init__(self, trace):
        self.trace = trace
        self.events = {e['event_id']: e for e in trace['events']}
        self.calls = {c['tool_call_id']: (e, c) for e in trace['events'] for c in e['tool_calls']}

    def refs(self, refs, event_id=None):
        require(isinstance(refs, list) and bool(refs), 'Node needs source evidence')
        has_thought = False
        for ref in refs:
            keys(ref, 'event_id tool_call_id field quote')
            string(ref['quote'])
            eid, cid, field = ref['event_id'], ref['tool_call_id'], ref['field']
            if event_id is not None:
                require(eid == event_id, 'Agent turn evidence must stay in its own event')
            if eid == 'query':
                require(cid is None and field == 'source_raw', 'Invalid query reference')
                texts = [self.trace['query']['source_raw']]
            else:
                require(isinstance(eid, str) and eid in self.events, 'Unknown event reference')
                if cid is None:
                    require(field == 'thought', 'Message reference must use thought')
                    texts = [self.events[eid]['thought']]
                    has_thought = True
                else:
                    require(isinstance(cid, str) and cid in self.calls, 'Unknown call reference')
                    event, call = self.calls[cid]
                    require(event['event_id'] == eid, 'Call and event reference disagree')
                    require(field in ('arguments', 'observation.raw'), 'Invalid tool evidence field')
                    texts = strings(call['arguments']) if field == 'arguments' else [call['observation']['raw']]
            require(any(ref['quote'] in s for s in texts), 'Evidence quote does not match source')
        if event_id is not None:
            require(has_thought, 'Agent turn needs current message evidence for its goal')


TURN_STATUS = {'completed', 'failed', 'incomplete', 'uncertain'}
TASK_STATUS = {'active', 'suspended', 'completed', 'failed', 'abandoned', 'uncertain'}


def turn_annotation(value, event):
    keys(value, 'turn review_flags')
    flags(value['review_flags'])
    turn = value['turn']
    keys(turn, 'event_id goal status result tool_call_results source_refs')
    require(event['source'] == 'agent', 'Only agent events can be annotated')
    require(turn['event_id'] == event['event_id'], 'Turn event ID changed')
    string(turn['goal'])
    require(len(turn['goal']) <= 240, 'Turn goal exceeds 240 characters')
    require(turn['status'] in TURN_STATUS, 'Invalid Agent turn status')
    if turn['result'] is not None:
        string(turn['result'])
        require(len(turn['result']) <= 600, 'Turn result exceeds 600 characters')
    require(isinstance(turn['tool_call_results'], list), 'tool_call_results must be an array')
    expected_calls = [call['tool_call_id'] for call in event['tool_calls']]
    actual_calls = []
    for call_result in turn['tool_call_results']:
        keys(call_result, 'tool_call_id result')
        actual_calls.append(call_result['tool_call_id'])
        original = next((call for call in event['tool_calls']
                         if call['tool_call_id'] == call_result['tool_call_id']), None)
        require(original is not None, 'Unknown tool call in turn annotation')
        if call_result['result'] is not None:
            string(call_result['result'])
            require(len(call_result['result']) <= 300,
                    'Tool call result exceeds 300 characters')
            require(bool(original['observation']['raw']),
                    'Call with an empty observation must have result null')
        else:
            require(not original['observation']['raw'],
                    'Call with a non-empty observation needs a brief result')
    require(actual_calls == expected_calls,
            'Tool call results must match the event calls exactly once and in order')
    evidence = Evidence({'query': {'source_raw': ''}, 'events': [event]})
    evidence.refs(turn['source_refs'], event['event_id'])


def turn_annotations(value, trace):
    keys(value, 'turns review_flags')
    flags(value['review_flags'])
    require(isinstance(value['turns'], list), 'turns must be an array')
    evidence = Evidence(trace)
    expected = [e['event_id'] for e in trace['events'] if e['source'] == 'agent']
    actual = []
    for turn in value['turns']:
        keys(turn, 'event_id goal status result source_refs tool_calls')
        string(turn['event_id'])
        string(turn['goal'])
        require(len(turn['goal']) <= 240, 'Turn goal exceeds 240 characters')
        require(turn['status'] in TURN_STATUS, 'Invalid Agent turn status')
        if turn['result'] is not None:
            string(turn['result'])
            require(len(turn['result']) <= 600, 'Turn result exceeds 600 characters')
        evidence.refs(turn['source_refs'], turn['event_id'])
        require(isinstance(turn['tool_calls'], list), 'tool_calls must be an array')
        expected_calls = [call['tool_call_id'] for call in evidence.events[turn['event_id']]['tool_calls']]
        actual_calls = []
        for call in turn['tool_calls']:
            keys(call, 'tool_call_id result')
            actual_calls.append(call['tool_call_id'])
            if call['result'] is not None:
                string(call['result'])
                require(len(call['result']) <= 300, 'Tool call result exceeds 300 characters')
        require(actual_calls == expected_calls, 'Agent turn tool calls changed or reordered')
        actual.append(turn['event_id'])
    require(actual == expected, 'Agent turns must match all agent events exactly once and in order')


def attach_tool_calls(value, trace):
    """Attach immutable call references after validating model annotations."""
    result = []
    for source in value['turns']:
        turn = copy.deepcopy(source)
        call_results = turn.pop('tool_call_results')
        turn['tool_calls'] = [{'tool_call_id': call['tool_call_id'], 'result': call['result']}
                              for call in call_results]
        result.append(turn)
    turn_annotations({'turns': result, 'review_flags': value['review_flags']}, trace)
    return result


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
            'Every trigger_tool_call_id must belong to a prior Agent turn')
    positions = [prior_positions[call_id] for call_id in trigger_ids]
    require(positions == sorted(positions),
            'trigger_tool_call_ids must follow prior trajectory order')


def dependency_evidence(value, trace, canonical_turns):
    keys(value, 'dependencies review_flags')
    flags(value['review_flags'])
    require(isinstance(value['dependencies'], list), 'dependencies must be an array')
    agent_ids = [e['event_id'] for e in trace['events'] if e['source'] == 'agent']
    canonical_ids = [turn['event_id'] for turn in canonical_turns]
    require(canonical_ids == agent_ids, 'Canonical Agent turns do not match the trace')
    require(len(value['dependencies']) == len(agent_ids),
            'Dependency evidence needs exactly one record for every Agent turn')
    prior_call_ids = []
    for index, (expected_target, item) in enumerate(zip(agent_ids, value['dependencies'])):
        if index == 0:
            keys(item, 'target_event_id trigger_tool_call_ids')
            require(item['target_event_id'] == expected_target and
                    item['trigger_tool_call_ids'] == [],
                    'First Agent turn must have no prior information dependency')
        else:
            dependency_choice(item, expected_target, prior_call_ids)
        prior_call_ids.extend(
            call['tool_call_id'] for call in canonical_turns[index]['tool_calls'])


def expand_turn_refs(value, canonical_turns):
    """Replace model-returned event references with immutable program nodes."""
    result = copy.deepcopy(value)
    canonical = {turn['event_id']: turn for turn in canonical_turns}
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


def materialize_group_evidence(value, trace, canonical_turns):
    """Copy exact, already validated evidence after the model selects event IDs."""
    result = copy.deepcopy(value)
    keys(result, 'root review_flags')
    canonical = {turn['event_id']: turn for turn in canonical_turns}

    def walk(node, is_root=False):
        require(isinstance(node, dict), 'Invalid composite task')
        keys(node, 'id goal status reason result source_event_ids subtasks turn_event_ids')
        selected = node.pop('source_event_ids')
        require(isinstance(selected, list) and all(
            isinstance(event_id, str) and event_id in canonical for event_id in selected),
            'source_event_ids must contain known Agent turn IDs')
        require(len(selected) == len(set(selected)),
                'source_event_ids must not contain duplicates')
        descendants = []
        require(isinstance(node['subtasks'], list), 'subtasks must be an array')
        require(isinstance(node['turn_event_ids'], list), 'turn_event_ids must be an array')
        has_subtasks, has_turns = bool(node['subtasks']), bool(node['turn_event_ids'])
        require(has_subtasks != has_turns,
                'Each task must contain either subtasks or Agent turns')
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


def expand_grouping(value, trace, canonical_turns):
    """Turn the model's compact grouping into the fully evidenced saved tree."""
    result = canonicalize_root(value, trace)
    result = materialize_group_evidence(result, trace, canonical_turns)
    result = expand_turn_refs(result, canonical_turns)
    tree(result, trace, canonical_turns)
    return result


def tasks(node):
    yield node
    for child in node['subtasks']:
        yield from tasks(child)


def agent_turns(node):
    for turn in node['turns']:
        yield turn
    for child in node['subtasks']:
        yield from agent_turns(child)


def _validate_atomic(turn, evidence):
    keys(turn, 'event_id goal status result source_refs tool_calls')
    eid = turn['event_id']
    require(isinstance(eid, str) and eid in evidence.events, 'Unknown atomic event')
    event = evidence.events[eid]
    require(event['source'] == 'agent', 'Only agent events can be Agent turns')
    string(turn['goal'])
    require(turn['status'] in TURN_STATUS, 'Invalid Agent turn status')
    if turn['result'] is not None:
        string(turn['result'])
    evidence.refs(turn['source_refs'], eid)
    require(isinstance(turn['tool_calls'], list), 'tool_calls must be an array')
    for call in turn['tool_calls']:
        keys(call, 'tool_call_id result')
        if call['result'] is not None:
            string(call['result'])
    require([c['tool_call_id'] for c in turn['tool_calls']] ==
            [c['tool_call_id'] for c in event['tool_calls']],
            'Agent turn must contain all and only its original tool calls in order')


def tree(value, trace, canonical_turns=None):
    keys(value, 'root review_flags')
    flags(value['review_flags'])
    evidence = Evidence(trace)
    ids, turns_seen = set(), []
    canonical = {t['event_id']: t for t in canonical_turns} if canonical_turns is not None else None
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
                'Each task must contain either subtasks or Agent turns')
        if has_subtasks:
            require(len(node['subtasks']) >= 2,
                    'Composite task needs at least two direct subtasks')
            for child in node['subtasks']:
                require(isinstance(child, dict), 'Invalid child task')
                visit(child)
        else:
            for turn in node['turns']:
                require(isinstance(turn, dict), 'Invalid Agent turn')
                _validate_atomic(turn, evidence)
                if canonical is not None:
                    require(turn == canonical.get(turn['event_id']),
                            'Agent turn was changed while grouping')
                turns_seen.append(turn['event_id'])
    visit(value['root'], True)
    expected = [e['event_id'] for e in trace['events'] if e['source'] == 'agent']
    require(turns_seen == expected, 'Agent turns omitted, duplicated, or reordered')

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
        task['id']: [turn['event_id'] for turn in agent_turns(task)]
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
