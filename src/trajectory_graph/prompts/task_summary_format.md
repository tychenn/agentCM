# Task summary format

Whenever this call requires a task summary, return exactly these fields:

{
  "goal": "one coherent task goal",
  "completion_condition": "specific condition that ends this task interval",
  "status": "completed",
  "reason": "why these members form one task at this level",
  "result": "brief supported outcome or null",
  "source_event_ids": ["representative supplied evidence event IDs"]
}

Use exactly goal, completion_condition, status, reason, result, and
source_event_ids. goal, completion_condition, and reason must be non-empty.
status is active, suspended, completed, failed, abandoned, or uncertain.
result is a supported summary or null. Select one or more source_event_ids only
from the supplied members' evidence_event_ids, in trajectory order. These IDs
let the program copy already validated source references; do not return quotes,
tool call IDs, or source reference objects.

Keep goal within 240 characters, completion_condition within 300 characters,
reason within 600 characters, and result within 600 characters. Summarize only
behavior and outcomes supported by the supplied nodes.
