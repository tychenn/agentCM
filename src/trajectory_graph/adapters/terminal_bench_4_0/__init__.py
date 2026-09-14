"""Terminal-Bench 4.0 adapter for Claude Code ATIF-v1.7 trajectories."""

from .annotation import annotate_event, attach_tool_calls, tool_call_annotation
from .dependencies import (add_dependency_reasons, build_dependency_evidence,
                           project_local_graphs)
from .grouping import build_task_tree
from .normalize import derive_goal_seed, load, normalize, prepare
from .profile import NAME
from . import render as render_profile
from .validate import expand_grouping, tree as validate_tree

__all__ = [
    'NAME',
    'annotate_event',
    'attach_tool_calls',
    'add_dependency_reasons',
    'build_dependency_evidence',
    'build_task_tree',
    'derive_goal_seed',
    'expand_grouping',
    'load',
    'normalize',
    'prepare',
    'project_local_graphs',
    'render_profile',
    'tool_call_annotation',
    'validate_tree',
]
