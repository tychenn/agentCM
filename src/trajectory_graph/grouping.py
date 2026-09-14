"""Build an ordered task tree through bounded local bottom-up grouping."""
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from .deepseek_client import CapacityError, encoded
from .validate import TASK_STATUS, flags, keys, require, string


SUMMARY_FIELDS = (
    'goal completion_condition status reason result source_event_ids'
)


@dataclass
class Unit:
    node_id: str
    node_kind: str
    start_order: int
    end_order: int
    goal: str
    status: str
    result: object
    completion_condition: object
    first_turn_goal: str
    last_turn_goal: str
    turn_event_ids: tuple
    evidence_event_ids: tuple
    direct_child_count: int
    adapter_fields: dict = field(default_factory=dict)
    task: object = None

    def card(self):
        result = {
            'node_id': self.node_id,
            'node_kind': self.node_kind,
            'start_order': self.start_order,
            'end_order': self.end_order,
            'goal': self.goal,
            'status': self.status,
            'completion_condition': self.completion_condition,
            'result': self.result,
            'first_turn_goal': self.first_turn_goal,
            'last_turn_goal': self.last_turn_goal,
            'descendant_turn_count': len(self.turn_event_ids),
            'direct_child_count': self.direct_child_count,
            'evidence_event_ids': list(self.evidence_event_ids),
        }
        result.update(self.adapter_fields)
        return result


@dataclass
class Block:
    members: list
    unit: Unit


class IdFactory:
    def __init__(self):
        self.value = 0

    def next(self):
        self.value += 1
        return f'group-{self.value:05d}'


class StepLog:
    def __init__(self, path, client):
        self.path = Path(path)
        self.client = client
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('', encoding='utf-8')

    def add(self, record):
        safe = self.client.redactor.walk(record)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(safe, ensure_ascii=False, allow_nan=False) + '\n')


def _nullable_string(value, name, limit):
    if value is None:
        return
    string(value)
    require(len(value) <= limit, f'{name} exceeds {limit} characters')


def _ordered_subset(selected, available, name):
    require(isinstance(selected, list) and bool(selected), f'{name} must be a non-empty array')
    require(all(isinstance(item, str) and bool(item.strip()) for item in selected),
            f'{name} must contain non-empty strings')
    require(len(selected) == len(set(selected)), f'{name} must not contain duplicates')
    selected_set = set(selected)
    require(selected == [item for item in available if item in selected_set],
            f'{name} must be an ordered subset of supplied evidence events')


def _summary(value, descendant_ids, available_evidence_ids):
    keys(value, SUMMARY_FIELDS)
    string(value['goal'])
    require(len(value['goal']) <= 240, 'Task goal exceeds 240 characters')
    string(value['completion_condition'])
    require(len(value['completion_condition']) <= 300,
            'Task completion_condition exceeds 300 characters')
    require(value['status'] in TASK_STATUS, 'Invalid task status')
    string(value['reason'])
    require(len(value['reason']) <= 600, 'Task reason exceeds 600 characters')
    _nullable_string(value['result'], 'Task result', 600)
    _ordered_subset(value['source_event_ids'], available_evidence_ids, 'source_event_ids')
    require(set(value['source_event_ids']).issubset(descendant_ids),
            'Task evidence must belong to its descendant atomic nodes')


def _review_flags(value):
    flags(value)


def _prefix_decision(value, candidates, *, leaf, can_extend):
    keys(value, 'action member_ids task review_flags')
    _review_flags(value['review_flags'])
    require(value['action'] in ('merge', 'keep', 'need_more_context'),
            'Invalid local grouping action')
    require(isinstance(value['member_ids'], list), 'member_ids must be an array')
    candidate_ids = [unit.node_id for unit in candidates]
    if value['action'] == 'need_more_context':
        require(can_extend, 'need_more_context is unavailable for this window')
        require(value['member_ids'] == [] and value['task'] is None,
                'need_more_context must return empty member_ids and null task')
        return
    if value['action'] == 'keep':
        require(value['member_ids'] == candidate_ids[:1],
                'keep must select only the anchor node')
        if leaf:
            require(isinstance(value['task'], dict),
                    'A single-node leaf needs a task summary')
        else:
            require(value['task'] is None,
                    'Keeping an existing task must return task null')
            return
    else:
        require(2 <= len(value['member_ids']) <= len(candidates),
                'merge must select between 2 and the supplied candidate count')
        require(value['member_ids'] == candidate_ids[:len(value['member_ids'])],
                'merge member_ids must be a continuous prefix beginning at the anchor')
        require(isinstance(value['task'], dict), 'merge needs a task summary')
    count = len(value['member_ids'])
    members = candidates[:count]
    descendants = [event_id for unit in members for event_id in unit.turn_event_ids]
    available = [event_id for unit in members for event_id in unit.evidence_event_ids]
    _summary(value['task'], descendants, available)


