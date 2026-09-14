"""Normalize Claude Code trajectories from the Terminal-Bench 4.0 corpus."""
import copy
import hashlib
import json
from pathlib import Path

from ...deepseek_client import save
from ...validate import require, root_query, strict_json, string
from .profile import EXPECTED_AGENT, EXPECTED_SCHEMA, NAME as ADAPTER_NAME


def _argument_text(arguments, *names):
    for name in names:
        value = arguments.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def derive_goal_seed(call):
    """Return a deterministic goal seed, preferring the original description."""
    arguments = call['arguments']
    description = _argument_text(arguments, 'description')
    if description:
        return description, 'arguments.description'

    tool_name = call['function_name']
    target = _argument_text(arguments, 'file_path', 'url', 'task_id', 'recipient',
                            'to', 'query', 'summary', 'name')
    templates = {
        'Read': 'Read {target}',
        'Write': 'Write {target}',
        'Edit': 'Edit {target}',
        'WebFetch': 'Fetch {target}',
        'ToolSearch': 'Search for {target}',
        'TaskOutput': 'Collect output from task {target}',
        'TaskStop': 'Stop task {target}',
        'SendMessage': 'Send message to {target}',
        'ListAgents': 'List active agents',
    }
    if tool_name in templates:
        fallback_target = target or 'the requested target'
        return templates[tool_name].format(target=fallback_target), 'derived_from_tool_call'
    if tool_name == 'Bash':
        command = _argument_text(arguments, 'command')
        first_line = command.splitlines()[0].strip() if command else ''
        suffix = f': {first_line[:160]}' if first_line else ''
        return 'Run shell command' + suffix, 'derived_from_tool_call'
    if tool_name == 'Agent':
        prompt = _argument_text(arguments, 'prompt')
        summary = prompt.splitlines()[0].strip()[:160] if prompt else 'the delegated task'
        return f'Delegate task: {summary}', 'derived_from_tool_call'
    return f'Use {tool_name}' + (f' on {target}' if target else ''), 'derived_from_tool_call'


def _observation_error(result):
    extra = result.get('extra')
    if not isinstance(extra, dict):
        return None
    value = extra.get('tool_result_is_error')
    return value if isinstance(value, bool) else None


def load(path):
    path = Path(path)
    raw = path.read_bytes()
    trace = strict_json(raw.decode('utf-8'))
    require(isinstance(trace, dict) and isinstance(trace.get('schema_version'), str),
            'Missing ATIF schema_version')
    require(trace['schema_version'] == EXPECTED_SCHEMA,
            f'{ADAPTER_NAME} adapter requires {EXPECTED_SCHEMA}')
    agent = trace.get('agent')
    agent_name = agent.get('name') if isinstance(agent, dict) else None
    require(agent_name == EXPECTED_AGENT,
            f"{ADAPTER_NAME} adapter requires agent.name={EXPECTED_AGENT!r}; "
            f"got {agent_name!r}")
    require(isinstance(trace.get('steps'), list) and bool(trace['steps']), 'Missing steps')

    seen_steps, seen_calls = set(), set()
    for step in trace['steps']:
        require(isinstance(step, dict), 'Each step must be an object')
        step_id = step.get('step_id')
        require(type(step_id) in (int, str) and step_id not in seen_steps,
                'Missing or duplicate step_id')
        seen_steps.add(step_id)
        require(step.get('source') in ('user', 'agent'), 'Unsupported step source')
        require(isinstance(step.get('message'), str), 'message must be text')
        calls = step.get('tool_calls', [])
        require(isinstance(calls, list), 'tool_calls must be an array')
        require(not calls or step['source'] == 'agent',
                'Only agent steps may contain tool calls')
        call_ids = []
        for call in calls:
            require(isinstance(call, dict), 'Tool call must be an object')
            call_id = call.get('tool_call_id')
            string(call_id)
            require(call_id not in seen_calls, 'Duplicate tool_call_id')
            seen_calls.add(call_id)
            call_ids.append(call_id)
            string(call.get('function_name'))
            require(isinstance(call.get('arguments'), dict),
                    'Tool arguments must be an object')

        observation = step.get('observation') or {}
        require(isinstance(observation, dict) and
                isinstance(observation.get('results', []), list),
                'Invalid observation')
        observation_ids = []
        for result in observation.get('results', []):
            require(isinstance(result, dict) and isinstance(result.get('content'), str),
                    'Only textual observation content is supported')
            string(result.get('source_call_id'))
            observation_ids.append(result['source_call_id'])
        require(observation_ids == call_ids,
                f'step {step_id}: observations must match tool calls exactly once and in order')

    first = trace['steps'][0]
    require(first['source'] == 'user', 'Trajectory must start with the user task')
    require(not first.get('tool_calls') and not first.get('observation'),
            'First user step cannot contain actions/observations')
    return trace, {
        'filename': path.name,
        'sha256': hashlib.sha256(raw).hexdigest(),
        'adapter': ADAPTER_NAME,
    }


def prepare(trace):
    """Expand each immutable source tool call into one ordered atomic event."""
    events, flags, pending_context = [], [], []
    event_number = 0
    for step in trace['steps'][1:]:
        calls = step.get('tool_calls', [])
        observations = (step.get('observation') or {}).get('results', [])
        if not calls:
            if step['message'].strip():
                pending_context.append({
                    'step_id': step['step_id'],
                    'source': step['source'],
                    'message': step['message'],
                })
            continue

        for tool_index, (original, observation) in enumerate(
                zip(calls, observations), 1):
            event_number += 1
            goal_seed, seed_source = derive_goal_seed(original)
            event = {
                'event_id': f'event-{event_number:04d}',
                'step_id': step['step_id'],
                'source': 'agent',
                'node_kind': 'tool_call',
                'source_tool_index': tool_index,
                'goal_seed': goal_seed,
                'goal_seed_source': seed_source,
                'agent_message': step['message'],
                'context_messages': copy.deepcopy(pending_context),
                'tool_calls': [{
                    'tool_call_id': original['tool_call_id'],
                    'tool_name': original['function_name'],
                    'arguments': copy.deepcopy(original['arguments']),
                    'observation': {
                        'raw': observation['content'],
                        'is_error': _observation_error(observation),
                    },
                }],
            }
            events.append((event, []))
        pending_context = []

    require(bool(events), 'Terminal-Bench 4.0 trajectory contains no tool calls')
    if pending_context:
        events[-1][0]['following_context_messages'] = copy.deepcopy(pending_context)
    return events, flags


def normalize(trace, source, client):
    root = client.ask(
        'root', ['extract_root_v1'], 'extract_root_user',
        {'first_user_message_json': trace['steps'][0]['message']}, root_query,
    )
    prepared, flags = prepare(trace)
    flags.extend(root['review_flags'])
    events = [event for event, _ in prepared]
    output = {
        'source': source,
        'query': {
            'title': root['title'],
            'text': root['query'],
            'source_ref': {'step_id': trace['steps'][0]['step_id'], 'field': 'message'},
            'source_raw': trace['steps'][0]['message'],
        },
        'events': events,
        'review_flags': flags,
    }
    print(f'[atomize] {len(events)} 个 tool call → {len(events)} 个原子节点；'
          'observation 均按 source_call_id 本地直接对齐，未调用 split 模型', flush=True)
    save(client.directory / 'checkpoint.json', {
        'stage': 'normalizing',
        'source': source,
        'last_step_id': events[-1]['step_id'],
    })
    return output
