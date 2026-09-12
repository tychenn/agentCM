# Objective

Decide the first leaf-task boundary in one bounded window of immutable Agent
turns. This call handles only the candidate prefix beginning at the anchor.

# Boundary criteria

A leaf is the smallest coherent operational task with one local objective and
one completion condition. A broader phase that contains several operational
steps belongs in a later composite task. Sharing that broader phase is not
sufficient reason to merge turns into one leaf.

Find the earliest supported boundary after the anchor. Scan each adjacent pair
in order and apply these rules:

1. Continue the leaf when the next turn repeats, corrects, retries, batches, or
   finishes the same operation under the same completion condition.
2. End the leaf when the current prefix has produced an independently usable
   fact, decision, diagnosis, artifact, or verified state and the next turn
   changes its primary action or completion condition to consume or respond to
   that result.
3. Treat transitions such as discovery or diagnosis to remediation or
   installation, planning or selection to execution, and artifact production
   to downstream analysis as candidate task boundaries. Apply the semantic
   criterion; these examples are not fixed labels.
4. Do not split a failed command from its direct correction, or one batch from
   the remaining batches, when both still pursue the same operation and
   completion condition.

Only merge candidates that occur before the first supported boundary. The
prefix may therefore be a complete leaf even when the broader preparation,
analysis, or delivery phase continues in later turns.

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
