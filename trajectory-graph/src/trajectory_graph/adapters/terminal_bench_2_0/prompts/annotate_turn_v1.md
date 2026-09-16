Create one atomic execution-turn annotation for the supplied agent event. The
event boundary is fixed by the input: do not split it, merge it with another
event, or create a composite task.

Infer the complete local goal mainly from the event's full forward-looking plan.
When the plan names follow-up work beyond the calls issued in this event, keep
that follow-up in the goal instead of shrinking the goal to the calls already
executed. The agent message may begin by reviewing a preceding observation; do
not treat that review as the current goal. Summarize only the result produced by
this event. Also give one brief result for every supplied tool call.

Return exactly:
{
  "turn": {
    "event_id": "the supplied agent event ID",
    "goal": "goal pursued by this turn",
    "status": "completed",
    "result": "brief observed result or null",
    "tool_call_results": [{
      "tool_call_id": "supplied call ID",
      "result": "brief observed result or null"
    }],
    "source_refs": []
  },
  "review_flags": []
}
The turn has exactly event_id, goal, status, result, tool_call_results, and
source_refs. Infer status from this event's thought, tool calls, and observations.
status is completed, failed, incomplete, or uncertain and describes the execution
outcome observed in this event only. It does not decide whether the complete
local goal remains open for a later turn. Keep goal within 240
characters, the turn result within 600 characters, and each call result within
300 characters. Return every tool call exactly once and in input order. A call
with an empty observation has result null. source_refs must cite exact
current-event thought evidence for the goal and current-event tool evidence for
a non-null result. References may only point to this event and its tool calls.
Use {"event_id":"input event ID","tool_call_id":null,"field":"thought",
"quote":"exact source text"} for thought evidence. Use an input tool_call_id
and field "arguments" or "observation.raw" for tool evidence. Quotes must match
the referenced thought, observation, or a string value in arguments.
Do not copy tool arguments or observation text into result except for the short
information needed to identify the outcome.
