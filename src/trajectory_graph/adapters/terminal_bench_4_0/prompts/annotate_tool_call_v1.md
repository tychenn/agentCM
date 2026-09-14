# Objective

Annotate one fixed Terminal-Bench 4.0 tool-call node. The node contains exactly
one tool call and its source-linked observation. Do not split, merge, reorder,
or invent calls.

The normalized `goal_seed` is immutable. It comes from the original
tool `description` when available, otherwise from a deterministic local
fallback. Refine it only enough to state the immediate operation precisely.
Use `agent_message` only as optional context; it is not a separate reasoning
node.

# Semantic fields

- `goal`: the immediate purpose of this call, grounded in the goal seed.
- `action_type`: exactly one of `inspect`, `search`, `compute`, `write`,
  `edit`, `execute`, `validate`, `communicate`, `delegate`, `control`, or
  `other`.
- `target`: the main file, directory, dataset, process, service, task, or object
  acted on; use null only when no concise target is supported.
- `status`: `completed`, `failed`, `incomplete`, or `uncertain`, describing only
  the observed outcome of this call.
- `result`: a concise observation-derived outcome. State the important finding,
  produced state, validation result, or failure. Use null only when the supplied
  observation contains no usable outcome.
- `artifacts`: paths or named outputs created or materially modified by this
  call. Do not list inputs that were only read. Use an empty array when none are
  supported.

The `observation.raw` field is immutable evidence. If `observation.is_error` is
true, do not label the call completed. A command can contain diagnostics or an
expected failed probe; infer status from the actual observed execution outcome,
without deciding whether the broader task has finished.

# Output

Return exactly:

{
  "tool_call_id": "the supplied tool call ID",
  "goal": "immediate tool-call goal",
  "action_type": "inspect",
  "target": "main target or null",
  "status": "completed",
  "result": "brief observed result or null",
  "artifacts": [],
  "review_flags": []
}

Use exactly these eight fields. Keep goal within 240 characters, target within
300 characters, result within 300 characters, and each artifact within 300
characters. Return no source references, task grouping, or dependency edges.
