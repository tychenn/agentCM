"""Terminal-Bench 2.0 entry point for recursive task grouping."""

from ...grouping import atomic_units, build_task_tree as build_recursive_tree


PROMPT_ROOT = 'adapters/terminal_bench_2_0/prompts'


def build_task_tree(trace, nodes, client, **options):
    atomic = atomic_units(nodes, node_kind='agent_turn')
    return build_recursive_tree(
        trace, client, atomic=atomic,
        leaf_prompt=f'{PROMPT_ROOT}/group_leaf_v1',
        leaf_user_prompt=f'{PROMPT_ROOT}/group_leaf_user',
        **options,
    )
