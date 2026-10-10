#!/usr/bin/env python3
"""Build an offline animation payload from a read-only trace and editable storyboard.

Usage: python3 build_data.py [--source PATH] [--storyboard PATH] [--output PATH]
Only the output JavaScript file is written. No commands inside the trace run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


BASE = Path(__file__).resolve().parent
KINDS = {"inspect", "setup", "extract", "review", "repair", "write", "verify", "finish"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build(source: Path, storyboard: Path):
    raw = source.read_bytes()
    trace = json.loads(raw)
    story = json.loads(storyboard.read_text(encoding="utf-8"))
    raw_steps = trace["steps"]
    agent_steps = [step for step in raw_steps if step.get("source") == "agent"]
    source_ids = [step["step_id"] for step in agent_steps]
    require(len(source_ids) == len(set(source_ids)), "Source agent step IDs must be unique")
    annotated_ids = [step["id"] for step in story["steps"]]
    require(annotated_ids == source_ids, "Storyboard must cover every agent step once in original order")

    group_ids = [group["id"] for group in story["groups"]]
    require(len(group_ids) == len(set(group_ids)), "Group IDs must be unique")
    covered = [sid for group in story["groups"] for sid in group["stepIds"]]
    require(covered == source_ids, "Groups must cover every agent step once in original order")
    by_group = {group["id"]: group for group in story["groups"]}
    group_for = {sid: group["id"] for group in story["groups"] for sid in group["stepIds"]}
    order = {sid: i for i, sid in enumerate(source_ids)}
    for group in story["groups"]:
        require(bool(group["stepIds"]), f"Empty group: {group['id']}")
        require(isinstance(group["summary"], str) and group["summary"], f"Missing summary: {group['id']}")

    calls = [call for step in agent_steps for call in step.get("tool_calls", [])]
    call_ids = [call["tool_call_id"] for call in calls]
    require(len(call_ids) == len(set(call_ids)), "Source tool call IDs must be unique")
    steps = []
    for original, annotation in zip(agent_steps, story["steps"]):
        sid = original["step_id"]
        require(annotation["kind"] in KINDS, f"Unknown kind at step {sid}")
        steps.append({
            **annotation,
            "groupId": group_for[sid],
            "message": original.get("message", ""),
            "toolCalls": [{
                "id": call["tool_call_id"],
                "name": call["function_name"],
                "command": call.get("arguments", {}).get("keystrokes") or
                           json.dumps(call.get("arguments", {}), ensure_ascii=False),
            } for call in original.get("tool_calls", [])],
            "observation": "\n\n".join(result["content"] for result in
                original.get("observation", {}).get("results", [])),
            "promptTokens": original.get("metrics", {}).get("prompt_tokens", 0),
        })

    seen_edges = set()
    for edge in story["dependencies"]:
        source_id, target_id = edge["source"], edge["target"]
        require(source_id in order and target_id in order, f"Unknown dependency endpoint: {edge}")
        require(order[source_id] < order[target_id], f"Dependency must point forward: {edge}")
        require((source_id, target_id) not in seen_edges, f"Duplicate dependency: {edge}")
        require(bool(edge.get("evidence")), f"Missing dependency evidence: {edge}")
        seen_edges.add((source_id, target_id))

    seen_compressions = set()
    compression_order = []
    for event in story["compressions"]:
        gid, after = event["groupId"], event["afterStep"]
        require(gid in by_group and after in order, f"Invalid compression: {event}")
        require(gid not in seen_compressions, f"Duplicate compression for {gid}")
        require(max(order[sid] for sid in by_group[gid]["stepIds"]) <= order[after],
                f"Compression precedes completed group: {gid}")
        compression_order.append(order[after])
        seen_compressions.add(gid)
    require(compression_order == sorted(compression_order), "Compression events must be ordered")

    # Higher-level summaries retain their child groups and full document records.
    # Timing refers to the observation-complete point of an original agent step;
    # the player runs a leaf compression before a merge at that same point.
    higher_groups = []
    higher_ids = set()
    used_children = set()
    by_step = {step["id"]: step for step in steps}
    for group in story.get("higherGroups", []):
        gid = group["id"]
        require(gid not in by_group and gid not in higher_ids, f"Duplicate higher group ID: {gid}")
        members = group["memberGroupIds"]
        require(len(members) >= 2 and len(members) == len(set(members)),
                f"Higher group needs at least two unique children: {gid}")
        require(all(child in by_group for child in members), f"Unknown child in higher group: {gid}")
        require(not used_children.intersection(members), f"Overlapping higher group children: {gid}")
        step_ids = [sid for child in members for sid in by_group[child]["stepIds"]]
        require(len(step_ids) == len(set(step_ids)), f"Overlapping higher group steps: {gid}")
        step_ids.sort(key=order.__getitem__)
        require(bool(group.get("summary")) and bool(group.get("retained")),
                f"Higher group requires a summary and retained information: {gid}")
        records = group.get("records", {})
        require(isinstance(records.get("invoices"), list) and isinstance(records.get("other"), list),
                f"Higher group requires invoices / other record lists: {gid}")
        filenames = set()
        for category in ("invoices", "other"):
            for record in records[category]:
                filename, evidence = record["filename"], record["evidenceStepId"]
                require(filename and filename not in filenames, f"Duplicate document record: {filename}")
                require(evidence in step_ids, f"Evidence outside higher group: {filename}")
                require(filename in by_step[evidence]["observation"],
                        f"Document absent from referenced observation: {filename}")
                if category == "invoices":
                    for field in ("total_amount", "vat_amount"):
                        value = record.get(field)
                        require(isinstance(value, str) and re.fullmatch(r"\d+\.\d{2}", value),
                                f"{filename} {field} must be a decimal string with two places")
                filenames.add(filename)
        higher_groups.append({**group, "stepIds": step_ids, "level": 2})
        higher_ids.add(gid)
        used_children.update(members)

    by_higher_group = {group["id"]: group for group in higher_groups}
    compressed_after = {event["groupId"]: event["afterStep"] for event in story["compressions"]}
    seen_merges = set()
    merge_order = []
    for event in story.get("merges", []):
        gid, after = event["groupId"], event["afterStep"]
        require(gid in by_higher_group and after in order, f"Invalid higher merge: {event}")
        require(gid not in seen_merges, f"Duplicate higher merge: {gid}")
        group = by_higher_group[gid]
        require(max(order[sid] for sid in group["stepIds"]) <= order[after],
                f"Higher merge precedes completed children: {gid}")
        for child in group["memberGroupIds"]:
            require(child in compressed_after and order[compressed_after[child]] <= order[after],
                    f"Higher merge requires an already compressed child: {child}")
        seen_merges.add(gid)
        merge_order.append(order[after])
    require(seen_merges == higher_ids, "Every higher group must have exactly one merge event")
    require(merge_order == sorted(merge_order), "Higher merge events must be ordered")

    return {
        "meta": {
            "title": story["title"],
            "task": story["task"],
            "agent": trace["agent"]["name"],
            "source": "../trajectory.json" if source == BASE.parent / "trajectory.json" else str(source),
            "sourceSha256": hashlib.sha256(raw).hexdigest(),
            "sourceStepCount": len(raw_steps),
            "agentStepCount": len(agent_steps),
            "toolCallCount": len(calls),
            "compressionNote": story["compressionNote"],
            "dependencyNote": story["dependencyNote"],
            "tokenNote": story["tokenNote"],
        },
        "groups": story["groups"],
        "higherGroups": higher_groups,
        "steps": steps,
        "dependencies": story["dependencies"],
        "compressions": story["compressions"],
        "merges": story.get("merges", []),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=BASE.parent / "trajectory.json")
    parser.add_argument("--storyboard", type=Path, default=BASE / "storyboard.json")
    parser.add_argument("--output", type=Path, default=BASE / "data.js")
    args = parser.parse_args()
    source, storyboard, output = args.source.resolve(), args.storyboard.resolve(), args.output.resolve()
    require(output not in {source, storyboard}, "Output must not overwrite the source or storyboard")
    data = build(source, storyboard)
    # Keep the payload valid even if somebody embeds it inside an HTML script tag.
    payload = json.dumps(data, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    output.write_text("// Generated by build_data.py; edit storyboard.json and rebuild.\n"
                      + "window.TRAJECTORY_DEMO = " + payload + ";\n", encoding="utf-8")
    print(f"Built {output.name}: {len(data['steps'])} agent steps, "
          f"{data['meta']['toolCallCount']} tool calls, {len(data['groups'])} groups, "
          f"{len(data['compressions'])} illustrative leaf compressions, "
          f"{len(data['merges'])} higher merges.")
    print(f"Source SHA-256: {data['meta']['sourceSha256']}")


if __name__ == "__main__":
    main()
