# Terminal-Bench 2.0 adapter

This directory contains the format-specific code for Terminal-Bench 2.0
trajectories produced by Terminus 2:

- `profile.py` identifies the supported `ATIF-v1.7` and `terminus-2` profile.
- `normalize.py` validates the source trajectory and aligns observations.
- `annotation.py` defines the per-turn model contract and validation.
- `grouping.py` constructs Agent-turn cards and selects this adapter's leaf
  grouping prompts.
- `dependencies.py` constructs Agent-turn dependency inputs and selects this
  adapter's dependency prompts.
- `validate.py` owns all Terminal-Bench 2.0 node schemas and field rules.
- `render.py` defines labels and detail panels for Agent-turn nodes.
- `prompts/` contains only the prompts used by this adapter.

The parent package contains only benchmark-independent tree merging,
dependency projection, evidence primitives, layout, and HTML generation.
