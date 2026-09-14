"""Terminal-Bench 4.0 tool-call annotation contract and validation."""
import copy
import json

from ...validate import TURN_STATUS, flags, keys, require, string
from .validate import attach_nodes


PROMPT_ROOT = 'adapters/terminal_bench_4_0/prompts'
ACTION_TYPES = {
    'inspect', 'search', 'compute', 'write', 'edit', 'execute', 'validate',
    'communicate', 'delegate', 'control', 'other',
}


def _nullable_string(value, name, limit):
    if value is None:
        return
    string(value)
    require(len(value) <= limit, f'{name} exceeds {limit} characters')


def _artifacts(value):
    require(isinstance(value, list), 'artifacts must be an array')
    require(len(value) <= 20, 'artifacts exceeds 20 entries')
    require(all(isinstance(item, str) and bool(item.strip()) and len(item) <= 300
                for item in value),
            'artifacts must contain non-empty strings of at most 300 characters')
    require(len(value) == len(set(value)), 'artifacts must not contain duplicates')


def tool_call_annotation(value, event):
    """Validate one model annotation against its immutable source call."""
    keys(value, 'tool_call_id goal action_type target status result artifacts review_flags')
    require(event['node_kind'] == 'tool_call' and len(event['tool_calls']) == 1,
            'Terminal-Bench 4.0 annotation requires one tool-call event')
    call = event['tool_calls'][0]
    require(value['tool_call_id'] == call['tool_call_id'], 'Tool call ID changed')
    string(value['goal'])
    require(len(value['goal']) <= 240, 'Tool-call goal exceeds 240 characters')
    require(value['action_type'] in ACTION_TYPES, 'Invalid action_type')
    _nullable_string(value['target'], 'Tool-call target', 300)
    require(value['status'] in TURN_STATUS, 'Invalid tool-call status')
    _nullable_string(value['result'], 'Tool-call result', 300)
    if not call['observation']['raw']:
        require(value['result'] is None,
                'Call with an empty observation must have result null')
    if call['observation']['is_error'] is True:
        require(value['status'] != 'completed',
                'Call marked as an error cannot have completed status')
    _artifacts(value['artifacts'])
    flags(value['review_flags'])


def _compact_image_observation(event):
    """Remove base64 image bytes from model input while preserving raw source data."""
    model_event = copy.deepcopy(event)
    # A later final response is preserved for provenance, but it is not evidence
    # for annotating the preceding tool call.
    model_event.pop('following_context_messages', None)
    raw = model_event['tool_calls'][0]['observation']['raw']
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return model_event, None
    if not (isinstance(value, dict) and value.get('type') == 'image' and
            isinstance(value.get('source'), dict) and
            isinstance(value['source'].get('data'), str)):
        return model_event, None
    source = copy.deepcopy(value['source'])
    encoded_length = len(source.pop('data'))
    source['data_omitted'] = True
    source['encoded_length'] = encoded_length
    value['source'] = source
    model_event['tool_calls'][0]['observation']['raw'] = json.dumps(
        value, ensure_ascii=False, allow_nan=False)
    return model_event, (
        f'{event["event_id"]}: base64 image bytes were omitted from the DeepSeek '
        'annotation request; image metadata is retained and the complete source '
        'observation is still saved'
    )


def annotate_event(client, event, output_tokens):
    """Ask DeepSeek to enrich one fixed tool-call node."""
    model_event, local_flag = _compact_image_observation(event)
    response = client.ask(
        f'annotate-{event["event_id"]}',
        [f'{PROMPT_ROOT}/annotate_tool_call_v1'],
        f'{PROMPT_ROOT}/annotate_tool_call_user',
        {'tool_call_event_json': model_event},
        lambda value: tool_call_annotation(value, event),
        output_tokens=output_tokens,
        thinking=True,
    )
    source_refs = [{
        'event_id': event['event_id'],
        'tool_call_id': None,
        'field': 'goal_seed',
        'quote': event['goal_seed'],
    }]
    turn = {
        'event_id': event['event_id'],
        'goal': response['goal'],
        'action_type': response['action_type'],
        'target': response['target'],
        'status': response['status'],
        'result': response['result'],
        'artifacts': response['artifacts'],
        'source_refs': source_refs,
        'tool_calls': [{
            'tool_call_id': response['tool_call_id'],
            'result': response['result'],
        }],
    }
    review_flags = list(response['review_flags'])
    if local_flag:
        review_flags.append(local_flag)
    return {'turn': turn, 'review_flags': review_flags}


def attach_tool_calls(value, trace):
    """Validate and copy the adapter's already materialized atomic nodes."""
    return attach_nodes(value, trace)