def _boundary_decision(value, left, right, *, leaf, lookback, merge_limit):
    keys(value, 'action move_count left_task right_task merged_task review_flags')
    _review_flags(value['review_flags'])
    action = value['action']
    require(action in ('keep_boundary', 'shift_left', 'shift_right', 'merge_adjacent'),
            'Invalid boundary review action')
    move = value['move_count']
    require(isinstance(move, int) and not isinstance(move, bool) and move >= 0,
            'move_count must be a non-negative integer')
    if action == 'keep_boundary':
        require(move == 0, 'keep_boundary requires move_count 0')
        require(value['left_task'] is None and value['right_task'] is None and
                value['merged_task'] is None,
                'keep_boundary must return null task summaries')
        return
    if action == 'merge_adjacent':
        require(move == 0, 'merge_adjacent requires move_count 0')
        require(len(left.members) + len(right.members) <= merge_limit,
                'merge_adjacent exceeds the configured maximum merge size')
        require(value['left_task'] is None and value['right_task'] is None and
                isinstance(value['merged_task'], dict),
                'merge_adjacent needs only merged_task')
        members = left.members + right.members
        descendants = [event_id for unit in members for event_id in unit.turn_event_ids]
        available = [event_id for unit in members for event_id in unit.evidence_event_ids]
        _summary(value['merged_task'], descendants, available)
        return
    require(1 <= move <= lookback, 'Boundary shift exceeds the configured lookback')
    require(value['merged_task'] is None and isinstance(value['left_task'], dict) and
            isinstance(value['right_task'], dict),
            'Boundary shift needs left_task and right_task summaries')
    if action == 'shift_left':
        require(move < len(right.members), 'shift_left must leave a non-empty right task')
        left_members = left.members + right.members[:move]
        right_members = right.members[move:]
    else:
        require(move < len(left.members), 'shift_right must leave a non-empty left task')
        left_members = left.members[:-move]
        right_members = left.members[-move:] + right.members
    for summary, members in ((value['left_task'], left_members),
                             (value['right_task'], right_members)):
        descendants = [event_id for unit in members for event_id in unit.turn_event_ids]
        available = [event_id for unit in members for event_id in unit.evidence_event_ids]
        _summary(summary, descendants, available)


def _root_summary(value):
    keys(value, 'status result review_flags')
    require(value['status'] in TASK_STATUS, 'Invalid root task status')
    _nullable_string(value['result'], 'Root result', 600)
    _review_flags(value['review_flags'])


def atomic_units(nodes, *, node_kind, adapter_fields=None):
    """Create immutable frontier units from adapter-owned node annotations."""
    adapter_fields = adapter_fields or (lambda node: {})
    result = []
    for order, node in enumerate(nodes, 1):
        result.append(Unit(
            node_id=node['event_id'],
            node_kind=node_kind,
            start_order=order, end_order=order, goal=node['goal'],
            status=node['status'], result=node['result'], completion_condition=None,
            first_turn_goal=node['goal'], last_turn_goal=node['goal'],
            turn_event_ids=(node['event_id'],), evidence_event_ids=(node['event_id'],),
            direct_child_count=0,
            adapter_fields=dict(adapter_fields(node)), task=None,
        ))
    return result


def _unique_ordered(items):
    return tuple(dict.fromkeys(items))


