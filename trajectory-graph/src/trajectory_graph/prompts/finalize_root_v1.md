Summarize the supplied completed task-tree frontier against the root user goal.
Infer only the overall root status and brief result. The task structure and
root goal are fixed by the program.

Return exactly:

{
  "status": "completed",
  "result": "brief overall supported result or null",
  "review_flags": []
}

Use exactly status, result, and review_flags. status is active, suspended,
completed, failed, abandoned, or uncertain. Keep result within 600 characters.
Do not return tasks, members, evidence, dependencies, or a rewritten root goal.
