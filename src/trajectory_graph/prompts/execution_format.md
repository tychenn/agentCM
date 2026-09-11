Return exactly this top-level structure:
{
  "root": {
    "id": "t1",
    "goal": "actual user task",
    "status": "active",
    "reason": null,
    "result": null,
    "source_event_ids": [],
    "subtasks": [],
    "turn_event_ids": []
  },
  "review_flags": []
}
Every task has exactly id, goal, status, reason, result, source_event_ids,
subtasks, turn_event_ids. Use unique temporary task IDs. goal is non-empty. Root
reason is null; each child task reason is a non-empty explanation of why its
contents form this scope. status is active, suspended, completed, failed,
abandoned, or uncertain.
result is a supported summary string or null. Root source_event_ids is []. Each
non-root task selects one or more descendant Agent turn event_id values whose
already validated evidence supports its goal or result. Do not return source_refs,
quote text, tool_call_id, or field; the program copies exact source_refs from the
selected immutable turns and supplies the root query reference.

Each task uses exactly one content form:
1. Leaf task: subtasks is [] and turn_event_ids contains one or more adjacent
   input Agent turn event IDs.
2. Composite task: turn_event_ids is [] and subtasks contains at least two
   complete child tasks with these same eight fields.

The program replaces turn_event_ids with the already validated immutable Agent
turns, including all tool calls. Keep child tasks and turn_event_ids in
trajectory order. Every input Agent turn appears exactly once in the whole
tree. Array position defines execution order. Do not return separate task,
execution, invocation, dependency, parent, confidence, or order fields.
