# Objective

Decide the first leaf-task boundary in one bounded window of immutable
Terminal-Bench 4.0 tool-call nodes. This call handles only the candidate prefix
beginning at the anchor.

# Boundary criteria

A leaf is the smallest closed operational unit with one immediate objective,
one primary output, and one completion condition. Each supplied node is one
fixed tool call with its own observed result. Do not split or reorder a node.
A leaf may contain one call or several adjacent calls.

Use `goal`, `action_type`, `target`, `result`, and `artifacts` together. The
primary output can be a diagnosis, decision, artifact, state change, or
verified result. A printed line, temporary file, partial batch, or isolated
fact is insufficient when it only records progress toward the same completion
condition.

Find the earliest supported boundary after the anchor:

1. Continue when the next call retries, corrects, validates, cleans up,
   processes another batch, gathers evidence, or completes the same immediate
   operation.
2. End the leaf when the current calls have produced their primary output and
   the next call starts a new operation with a different objective, output, or
   completion condition.
3. Discovery to remediation, planning to execution, and artifact production
   to downstream analysis are candidate boundaries when the concrete goals and
   outputs support them.
4. Calls emitted in one source step remain separate nodes. Their shared step
   alone does not require either merging or splitting; use the semantic fields.

Only merge candidates before the first supported boundary. A `completed`
status describes the observed outcome of one call and does not by itself show
that the surrounding leaf task is closed.

# Allowed actions

- merge: select a continuous candidate prefix of length 2 or more.
- keep: select only the first candidate and create a single-call leaf.
- need_more_context: use only when can_extend is true and all supplied
  candidates may still belong to the anchor task.

When can_extend is false and the boundary remains uncertain, choose the most
supported merge or keep action and add a concise review flag. Context nodes are
read-only and cannot appear in member_ids.

# Output

Return exactly:

{
  "action": "merge",
  "member_ids": ["candidate node IDs in order"],
  "task": null,
  "review_flags": []
}

Use exactly action, member_ids, task, and review_flags. For merge and keep,
task is the supplied task-summary format. For need_more_context, member_ids is
[], task is null, and review_flags states why the boundary is unseen. Return no
recursive tree and no dependency edges.
