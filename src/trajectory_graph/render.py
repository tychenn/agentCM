"""Render an ordered recursive task tree and task-level information edges."""
import html
import json
from pathlib import Path

from .validate import (atomic_nodes, local_graphs as validate_local_graphs,
                       require, strict_json, tasks)


def escape(value):
    return html.escape(str(value), quote=True)


def render_tree(tree_path, trace_path, output, local_graph_path=None):
    tree_path, trace_path, output = map(Path, (tree_path, trace_path, output))
    require(output.resolve() not in {tree_path.resolve(), trace_path.resolve()},
            'HTML output must not overwrite tree or trace')
    value = strict_json(tree_path.read_text(encoding='utf-8'))
    trace = strict_json(trace_path.read_text(encoding='utf-8'))
    from .adapters import get_adapter
    adapter_name = trace.get('source', {}).get('adapter')
    require(isinstance(adapter_name, str),
            'normalized_trace.json is missing source.adapter')
    adapter = get_adapter(adapter_name)
    adapter.validate_tree(value, trace)
    profile = adapter.render_profile
    local_graph_path = (Path(local_graph_path) if local_graph_path is not None else
                        tree_path.parent / 'local_graphs.json')
    graph_missing = not local_graph_path.exists()
    if graph_missing:
        graph = {'local_graphs': [
            {'task_id': task['id'], 'edges': []}
            for task in tasks(value['root'])
        ]}
    else:
        graph = strict_json(local_graph_path.read_text(encoding='utf-8'))
    validate_local_graphs(graph, value, trace)

    events = {event['event_id']: event for event in trace['events']}
    calls = {
        call['tool_call_id']: (event, call)
        for event in trace['events']
        for call in event['tool_calls']
    }
    statuses = dict(active='进行中', suspended='挂起', completed='完成', failed='失败',
                    abandoned='放弃', incomplete='未完成', uncertain='待确认')
    turn_nodes, task_groups, task_edges, detail_sections = [], [], [], []

    def detail(label, text):
        return (f'<details class="evidence"><summary>{escape(label)}</summary>'
                f'<pre>{escape(text)}</pre></details>')

    def evidence_text(refs):
        return '\n\n'.join(
            f'{ref["event_id"]} / {ref["tool_call_id"] or ref["field"]}\n{ref["quote"]}'
            for ref in refs)

    def add_turn(turn, path, owner_id, order):
        event = events[turn['event_id']]
        call_rows = [
            {'id': ref['tool_call_id'], 'name': calls[ref['tool_call_id']][1]['tool_name']}
            for ref in turn['tool_calls']
        ]
        turn_nodes.append(dict(
            id=turn['event_id'], goal=turn['goal'], status=statuses[turn['status']],
            state=turn['status'], label=profile.node_label(event),
            owner_group_id=owner_id, order=order,
            actions=len(turn['tool_calls']), calls=call_rows))
        section = [
            f'<section class="task-detail" id="detail-{escape(turn["event_id"])}" hidden>',
            f'<small>{escape(path)} · {profile.ATOMIC_NAME} · step {escape(event["step_id"])}</small>',
            f'<h2>{escape(turn["goal"])}</h2>',
            f'<span class="status">{escape(statuses[turn["status"]])}</span>',
        ]
        if turn['result']:
            section.append(
                f'<p>{profile.result_label()}：{escape(turn["result"])}</p>')
        for label, text in profile.details(turn, event):
            section.append(detail(label, text))
        section.append(detail('节点证据', evidence_text(turn['source_refs'])))
        for ref in turn['tool_calls']:
            source_event, call = calls[ref['tool_call_id']]
            section.append('<div class="action">' + detail(
                f'{call["tool_name"]} · {call["tool_call_id"]} · step {source_event["step_id"]}',
                '参数\n' + json.dumps(call['arguments'], ensure_ascii=False, indent=2) +
                '\n\nobservation\n' + call['observation']['raw']) + '</div>')
        section.append('</section>')
        detail_sections.append(''.join(section))

    def add_task(task, path='根任务', parent_group_id=None):
        child_tasks = task['subtasks']
        children = ([child['id'] for child in child_tasks] if child_tasks else
                    [turn['event_id'] for turn in task['turns']])
        descendant_ids = [node['event_id'] for node in atomic_nodes(task)]
        task_groups.append(dict(
            id=task['id'], goal=task['goal'], status=statuses[task['status']],
            state=task['status'], label=path, parent_group_id=parent_group_id,
            items=children, turn_ids=descendant_ids, leaf=bool(task['turns'])))
        section = [
            f'<section class="task-detail" id="detail-{escape(task["id"])}" hidden>',
            f'<small>{escape(path)} · 子任务 · {escape(task["id"])}</small>',
            f'<h2>{escape(task["goal"])}</h2>',
            f'<span class="status">{escape(statuses[task["status"]])}</span>',
        ]
        if task['reason']:
            section.append(f'<p>划分依据：{escape(task["reason"])}</p>')
        if task['result']:
            section.append(f'<p>任务结果：{escape(task["result"])}</p>')
        section.append(detail('任务证据', evidence_text(task['source_refs'])))
        if child_tasks:
            for index, child in enumerate(child_tasks, 1):
                section.append(
                    f'<button class="child-link" data-task="{escape(child["id"])}">'
                    f'{index}. 子任务 · {escape(child["goal"])}</button>')
        else:
            for index, turn in enumerate(task['turns'], 1):
                section.append(
                    f'<button class="child-link" data-task="{escape(turn["event_id"])}">'
                    f'{index}. {profile.ATOMIC_NAME} · {escape(turn["goal"])}</button>')
        section.append('</section>')
        detail_sections.append(''.join(section))
        if child_tasks:
            for index, child in enumerate(child_tasks, 1):
                child_path = str(index) if path == '根任务' else f'{path}.{index}'
                add_task(child, child_path, task['id'])
        else:
            for index, turn in enumerate(task['turns'], 1):
                add_turn(turn, f'{path} / {profile.node_path(index)}', task['id'], index)

    add_task(value['root'])
    task_index = {task['id']: task for task in tasks(value['root'])}
    edge_number = 0
    for local in graph['local_graphs']:
        for edge in local['edges']:
            edge_number += 1
            edge_id = f'dependency-{edge_number:04d}'
            source_event_ids = []
            target_event_ids = []
            call_ids = []
            section = [
                f'<section class="task-detail" id="detail-{edge_id}" hidden>',
                '<small>子任务信息依赖</small>',
                f'<h2>{escape(task_index[edge["source_task_id"]]["goal"])} → '
                f'{escape(task_index[edge["target_task_id"]]["goal"])}</h2>',
                f'<p>依赖原因：{escape(edge["reason"])}</p>',
            ]
            for evidence in edge['evidence']:
                call_id = evidence['tool_call_id']
                target_event_id = evidence['target_event_id']
                source_event, call = calls[call_id]
                if source_event['event_id'] not in source_event_ids:
                    source_event_ids.append(source_event['event_id'])
                if target_event_id not in target_event_ids:
                    target_event_ids.append(target_event_id)
                call_ids.append(call_id)
                section.append('<div class="action">' + detail(
                    f'{call_id} · step {source_event["step_id"]} → {target_event_id}',
                    '参数\n' + json.dumps(call['arguments'], ensure_ascii=False, indent=2) +
                    '\n\nobservation\n' + call['observation']['raw']) + '</div>')
            section.append('</section>')
            detail_sections.append(''.join(section))
            task_edges.append(dict(
                id=edge_id, owner_task_id=local['task_id'],
                source_task_id=edge['source_task_id'],
                target_task_id=edge['target_task_id'], reason=edge['reason'],
                evidence=edge['evidence'],
                source_event_ids=source_event_ids,
                target_event_ids=target_event_ids,
                trigger_tool_call_ids=call_ids))

    all_flags = list(value['review_flags'])
    if graph_missing:
        all_flags.append('缺少 local_graphs.json，页面只显示有序任务树')
    flags = ''.join(f'<li>{escape(flag)}</li>' for flag in all_flags)
    assets = Path(__file__).parent / 'web'
    style = (assets / 'tree.css').read_text(encoding='utf-8')
    script = (assets / 'tree.js').read_text(encoding='utf-8')
    graph_data = {
        'turn_nodes': turn_nodes,
        'task_groups': task_groups,
        'root_group_id': value['root']['id'],
        'task_edges': task_edges,
    }
    data = json.dumps(graph_data, ensure_ascii=False).replace('<', '\\u003c')
    task_count = len(list(tasks(value['root'])))
    turn_count = len(list(atomic_nodes(value['root'])))
    document = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
    document += '<meta name="viewport" content="width=device-width,initial-scale=1">'
    document += '<title>层级任务依赖图</title><style>' + style + '</style></head><body>'
    document += '<header><div><small>TRAJECTORY / TASK DEPENDENCY GRAPH</small><h1>层级任务依赖图</h1></div>'
    document += '<div class="meta">' + escape(trace['source']['filename']) + \
                f' · {task_count} 个任务 · {turn_count} 个 {profile.ATOMIC_NAME}</div></header>'
    document += '<div class="toolbar"><button id="fit">适应画布</button><button id="expand">展开全部</button>'
    document += '<button id="collapse">收起子任务</button><button id="minus" aria-label="缩小">−</button>'
    document += '<button id="plus" aria-label="放大">＋</button><span id="zoom"></span>'
    document += (f'<input id="search" type="search" placeholder="搜索子任务、{profile.ATOMIC_NAME}或编号" '
                 'aria-label="搜索任务或节点">')
    document += '<span id="count"></span></div>'
    document += '<main><div class="canvas"><svg id="tree" aria-label="层级任务依赖图"><g id="viewport"></g></svg>'
    document += '<div class="hint">默认展开全部任务 · 拖动黄色任务标题或蓝色节点可调整位置 · 黄色框与依赖边随节点实时重绘 · 蓝色箭头和标签：子任务信息依赖及原因 · 点击对象聚焦 · 拖动画布 / 滚轮缩放</div></div>'
    document += f'<aside><div class="panel-title">{profile.DETAIL_TITLE} <small>点击图中对象查看</small></div>'
    document += ''.join(detail_sections) + '</aside></main>'
    document += '<footer><details class="review"><summary>待检查项 · ' + str(len(all_flags)) + '</summary>'
    document += '<ul>' + flags + '</ul></details></footer>'
    document += '<script id="tree-data" type="application/json">' + data + '</script>'
    document += '<script>' + script + '</script></body></html>'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding='utf-8')
