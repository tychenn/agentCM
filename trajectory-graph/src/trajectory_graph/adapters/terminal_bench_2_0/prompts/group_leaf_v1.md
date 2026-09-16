# Objective

Decide the first leaf-task boundary in one bounded window of immutable Agent
turns. This call handles only the candidate prefix beginning at the anchor.

# Boundary criteria

A leaf is the smallest closed operational unit with one immediate objective,
one primary output, and one completion condition. Agent turns are already the
atomic execution nodes. Do not create a separate leaf merely because an
individual command, observation, or intermediate result can be checked on its
own. A leaf may contain one turn or multiple turns.

The primary output is the result of the completed operation: for example, a
diagnosis, decision, artifact, state change, or verified result. It must be
possible to describe that output and determine from trajectory evidence
whether the completion condition was reached. A log line, temporary file,
partial batch, or isolated fact is not sufficient when it only represents
progress toward the current completion condition.

A broader phase that contains several closed operational units belongs in a
later composite task. Sharing that broader phase is not sufficient reason to
merge turns into one leaf. An information dependency between adjacent turns
also does not by itself require a split: first decide whether both turns still
serve the same immediate objective and completion condition.

Find the earliest supported boundary after the anchor. Scan each adjacent pair
in order and apply these rules:

1. Continue the leaf when the next turn repeats, corrects, retries, verifies,
   cleans up, processes another batch, gathers more evidence, or finishes the
   same operation under the same completion condition.
2. End the leaf only when the current prefix has closed its immediate
   operation, produced its primary output, and the next turn begins a new
   operation with a different immediate objective, primary output, or
   completion condition. The next operation may consume or respond to the
   completed output.
3. Treat transitions such as discovery or diagnosis to remediation or
   installation, planning or selection to execution, and artifact production
   to downstream analysis as candidate task boundaries. Apply the semantic
   criterion; these examples are not fixed labels.
4. Do not split a failed command from its direct correction, one batch from the
   remaining batches, evidence-gathering steps that jointly support one
   diagnosis or decision, or an operation from its direct verification when
   they still pursue the same immediate objective and completion condition.

Only merge candidates that occur before the first supported boundary. The
prefix may therefore be a complete leaf even when the broader preparation,
analysis, or delivery phase continues in later turns.

A completed Agent turn describes that event's observed execution outcome. It
does not by itself prove that the local operation has closed. A tool change, a
new command, a temporary artifact, or an individually checkable observation
also does not by itself establish a boundary. Use the candidate goals,
results, completion conditions, and the read-only left and right context to
identify the boundary.

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
