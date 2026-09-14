"""Terminal-Bench 4.0 labels and node details for the shared canvas renderer."""
import json


ATOMIC_NAME = '工具调用'
DETAIL_TITLE = '任务、工具调用与依赖详情'


def node_label(event):
    return f'工具调用 {event["source_tool_index"]} · step {event["step_id"]}'


def result_label():
    return '本次调用结果'


def node_path(index):
    return f'第 {index} 个工具调用'


def details(node, event):
    result = [
        ('工具调用语义', json.dumps({
            'action_type': node['action_type'],
            'target': node['target'],
            'artifacts': node['artifacts'],
        }, ensure_ascii=False, indent=2)),
        ('原始 description / 目标种子', event['goal_seed']),
    ]
    if event.get('agent_message'):
        result.append(('同一步 Agent message', event['agent_message']))
    if event.get('context_messages'):
        result.append((
            '前置消息上下文',
            json.dumps(event['context_messages'], ensure_ascii=False, indent=2)))
    if event.get('following_context_messages'):
        result.append((
            '后续最终回复',
            json.dumps(event['following_context_messages'],
                       ensure_ascii=False, indent=2)))
    return result
