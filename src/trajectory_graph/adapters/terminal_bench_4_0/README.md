# Terminal-Bench 4.0 adapter

This directory contains the format-specific code for Terminal-Bench 4.0
trajectories produced by Claude Code:

- `profile.py` identifies the supported `ATIF-v1.7` and `claude-code` profile.
- `normalize.py` expands every tool call into one atomic execution node and
  binds its observation locally through `source_call_id`.
- `annotation.py` asks DeepSeek to enrich each fixed tool-call node with its
  goal, action type, target, status, result, and artifacts.
- `grouping.py` constructs tool-call cards and selects this adapter's leaf
  grouping prompts.
- `dependencies.py` enforces source-step concurrency and constructs dependency
  inputs for tool-call nodes.
- `validate.py` owns all Terminal-Bench 4.0 node schemas and field rules.
- `render.py` defines labels and detail panels for tool-call nodes.
- `prompts/` contains only the prompts used by this adapter.

The adapter uses the original tool `description` as the goal seed when it is
available. It derives a deterministic seed from the tool name and key arguments
for tools without a description. Calls emitted in the same source step remain
separate nodes but are treated as concurrent for information-dependency
selection.
