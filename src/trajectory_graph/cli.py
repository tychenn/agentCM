"""Command line entry point for normalization and hierarchical graph building."""
import argparse
import hashlib
import os
import sys
from pathlib import Path

from .deepseek_client import Client, save
from .config import load_env
from .dependencies import (add_dependency_reasons, build_dependency_evidence,
                           project_local_graphs)
from .grouping import build_task_tree
from .normalize import load, normalize, prepare
from .validate import (Invalid, attach_tool_calls, expand_grouping, require,
                       stable_ids, strict_json, tree, turn_annotation)


def parser():
    result = argparse.ArgumentParser(description='ATIF 轨迹预处理及层级任务依赖图恢复')
    sub = result.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect', help='本地检查输入规模，不调用 API')
    inspect.add_argument('--input', required=True, type=Path)
    for name, help_text in [('normalize', '只运行预处理'), ('build', '生成有序任务树和信息依赖图')]:
        command = sub.add_parser(name, help=help_text)
        command.add_argument('--input', required=True, type=Path)
        command.add_argument('--output', type=Path, help='默认保存到 runs/<输入文件名>/；normalize 可指定 JSON 文件')
        command.add_argument('--resume', action='store_true', default=True, help=argparse.SUPPRESS)
        command.add_argument('--model', default=os.environ.get('DEEPSEEK_MODEL', 'deepseek-flash'))
        command.add_argument('--base-url', default=os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'))
        command.add_argument('--max-output-tokens', type=int, default=32768)
        command.add_argument('--context-tokens', type=int, default=1048576,
                             help='模型上下文上限；请求以 UTF-8 字节数保守估计，不截断')
        command.add_argument('--timeout', type=float, default=600)
        command.add_argument('--retries', type=int, default=3)
        if name == 'build':
            command.add_argument('--merge-window', type=int, default=16,
                                 help='局部归并初始候选节点数，默认 16')
            command.add_argument('--merge-window-max', type=int, default=64,
                                 help='局部归并最大候选节点数，默认 64')
            command.add_argument('--merge-input-tokens', type=int, default=65536,
                                 help='局部归并输入的保守 UTF-8 容量预算，默认 65536')
            command.add_argument('--merge-lookback', type=int, default=1,
                                 help='任务边界两侧允许回看的直属节点数，默认 1')
    visual = sub.add_parser('render', help='将层级任务依赖图生成为可展开的 HTML 页面，不调用模型')
    visual.add_argument('--input', required=True, type=Path, help='execution_tree.json 文件或运行目录')
    visual.add_argument('--output', type=Path, help='默认保存为同目录的 tree.html')
    check = sub.add_parser('validate', help='本地校验已生成树与规范化轨迹')
    check.add_argument('--tree', required=True, type=Path)
    check.add_argument('--trace', required=True, type=Path)
    return result


def run(args, transport=None):
    if args.command == 'render':
        from .render import render_tree
        source = args.input / 'execution_tree.json' if args.input.is_dir() else args.input
        output = args.output or source.parent / 'tree.html'
        render_tree(source, source.parent / 'normalized_trace.json', output,
                    source.parent / 'local_graphs.json')
        print('已保存: ' + str(output.resolve()))
        return
    if args.command == 'validate':
        value = strict_json(args.tree.read_text(encoding='utf-8'))
        trace = strict_json(args.trace.read_text(encoding='utf-8'))
        tree(value, trace)
        print('校验通过')
        return
    original, source = load(args.input)
    prepared, input_flags = prepare(original)
    if args.command == 'inspect':
        print(f"query: 1; events: {len(prepared)}; agent events: {sum(e['source'] == 'agent' for e, _ in prepared)}; "
              f"tool calls: {sum(len(e['tool_calls']) for e, _ in prepared)}")
        print('SHA-256: ' + source['sha256'])
        for flag in input_flags:
            print(flag)
        return
    require(args.retries >= 0 and args.timeout > 0 and args.max_output_tokens > 0 and
            args.context_tokens > args.max_output_tokens, 'Invalid request limits')
    if args.command == 'build':
        require(2 <= args.merge_window <= args.merge_window_max,
                'Require 2 <= --merge-window <= --merge-window-max')
        require(args.merge_input_tokens > 0,
                '--merge-input-tokens must be positive')
        require(0 <= args.merge_lookback < args.merge_window,
                'Require 0 <= --merge-lookback < --merge-window')
    default = Path('runs') / args.input.stem
    output = (args.output or (default if args.command == 'build' else default / 'normalized_trace.json')).resolve()
    directory = output if args.command == 'build' else output.parent
    normalized_path = directory / 'normalized_trace.json' if args.command == 'build' else output
    require(args.input.resolve() != normalized_path, 'Output would overwrite input trajectory')
    require(not args.input.resolve().is_relative_to(directory), '请选择不包含原始输入文件的独立输出目录')
    checkpoint = directory / 'checkpoint.json'
    if checkpoint.exists():
        old = strict_json(checkpoint.read_text())
        require(old['source'] == source, 'Resume source filename/SHA-256 changed; choose a new directory')
    directory.mkdir(parents=True, exist_ok=True)
    client = Client(directory, model=args.model, base_url=args.base_url, max_tokens=args.max_output_tokens,
                    context_tokens=args.context_tokens, timeout=args.timeout, retries=args.retries,
                    resume=args.resume, transport=transport)
    state = {'stage': 'starting', 'source': source}
    save(checkpoint, state)
    try:
        trace = normalize(original, source, client)
        save(normalized_path, trace)
        state['stage'] = 'normalized'
        save(checkpoint, state)
        if args.command == 'build':
            annotation_turns, annotation_flags = [], []
            for event in trace['events']:
                if event['source'] != 'agent':
                    continue
                response = client.ask(
                    f'annotate-{event["event_id"]}', ['annotate_turn_v1'], 'annotate_turn_user',
                    {'agent_event_json': event},
                    lambda value, current=event: turn_annotation(value, current),
                    output_tokens=args.max_output_tokens, thinking=True)
                annotation_turns.append(response['turn'])
                annotation_flags.extend(response['review_flags'])
            annotations = {'turns': annotation_turns, 'review_flags': annotation_flags}
            turn_nodes = attach_tool_calls(annotations, trace)
            save(directory / 'turn_nodes.json', {
                'turns': turn_nodes, 'review_flags': annotations['review_flags']})
            state['stage'] = 'turns_annotated'
            save(checkpoint, state)
            grouped_refs = build_task_tree(
                trace, turn_nodes, client,
                window=args.merge_window,
                window_max=args.merge_window_max,
                input_tokens=args.merge_input_tokens,
                lookback=args.merge_lookback,
            )
            final = expand_grouping(grouped_refs, trace, turn_nodes)
            final, mapping = stable_ids(final)
            final['review_flags'] = list(dict.fromkeys(
                trace['review_flags'] + annotations['review_flags'] +
                final['review_flags']))
            tree(final, trace, turn_nodes)
            save(directory / 'task_id_map.json', mapping)
            save(directory / 'execution_tree.json', final)
            for stale_name in ('dependency_evidence.json', 'local_graphs.json'):
                stale_path = directory / stale_name
                if stale_path.exists():
                    stale_path.unlink()
            state['stage'] = 'task_tree_built'
            save(checkpoint, state)
            dependencies = build_dependency_evidence(trace, turn_nodes, client)
            save(directory / 'dependency_evidence.json', dependencies)
            state['stage'] = 'dependencies_selected'
            save(checkpoint, state)
            graph_skeleton = project_local_graphs(final, dependencies, trace)
            graphs = add_dependency_reasons(
                final, graph_skeleton, dependencies, trace, client)
            save(directory / 'local_graphs.json', graphs)
            for legacy_name in ('turn_graph.json', 'turn_links.json'):
                legacy_path = directory / legacy_name
                if legacy_path.exists():
                    legacy_path.unlink()
            state['stage'] = 'complete'
        else:
            state['stage'] = 'normalized'
        require(hashlib.sha256(args.input.read_bytes()).hexdigest() == source['sha256'], 'Source changed during run')
        save(checkpoint, state)
    except Exception as error:
        state['error'] = client.redactor.hide(str(error), 'error')
        save(checkpoint, state)
        raise
    if args.command == 'build':
        print('已保存: ' + str(directory / 'execution_tree.json'))
        print('已保存: ' + str(directory / 'dependency_evidence.json'))
        print('已保存: ' + str(directory / 'local_graphs.json'))
    else:
        print('已保存: ' + str(normalized_path))


def main():
    try:
        load_env()
        args = parser().parse_args()
        run(args)
    except (Invalid, ValueError, RuntimeError, OSError, KeyError, TypeError, RecursionError) as error:
        print(f'错误: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