def _task_unit(summary, members, *, leaf, ids):
    require(bool(members), 'Cannot create an empty task')
    if leaf:
        require(all(member.task is None for member in members),
                'Leaf tasks can contain only atomic nodes')
        subtasks = []
        turn_ids = [member.node_id for member in members]
        kind = 'leaf_task'
        direct_children = 0
    else:
        require(all(member.task is not None for member in members),
                'Composite tasks can contain only task nodes')
        subtasks = [copy.deepcopy(member.task) for member in members]
        turn_ids = []
        kind = 'composite_task'
        direct_children = len(members)
    task = {
        'id': ids.next(),
        'goal': summary['goal'],
        'status': summary['status'],
        'reason': summary['reason'],
        'result': summary['result'],
        'source_event_ids': list(summary['source_event_ids']),
        'subtasks': subtasks,
        'turn_event_ids': turn_ids,
    }
    descendants = tuple(event_id for member in members for event_id in member.turn_event_ids)
    return Unit(
        node_id=task['id'], node_kind=kind,
        start_order=members[0].start_order, end_order=members[-1].end_order,
        goal=task['goal'], status=task['status'], result=task['result'],
        completion_condition=summary['completion_condition'],
        first_turn_goal=members[0].first_turn_goal,
        last_turn_goal=members[-1].last_turn_goal,
        turn_event_ids=descendants,
        evidence_event_ids=_unique_ordered(task['source_event_ids']),
        direct_child_count=direct_children, task=task,
    )


def _payload_size(value):
    return len(encoded(value).encode('utf-8'))


def _local_input(root_goal, phase, round_number, left_context, snapshot,
                 start, count, can_extend):
    end = start + count
    return {
        'root_goal': root_goal,
        'phase': phase,
        'round': round_number,
        'left_context': left_context.card() if left_context else None,
        'candidates': [unit.card() for unit in snapshot[start:end]],
        'right_context': snapshot[end].card() if end < len(snapshot) else None,
        'can_extend': can_extend,
    }


def _fit_window(root_goal, phase, round_number, left_context, snapshot,
                start, desired, maximum, budget):
    remaining = len(snapshot) - start

    def largest(up_to):
        for count in range(min(up_to, remaining, maximum), 0, -1):
            data = _local_input(root_goal, phase, round_number, left_context,
                                snapshot, start, count, False)
            if _payload_size(data) <= budget:
                return count
        raise CapacityError(
            f'{phase} anchor {snapshot[start].node_id}: one compact node exceeds '
            f'--merge-input-tokens={budget}')

    count = largest(desired)
    extended_target = min(max(count + 1, count * 2), remaining, maximum)
    extended = largest(extended_target) if extended_target > count else count
    can_extend = extended > count
    data = _local_input(root_goal, phase, round_number, left_context,
                        snapshot, start, count, can_extend)
    if _payload_size(data) > budget:
        count = largest(count - 1)
        extended = count
        can_extend = False
        data = _local_input(root_goal, phase, round_number, left_context,
                            snapshot, start, count, can_extend)
    return data, count, extended


def _request_block(client, log, root_goal, phase, round_number, snapshot,
                   start, blocks, initial, maximum, budget, leaf, ids,
                   leaf_prompt, leaf_user_prompt):
    desired = min(initial, len(snapshot) - start)
    while True:
        left_context = blocks[-1].unit if blocks else None
        data, count, extended = _fit_window(
            root_goal, phase, round_number, left_context, snapshot,
            start, desired, maximum, budget)
        candidates = snapshot[start:start + count]
        print(f'[{phase}] 第 {round_number} 轮：锚点 {candidates[0].node_id}，'
              f'候选 {count} 个', flush=True)
        parts = ['task_summary_format', leaf_prompt if leaf else 'merge_tasks_v1']
        user_prompt = leaf_user_prompt if leaf else 'merge_tasks_user'
        name = f'{phase}-r{round_number:02d}-i{start:05d}-k{count:03d}'
        response = client.ask(
            name, parts, user_prompt, {'grouping_input_json': data},
            lambda value, current=candidates, extend=data['can_extend']:
                _prefix_decision(value, current, leaf=leaf, can_extend=extend),
            output_tokens=client.max_tokens, thinking=True,
        )
        log.add({
            'type': 'local_decision', 'phase': phase, 'round': round_number,
            'anchor_id': candidates[0].node_id, 'window_size': count,
            'input_nodes': [unit.card() for unit in candidates],
            'response': response,
        })
        if response['action'] == 'need_more_context':
            require(extended > count, 'Model requested unavailable context')
            desired = extended
            continue
        consumed = len(response['member_ids'])
        members = snapshot[start:start + consumed]
        if leaf or response['action'] == 'merge':
            unit = _task_unit(response['task'], members, leaf=leaf, ids=ids)
        else:
            unit = members[0]
        return Block(members=members, unit=unit), response['review_flags']


