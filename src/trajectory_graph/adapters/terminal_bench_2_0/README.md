# Terminal-Bench 2.0 adapter

This directory contains the format-specific code for Terminal-Bench 2.0
trajectories produced by Terminus 2:

- `profile.py` identifies the supported `ATIF-v1.7` and `terminus-2` profile.
- `normalize.py` validates the source trajectory and aligns observations.
- `annotation.py` defines the per-turn model contract and validation.
- `prompts/` contains only the prompts used by this adapter.

The task-tree, dependency-projection, validation, and rendering modules remain
in the parent `trajectory_graph` package so a later adapter can reuse them.
