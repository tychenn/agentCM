Identify which earlier tool-call results directly informed the supplied target
Agent turn. This call only selects information-dependency evidence. It does not
choose task boundaries, task parents, execution order, or graph endpoints.

Prior turn cards contain the original thought, annotated goal and result, and
every tool call's input, brief result, and complete observation. The target card
contains the same fields for context. Evaluate every earlier tool-call result
against the target turn's overall goal and concrete actions.

Include an earlier tool call when the target turn directly consumes its output,
responds to its error or missing condition, verifies or repairs its result, or
uses it to choose a concrete action. A materially different or absent result
should plausibly change the target goal or at least one target action. Keep all
independent direct sources when different results support different decisions.

Exclude calls connected only by chronology, topic similarity, shared user
query, general background, or an indirect condition superseded by a later,
more direct result. An empty list is valid when no earlier tool result directly
informs the target turn. Return selected IDs once each in prior trajectory order.

Return exactly:
{
  "target_event_id": "the supplied target event ID",
  "trigger_tool_call_ids": ["zero or more prior tool_call_id values"]
}
Do not return task IDs, relation types, explanations, confidence, quotes, graph
objects, or any additional field.