def _rebuild_block(members, summary, *, leaf, ids):
    if not leaf and len(members) == 1:
        return Block(members=members, unit=members[0])
    return Block(members=members,
                 unit=_task_unit(summary, members, leaf=leaf, ids=ids))


def _review_boundary(client, log, root_goal, phase, round_number,
                     left, right, outer_left, outer_right,
                     lookback, merge_limit, budget, leaf, ids, boundary_number):
    if lookback == 0:
        return [left, right], []
    data = None
    actual_lookback = lookback
    while actual_lookback >= 0:
        left_tail = left.members[-actual_lookback:] if actual_lookback else []
        right_head = right.members[:actual_lookback] if actual_lookback else []
        candidate = {
            'root_goal': root_goal,
            'phase': phase,
            'round': round_number,
            'lookback': actual_lookback,
            'left_task': left.unit.card(),
            'right_task': right.unit.card(),
            'left_tail': [member.card() for member in left_tail],
            'right_head': [member.card() for member in right_head],
            'outer_left_context': outer_left.card() if outer_left else None,
            'outer_right_context': outer_right.card() if outer_right else None,
            'allowed': {
                'shift_left_max': min(actual_lookback, max(0, len(right.members) - 1)),
                'shift_right_max': min(actual_lookback, max(0, len(left.members) - 1)),
                'merge_adjacent': len(left.members) + len(right.members) <= merge_limit,
            },
        }
        if _payload_size(candidate) <= budget:
            data = candidate
            break
        actual_lookback -= 1
    if data is None:
        raise CapacityError(
            f'{phase} boundary {boundary_number}: compact boundary summaries exceed '
            f'--merge-input-tokens={budget}')
    response = client.ask(
        f'review-{phase}-r{round_number:02d}-b{boundary_number:05d}',
        ['task_summary_format', 'review_boundary_v1'], 'review_boundary_user',
        {'boundary_input_json': data},
        lambda value: _boundary_decision(
            value, left, right, leaf=leaf, lookback=actual_lookback,
            merge_limit=merge_limit),
        output_tokens=client.max_tokens, thinking=True,
    )
    action, move = response['action'], response['move_count']
    if action == 'keep_boundary':
        reviewed = [left, right]
    elif action == 'merge_adjacent':
        reviewed = [_rebuild_block(
            left.members + right.members, response['merged_task'], leaf=leaf, ids=ids)]
    elif action == 'shift_left':
        reviewed = [
            _rebuild_block(left.members + right.members[:move],
                           response['left_task'], leaf=leaf, ids=ids),
            _rebuild_block(right.members[move:], response['right_task'],
                           leaf=leaf, ids=ids),
        ]
    else:
        reviewed = [
            _rebuild_block(left.members[:-move], response['left_task'],
                           leaf=leaf, ids=ids),
            _rebuild_block(left.members[-move:] + right.members,
                           response['right_task'], leaf=leaf, ids=ids),
        ]
    log.add({
        'type': 'boundary_review', 'phase': phase, 'round': round_number,
        'boundary': boundary_number,
        'before': [[member.node_id for member in left.members],
                   [member.node_id for member in right.members]],
        'response': response,
        'after': [[member.node_id for member in block.members] for block in reviewed],
    })
    print(f'[review-{phase}] 第 {round_number} 轮边界 {boundary_number}：{action}',
          flush=True)
    return reviewed, response['review_flags']


