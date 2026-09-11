# Objective

Decide whether the anchor and following task nodes form one meaningful
composite task. The supplied nodes are immutable tasks created at the preceding
level. This call may only group a continuous prefix beginning at the anchor.

# Grouping criteria

Merge two or more adjacent tasks when their combined outcome forms one
coherent intermediate phase of the root goal. The new goal must add a useful
scope supported by all selected children. Keep tasks separate when they merely
occur next to each other, share a topic, or already express the same scope as a
single selected child.

Use first_turn_goal, last_turn_goal, completion_condition, result, and the
read-only boundary context. Do not open, split, or reorder a supplied task.

# Allowed actions

- merge: select a continuous candidate prefix of length 2 or more and provide
  a new task summary.
- keep: select only the anchor and return task null; the program carries the
  existing task forward unchanged.
- need_more_context: use only when can_extend is true and the selected scope may
  continue beyond the supplied candidates.

When can_extend is false and the boundary remains uncertain, choose the most
supported merge or keep action and add a concise review flag.

Context nodes are read-only and cannot appear in member_ids. Never select a
range beginning after the anchor.

# Output

Return exactly:

{
  "action": "merge",
  "member_ids": ["candidate node IDs in order"],
  "task": null,
  "review_flags": []
}

Use exactly action, member_ids, task, and review_flags. merge requires the task
summary defined above. keep requires one anchor ID and task null.
need_more_context requires empty member_ids and task null. Return no recursive
tree and no dependency edges.
