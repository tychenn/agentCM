# Objective

Decide the first leaf-task boundary in one bounded window of immutable Agent
turns. This call handles only the candidate prefix beginning at the anchor.

# Boundary criteria

Group adjacent turns when they pursue the same local goal or jointly produce
one concrete intermediate outcome. Keep retries, command corrections, output
batching, and continued inspection of the same kind of object together when
they still serve that goal. End the leaf when the local completion condition or
concrete phase changes.

A completed Agent turn describes that event's observed execution outcome. It
does not by itself prove that the multi-turn local task has ended. Use the
candidate goals, results, and the read-only left and right context to identify
the boundary.

# Allowed actions

- merge: select a continuous candidate prefix of length 2 or more.
- keep: select only the first candidate and create a single-turn leaf.
- need_more_context: use only when can_extend is true and every supplied
  candidate may still belong to the anchor task, leaving its right boundary
  unseen.

When can_extend is false and the boundary remains uncertain, choose the most
supported merge or keep action and add a concise review flag.

Context nodes are read-only and cannot appear in member_ids. Never skip a
candidate or select a range beginning after the anchor.

# Output

Return exactly:

{
  "action": "merge",
  "member_ids": ["candidate node IDs in order"],
  "task": null,
  "review_flags": []
}

Use exactly action, member_ids, task, and review_flags. For merge and keep,
task is the task summary defined above. For need_more_context, member_ids is [],
task is null, and review_flags briefly records why the current boundary is
unseen. Return no recursive tree and no dependency edges.
