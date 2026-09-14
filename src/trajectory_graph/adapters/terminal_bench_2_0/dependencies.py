"""Terminal-Bench 2.0 dependency cards and pipeline entry points."""

from ... import dependencies as common
from .validate import dependency_evidence as validate_dependency_evidence


PROMPT_ROOT = 'adapters/terminal_bench_2_0/prompts'


def _call_input(call):
    arguments = call['arguments']
    if (call['tool_name'] == 'bash_command' and
            isinstance(arguments.get('keystrokes'), str)):
        return arguments['keystrokes']
    return arguments


def _turn_card(turn, events):
    event = events[turn['event_id']]
    source_calls = {
        call['tool_call_id']: call for call in event['tool_calls']
    }
    return {
        'event_id': turn['event_id'],
        'thought': event['thought'],
        'goal': turn['goal'],
        'status': turn['status'],
        'result': turn['result'],
        'tool_calls': [{
            'tool_call_id': call['tool_call_id'],
            'tool_name': source_calls[call['tool_call_id']]['tool_name'],
            'input': _call_input(source_calls[call['tool_call_id']]),
            'result': call['result'],
            'observation': source_calls[call['tool_call_id']]['observation']['raw'],
        } for call in turn['tool_calls']],
    }


def _all_earlier_turns(prior_event, target_event):
    return True


def build_dependency_evidence(trace, nodes, client):
    return common.build_dependency_evidence(
        trace, nodes, client,
        card_builder=_turn_card,
        eligible_prior=_all_earlier_turns,
        system_prompt=f'{PROMPT_ROOT}/select_dependencies_v1',
        user_prompt=f'{PROMPT_ROOT}/select_dependencies_user',
        evidence_validator=validate_dependency_evidence,
    )


def project_local_graphs(execution_tree, dependency_data, trace):
    return common.project_local_graphs(
        execution_tree, dependency_data, trace,
        evidence_validator=validate_dependency_evidence)


def _target_context(event):
    return {'target_thought': event['thought']}


def add_dependency_reasons(execution_tree, skeleton, dependency_data, trace, client):
    return common.add_dependency_reasons(
        execution_tree, skeleton, dependency_data, trace, client,
        target_context=_target_context)