def _group_pass(client, log, root_goal, snapshot, *, phase, round_number,
                initial, maximum, budget, lookback, leaf, ids,
                leaf_prompt, leaf_user_prompt):
    log.add({'type': 'round_start', 'phase': phase, 'round': round_number,
             'frontier': [unit.node_id for unit in snapshot]})
    blocks, collected_flags = [], []
    start, boundary_number = 0, 0
    while start < len(snapshot):
        block, decision_flags = _request_block(
            client, log, root_goal, phase, round_number, snapshot,
            start, blocks, initial, maximum, budget, leaf, ids,
            leaf_prompt, leaf_user_prompt)
        collected_flags.extend(decision_flags)
        start += len(block.members)
        if not blocks:
            blocks.append(block)
            continue
        boundary_number += 1
        outer_left = blocks[-2].unit if len(blocks) >= 2 else None
        outer_right = snapshot[start] if start < len(snapshot) else None
        reviewed, review_flags = _review_boundary(
            client, log, root_goal, phase, round_number,
            blocks[-1], block, outer_left, outer_right,
            lookback, maximum, budget, leaf, ids, boundary_number)
        collected_flags.extend(review_flags)
        blocks[-1:] = reviewed
    output = [block.unit for block in blocks]
    log.add({'type': 'round_end', 'phase': phase, 'round': round_number,
             'frontier_before': [unit.node_id for unit in snapshot],
             'frontier_after': [unit.node_id for unit in output],
             'reduction': len(snapshot) - len(output)})
    return output, collected_flags


def build_task_tree(trace, client, *, window=16,
                    window_max=64, input_tokens=65536, lookback=1,
                    atomic, leaf_prompt, leaf_user_prompt):
    """Return the compact recursive grouping consumed by expand_grouping."""
    require(2 <= window <= window_max, 'Require 2 <= merge window <= merge window max')
    require(input_tokens > 0, 'merge input token budget must be positive')
    require(0 <= lookback < window, 'Require 0 <= merge lookback < merge window')
    require(bool(atomic), 'Cannot build a task tree without atomic nodes')
    ids = IdFactory()
    log = StepLog(client.directory / 'grouping_steps.jsonl', client)
    root_goal = {'title': trace['query']['title'], 'text': trace['query']['text']}

    frontier, review_flags = _group_pass(
        client, log, root_goal, atomic, phase='group-leaf', round_number=1,
        initial=window, maximum=window_max, budget=input_tokens,
        lookback=lookback, leaf=True, ids=ids,
        leaf_prompt=leaf_prompt, leaf_user_prompt=leaf_user_prompt)

    round_number = 1
    while len(frontier) > 1:
        next_frontier, round_flags = _group_pass(
            client, log, root_goal, frontier, phase='merge-tasks',
            round_number=round_number, initial=window, maximum=window_max,
            budget=input_tokens, lookback=lookback, leaf=False, ids=ids,
            leaf_prompt=leaf_prompt, leaf_user_prompt=leaf_user_prompt)
        review_flags.extend(round_flags)
        if len(next_frontier) == len(frontier):
            frontier = next_frontier
            break
        require(len(next_frontier) < len(frontier),
                'A successful composite round must reduce the frontier')
        frontier = next_frontier
        round_number += 1

    root_input = {
        'root_goal': root_goal,
        'top_level_tasks': [unit.card() for unit in frontier],
        'task_count': len(frontier),
    }
    if _payload_size(root_input) > input_tokens:
        raise CapacityError(
            f'final root summary exceeds --merge-input-tokens={input_tokens}; '
            'increase the configured grouping input budget')
    root_result = client.ask(
        'finalize-task-root', ['finalize_root_v1'], 'finalize_root_user',
        {'root_input_json': root_input}, _root_summary,
        output_tokens=client.max_tokens, thinking=True,
    )
    review_flags.extend(root_result['review_flags'])
    if len(frontier) == 1:
        only = frontier[0].task
        subtasks = copy.deepcopy(only['subtasks'])
        turn_event_ids = list(only['turn_event_ids'])
    else:
        subtasks = [copy.deepcopy(unit.task) for unit in frontier]
        turn_event_ids = []
    root = {
        'id': 'group-root', 'goal': trace['query']['text'],
        'status': root_result['status'], 'reason': None,
        'result': root_result['result'], 'source_event_ids': [],
        'subtasks': subtasks, 'turn_event_ids': turn_event_ids,
    }
    result = {'root': root, 'review_flags': list(dict.fromkeys(review_flags))}
    log.add({'type': 'complete', 'frontier': [unit.node_id for unit in frontier],
             'root_summary': root_result})
    return result
