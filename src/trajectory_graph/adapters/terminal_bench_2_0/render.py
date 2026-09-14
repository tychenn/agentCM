"""Terminal-Bench 2.0 labels and node details for the shared canvas renderer."""


ATOMIC_NAME = 'Agent 回合'
DETAIL_TITLE = '任务、回合与依赖详情'


def node_label(event):
    return f'回合 {event["step_id"]}'


def result_label():
    return '本回合结果'


def node_path(index):
    return f'第 {index} 回合'


def details(node, event):
    return [('Agent message', event['thought'])]
