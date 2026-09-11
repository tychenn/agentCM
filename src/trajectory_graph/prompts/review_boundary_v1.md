# Objective

Review only the most recently formed boundary between two provisional tasks.
Use the task summaries, the bounded direct members beside the boundary, and
the read-only outer context. Preserve every member and its execution order.

# Allowed actions

- keep_boundary: retain the boundary.
- shift_left: move the first move_count direct members of the right task to the
  end of the left task, no more than allowed.shift_left_max.
- shift_right: move the last move_count direct members of the left task to the
  beginning of the right task, no more than allowed.shift_right_max.
- merge_adjacent: remove the boundary when allowed.merge_adjacent is true.

Move only complete direct members shown in left_tail or right_head. Never open
or split a member. Outer context is read-only. Prefer keep_boundary when the
evidence does not support a change.

# Output

Return exactly:

{
  "action": "keep_boundary",
  "move_count": 0,
  "left_task": null,
  "right_task": null,
  "merged_task": null,
  "review_flags": []
}

Use exactly these six fields. keep_boundary uses move_count 0 and all three
task fields null. shift_left and shift_right use a positive allowed move_count,
provide updated left_task and right_task summaries, and set merged_task null.
merge_adjacent uses move_count 0, provides merged_task, and sets left_task and
right_task null. Return no member arrays; the program applies the action to the
fixed ordered members.
