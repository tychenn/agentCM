"""Terminal-Bench 4.0 dependency cards and pipeline entry points."""

from ... import dependencies as common
from .validate import dependency_evidence as validate_dependency_evidence


PROMPT_ROOT = 'adapters/terminal_bench_4_0/prompts'


def _call_input(call):
    return call['arguments']


def _node_card(node, events):
    event = events[node['event_id']]
    source_calls = {
        call['tool_call_id']: call for call in event['tool_calls']
    }
    return {
        'event_id': node['event_id'],
        'goal_seed': event['goal_seed'],
        'goal': node['goal'],
        'action_type': node['action_type'],
        'target': node['target'],
        'status': node['status'],
        'result': node['result'],
        'artifacts': node['artifacts'],
        'tool_calls': [{
            'tool_call_id': call['tool_call_id'],
            'tool_name': source_calls[call['tool_call_id']]['tool_name'],
            'input': _call_input(source_calls[call['tool_call_id']]),
            'result': call['result'],
            'observation': source_calls[call['tool_call_id']]['observation']['raw'],
        } for call in node['tool_calls']],
    }


def _different_source_step(prior_event, target_event):
    return prior_event['step_id'] != target_event['step_id']


def build_dependency_evidence(trace, nodes, client):
    return common.build_dependency_evidence(
        trace, nodes, client,
        card_builder=_node_card,
        eligible_prior=_different_source_step,
        system_prompt=f'{PROMPT_ROOT}/select_dependencies_v1',
        user_prompt=f'{PROMPT_ROOT}/select_dependencies_user',
        evidence_validator=validate_dependency_evidence,
    )


def project_local_graphs(execution_tree, dependency_data, trace):
    return common.project_local_graphs(
        execution_tree, dependency_data, trace,
        evidence_validator=validate_dependency_evidence,
    )


def _target_context(event):
    return {'target_goal_seed': event['goal_seed']}


def add_dependency_reasons(execution_tree, skeleton, dependency_data, trace, client):
    return common.add_dependency_reasons(
        execution_tree, skeleton, dependency_data, trace, client,
        target_context=_target_context,
    )
