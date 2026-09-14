"""Terminal-Bench 2.0 turn-annotation contract and validation."""
import copy

from ...validate import (Evidence, TURN_STATUS, flags, keys, require, string,
                         turn_annotations)


PROMPT_ROOT = 'adapters/terminal_bench_2_0/prompts'


def turn_annotation(value, event):
    """Validate the Terminus 2 per-call result schema."""
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
    require(isinstance(turn['tool_call_results'], list),
            'tool_call_results must be an array')
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


def annotate_event(client, event, output_tokens):
    """Ask for one annotation using the Terminal-Bench 2.0 prompt contract."""
    return client.ask(
        f'annotate-{event["event_id"]}',
        [f'{PROMPT_ROOT}/annotate_turn_v1'],
        f'{PROMPT_ROOT}/annotate_turn_user',
        {'agent_event_json': event},
        lambda value: turn_annotation(value, event),
        output_tokens=output_tokens,
        thinking=True,
    )


def attach_tool_calls(value, trace):
    """Attach immutable call references after validating adapter annotations."""
    result = []
    for source in value['turns']:
        turn = copy.deepcopy(source)
        call_results = turn.pop('tool_call_results')
        turn['tool_calls'] = [
            {'tool_call_id': call['tool_call_id'], 'result': call['result']}
            for call in call_results
        ]
        result.append(turn)
    turn_annotations({'turns': result, 'review_flags': value['review_flags']}, trace)
    return result
