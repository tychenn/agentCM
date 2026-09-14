# Terminal-Bench 2.0 轨迹建图适配器

## 当前状态

项目当前实现的是 **Terminal-Bench 2.0 / Terminus 2** 轨迹适配，以及通用的有序递归任务树、tool call 信息依赖识别、任务级依赖投影和离线 HTML 可视化。原始 trajectory 保持只读。

现有输入适配代码统一放在 [`src/trajectory_graph/adapters/terminal_bench_2_0/`](src/trajectory_graph/adapters/terminal_bench_2_0/)。它只接受 `ATIF-v1.7` 且 `agent.name` 为 `terminus-2` 的轨迹；Claude Code 生成的 Terminal-Bench 4.0 轨迹需要单独的适配器。任务归并、依赖投影和渲染继续由通用模块负责。

阶段一使用局部窗口形成叶子任务，再对精简任务摘要进行分轮归并。每次请求只判断当前锚点附近的连续节点；有限回看用于修正刚形成的相邻任务边界。

最终结构为：

```text
H = (T, {G_task})

T         自底向上恢复的有序递归任务树
G_task    一个组合任务的直属子任务信息依赖图
```

`T` 的数组顺序记录实际执行顺序。`G_task` 只记录有具体 tool call 证据的信息依赖，不把相邻执行顺序重复画成边。Agent 回合保留在叶子任务内部，按 trajectory 顺序排列，不作为主图依赖边的端点。

## 运行

需要 Python 3.10 或以上版本，无需安装第三方依赖。项目目录下的 `.env` 支持：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_MODEL`，默认 `deepseek-flash`
- `DEEPSEEK_BASE_URL`，默认 `https://api.deepseek.com`

正式实验由用户运行：

```bash
cd /home/cty/agentCM/trajectory-graph

python run.py build \
  --adapter terminal-bench-2.0 \
  --input ../trajectory.json \
  --output ./runs/terminal-bench-2.0/frontier-test

python run.py render \
  --input ./runs/terminal-bench-2.0/frontier-test
```

阶段一归并参数可以按轨迹规模调整：

```bash
python run.py build \
  --adapter terminal-bench-2.0 \
  --input ../trajectory.json \
  --output ./runs/terminal-bench-2.0/frontier-test \
  --merge-window 16 \
  --merge-window-max 64 \
  --merge-input-tokens 65536 \
  --merge-lookback 1
```

开发检查不调用真实模型：

```bash
cd /home/cty/agentCM/trajectory-graph
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q run.py src tests
node --check src/trajectory_graph/web/tree.js
```

`--adapter` 当前只有 `terminal-bench-2.0`。省略 `--output` 时，结果默认写入 `runs/terminal-bench-2.0/<输入文件名>/`，目录名会保留适配版本。

旧版 `execution_tree.json` 使用混合 `items`，旧版 `turn_graph.json` 使用 frontier 和 `structure_parent_id`，不能直接交给新版 `render`。重新执行 `build` 后会生成新结构，并删除同一输出目录中的旧 `turn_graph.json` 或 `turn_links.json`。

## 输出文件

| 文件 | 内容 |
| --- | --- |
| `normalized_trace.json` | 适配器名称、规范化轨迹、原始 thought、tool call 参数和完整 observation |
| `turn_nodes.json` | 每个固定 Agent 回合及简短 tool call 结果 |
| `execution_tree.json` | 自底向上组合并通过程序校验的有序任务树 |
| `dependency_evidence.json` | 每个目标 Agent 回合使用的更早 `tool_call_id` |
| `local_graphs.json` | tool call→回合证据投影成的任务级局部依赖图及 DeepSeek 生成的边原因 |
| `task_id_map.json` | 程序归并阶段的临时任务 ID 到稳定任务 ID 的映射 |
| `tree.html` | 可展开、聚焦和查看证据的离线页面 |
| `preprocess_calls.jsonl` | query 提取和必要的 observation 拆分请求记录 |
| `execution_calls.jsonl` | Agent 回合标注、局部任务归并、边界复核和依赖选择请求记录 |
| `grouping_steps.jsonl` | 每轮 frontier、局部选择、边界复核和收敛过程 |
| `cache/`、`checkpoint.json` | 已验证响应缓存和继续运行状态 |

`build` 默认最大输出长度为 32768，默认上下文上限为 1048576，超时为 600 秒。语义请求开启 thinking；observation 起点识别关闭 thinking 并使用 `temperature=0`。响应截断、JSON 错误或程序校验失败时会携带错误重试；observation 拆分固定最多请求三次，其他阶段使用 `--retries`。

## 两阶段处理流程

```text
trajectory.json
    │
    ▼
Terminal-Bench 2.0 适配：query、event、tool call、observation 对齐
    │
    ▼
逐 event 生成固定 Agent 回合
    │
    ▼
阶段一：局部形成叶子任务，再分轮归并为有序任务树
    │
    ▼
execution_tree.json
    │
    ▼
阶段二：逐目标回合选择直接信息来源
    │
    ▼
dependency_evidence.json
    │
    ▼
程序投影到最深公共任务的直属子任务
    │
    ▼
DeepSeek 为固定任务边生成简短原因
    │
    ▼
local_graphs.json → tree.html
```

### 预处理

Terminal-Bench 2.0 适配器面向 `terminus-2` 的 ATIF-v1.7 输出。程序保留 `source`、`step_id`、agent `message`、有效 tool 参数和 `tool_call_id`。agent `message` 规范化为 `thought`。固定的 parser warning 前缀会在 observation 开头被删除。

observation result 含 `source_call_id` 时，程序按它与当前 step 的 `tool_call_id` 精确对应，并保留原文；结果顺序无需与 tool call 顺序一致。缺少该标识且只有一个 tool call 时，程序直接对齐。多个 tool call 共用未标识的聚合 observation 时，DeepSeek 只返回各段的精确开始锚点，程序复制和切分原文。锚点连续三次无法使原文完整分区时停止构建。终端只显示对齐方式、输入计数及每个 `tool_call_id` 分配到的字符数，不打印 tool 参数和 observation 正文。

### 阶段一：有序任务树

每个 `source: "agent"` event 固定为一个 Agent 回合。模型不能拆分、合并、遗漏、重复或移动其中的 tool call。

DeepSeek 先分别标注每个回合的 `goal`、`status`、`result` 和每个调用的简短结果。程序随后执行以下局部分层归并流程。

#### 1. 构造精简节点

程序先把每个 Agent 回合转换为不可拆分的 frontier 节点。发送给分组模型的卡片只保留划分任务所需的信息：

```json
{
  "node_id": "event-0003",
  "node_kind": "agent_turn",
  "start_order": 3,
  "end_order": 3,
  "goal": "安装 OCR 和 PDF 提取工具",
  "status": "completed",
  "completion_condition": null,
  "result": "tesseract-ocr 和 poppler-utils 已安装",
  "first_turn_goal": "安装所需工具",
  "last_turn_goal": "安装所需工具",
  "descendant_turn_count": 1,
  "direct_child_count": 0,
  "evidence_event_ids": ["event-0003"]
}
```

原始 thought、完整 tool 参数、完整 observation 和 `source_refs` 留在程序侧，局部归并请求只发送精简卡片。卡片中的 `evidence_event_ids` 让模型选择代表性后代事件，程序再从已验证 Agent 回合复制精确证据。

#### 2. 形成叶子任务

程序从最左侧尚未处理的 Agent 回合开始，向右提供一个局部窗口。一次请求只判断锚点回合与其后连续候选是否共同完成一个局部目标。模型可以：

- 选择包含锚点的连续前缀，长度为 `2～K`，形成一个叶子任务；
- 保留锚点为单回合叶子任务；
- 在当前窗口尚未看到任务右边界时请求扩展窗口。

请求中带一个已定稿的左侧节点和一个候选窗口之外的右侧节点作为边界参考。这两个上下文节点只能用于判断，不能进入本次 `member_ids`：

```json
{
  "root_goal": {"title": "用户任务标题", "text": "用户原始目标"},
  "phase": "group-leaf",
  "round": 1,
  "left_context": null,
  "candidates": [
    {"node_id": "event-0001", "goal": "...", "result": "..."},
    {"node_id": "event-0002", "goal": "...", "result": "..."}
  ],
  "right_context": {"node_id": "event-0003", "goal": "...", "result": "..."}
}
```

Agent 回合已经是原子执行节点。叶子任务采用最小操作闭环：围绕一个直接目标产生一个主要产出，并具有一个完成条件；它可以包含一个或多个 Agent 回合。单条命令、单条 observation 或中间结果可以被检查，不足以单独构成叶子任务。模型从锚点开始逐个检查相邻边界，只能归并第一个有效边界之前的连续前缀：

- 重试、命令修正、同一操作的分批处理、共同支持同一诊断的证据收集，以及操作后的直接验证仍进入同一叶子任务；
- 当前前缀已经完成其直接操作、产生主要产出，并且下一回合开始具有不同直接目标、主要产出或完成条件的新操作时，在两者之间建立边界；
- “发现或诊断 → 修复或安装”“规划或选择 → 执行”“产生产物 → 下游分析”属于需要重点检查的阶段转换；
- 多个操作属于同一个宽泛阶段，不足以把它们归并成一个叶子任务；宽泛阶段由后续组合任务表达。

主要产出可以是诊断、决策、产物、状态变化或验证结果。日志、临时文件、部分批次和孤立事实如果只表示当前完成条件的中间进度，不形成边界。相邻回合之间存在信息依赖也不自动要求拆分，仍需先判断它们是否服务于同一个直接目标和完成条件。

例如“检查环境并确认缺少工具”和“根据检查结果安装工具”应形成两个叶子任务，再由上层“准备处理环境”组合任务统一包含。该规则根据操作目标和完成条件判断，不依赖 OCR、包管理器等特定名称。

模型只返回动作、连续成员 ID 和简短摘要，例如：

```json
{
  "action": "merge",
  "member_ids": ["event-0002", "event-0003"],
  "task": {
    "goal": "准备 OCR 和 PDF 文本提取工具",
    "completion_condition": "所需工具可用",
    "status": "completed",
    "reason": "两个回合共同完成工具选择和安装",
    "result": "已确认安装方式并完成工具安装",
    "source_event_ids": ["event-0002", "event-0003"]
  },
  "review_flags": []
}
```

#### 3. 分轮归并组合任务

叶子任务形成后，它们成为下一层 frontier。程序仍从左向右扫描，每次允许模型归并连续的 `2～K` 个 frontier 节点。归并成功后，程序创建一个组合任务，用新的精简摘要卡片替换这些节点；完整子节点继续保存在树中。

每一轮只使用该轮开始时的 frontier 快照。已归并区间不能重叠，新生成的组合任务到下一轮才参与更高层归并。这样可以把同一层的局部判断固定下来，并保留确定的构建过程。

组合任务需要满足：

- 直属子任务至少有两个；
- 子任务在当前 frontier 中连续且顺序不变；
- 组合目标比父级目标具体，并由全部子任务共同支持；
- 组合任务的区间等于直属子任务区间的并集；
- 一个节点在一轮中最多被消费一次。

模型返回内容与叶子归并相同，只把 `member_ids` 换成当前 frontier 中的任务 ID。`status`、`reason` 和 `result` 仍由 DeepSeek 根据当前窗口判断；程序校验其取值和证据归属。归并得到的新卡片继续保留节点类型、起止顺序、目标、状态、结果、首尾目标、后代回合数和直属子任务数量，供下一轮使用。

每一轮的程序流程为：

```text
snapshot = 当前 frontier
next_frontier = []
i = 0

while i < len(snapshot):
    从 snapshot[i] 开始构造局部窗口
    decision = DeepSeek(window)

    if decision 是长度 m 的 merge:
        校验并创建组合节点
        next_frontier.append(组合节点)
        i += m
    else if decision 是 keep:
        next_frontier.append(snapshot[i])
        i += 1
    else if decision 是 need_more_context:
        在输入预算内扩大窗口并重新请求

frontier = next_frontier
```

#### 4. `K`、窗口扩展与输入预算

`K` 表示一次请求最多同时判断的候选节点数。一个最终任务可以包含超过 `K` 个 Agent 回合，因为它可以经过多轮归并形成。

默认使用以下配置：

- 初始窗口 `K_initial` 默认设为 `16`；
- 最大窗口 `K_max` 默认设为 `64`，并允许用户设置得更大；
- 单次请求同时受 `--merge-input-tokens` 的保守 UTF-8 容量预算限制；节点摘要较长时，程序减少实际候选数；
- 模型返回 `need_more_context` 时，程序按 `16 → 32 → 64` 扩大窗口，直到找到边界、到达 frontier 末尾、达到 `K_max` 或触及输入预算；
- 达到窗口限制后，模型必须选择 `merge` 或 `keep`，并通过 `review_flags` 记录边界不确定性；程序不会静默截断输入。

因此，`K=4` 可以用于当前这类短轨迹的调试，不作为所有任务的固定上限。`--merge-window`、`--merge-window-max` 和 `--merge-input-tokens` 可以在 `build` 时覆盖默认值。输入预算连一个精简节点都无法容纳时，程序明确中止并提示增大配置。

#### 5. 有限回看与边界修正

局部前缀归并采用从左到右的决策顺序。为修正刚形成的任务边界，程序在提交相邻两个输出任务前增加一次有限边界复核。

设回看宽度为 `B`，默认 `B=1`。每次复核只读取：

- 左侧任务的摘要及其末尾最多 `B` 个直属成员；
- 右侧任务的摘要及其开头最多 `B` 个直属成员；
- 边界外左右各一个只读上下文节点。

叶子任务阶段的直属成员是固定 Agent 回合；组合任务阶段的直属成员是当前 frontier 节点。回看只能移动这些完整成员，不能拆开 Agent 回合，也不能展开或重组 frontier 节点内部已经固定的子树。

模型可以返回以下动作：

- `keep_boundary`：保留当前边界；
- `shift_left`：把右侧开头的 `1～B` 个成员移动到左侧；
- `shift_right`：把左侧末尾的 `1～B` 个成员移动到右侧；
- `merge_adjacent`：取消边界，把两侧合并成一个任务。

例如当前两个任务的直属成员为 `[A, B] | [C, D]`，`B=1` 时，允许得到 `[A] | [B, C, D]`、`[A, B, C] | [D]`、保持原边界或合并全部成员。模型只返回动作、移动数量、理由以及受影响任务的新摘要；成员列表由程序根据动作复制和重建。

边界复核采用以下提交规则：

1. 新任务生成后先作为 provisional task；
2. 下一个相邻任务生成后，模型复核这两个 provisional task 之间的边界；
3. 复核完成后冻结左侧任务，右侧任务继续作为下一次复核的 provisional task；
4. 到达本轮末尾后冻结最后一个 provisional task；
5. 每条边界在当前层只复核一次，不能反复左右移动。

程序校验移动数量不超过 `B`、两侧成员仍连续、顺序和覆盖不变。边界移动后若一侧只剩一个成员，程序直接保留该原节点，避免创建单子任务包装层；一侧将变为空时只接受 `merge_adjacent`。`--merge-lookback` 可以调整 `B`，并要求 `0 ≤ B < K`；设为 `0` 可以关闭边界复核。

#### 6. 收敛条件

一次局部请求返回“保留”只代表当前锚点没有合适的连续归并对象。程序必须完成整轮扫描：

1. 一轮产生至少一次归并时，用新 frontier 开始下一轮；
2. 完整一轮产生零次归并时停止；
3. 停止时若 frontier 仍有多个节点，它们直接成为根任务的有序子任务；
4. frontier 只剩一个节点时，程序把该节点内容提升到根任务，避免单子任务包装层。

#### 7. 程序校验和可 review 记录

程序负责校验当前 frontier 成员资格、连续性、唯一性、区间并集、顺序、完整覆盖、每轮非重叠和无单子任务组合。模型只判断哪些相邻节点表达同一层级的任务目标，以及应当如何概括该任务。

`grouping_steps.jsonl` 逐次记录：

- 轮次、锚点、实际窗口大小和输入节点摘要；
- 模型返回的 `merge`、`keep` 或 `need_more_context`；
- 边界复核的动作、移动数量和复核理由；
- 通过程序校验的模型结果；校验失败原因保存在 `execution_calls.jsonl`；
- 归并前后的 frontier ID 列表和新任务摘要。

任务树完成后再进入阶段二。阶段一只建立有序包含关系，不推断 tool call 信息依赖。

所有层级仍遵守以下最终结构约束：

- 叶子任务包含一个或多个相邻 Agent 回合；
- 组合任务只包含至少两个相邻子任务；
- 一个任务不能同时直接包含回合和子任务；
- 所有叶子的深度优先顺序必须与 trajectory 完全一致；
- 数组顺序直接表达任务和回合的执行顺序。

模型只返回后代 `event_id` 作为任务证据选择。程序从已验证 Agent 回合复制精确 `source_refs`，根任务证据固定指向原始 query。

保存后的任务结构为：

```json
{
  "id": "task-0001",
  "goal": "用户任务",
  "status": "completed",
  "reason": null,
  "result": "结果摘要",
  "source_refs": [],
  "subtasks": [],
  "turns": []
}
```

叶子任务使用非空 `turns` 和空 `subtasks`；组合任务使用非空 `subtasks` 和空 `turns`。

### 阶段二：信息依赖和任务投影

任务树完成后，程序按 trajectory 顺序处理每个目标 Agent 回合。依赖请求读取：

- 根 query；
- 全部更早 Agent 回合；
- 更早回合中每个 tool call 的输入、简短结果和完整 observation；
- 当前目标回合的完整卡片。

DeepSeek 只判断哪些更早 tool call 结果被当前回合直接使用、响应、验证、修复或用于选择具体行动。主题相似、时间相邻和一般背景不生成依赖。没有直接来源时允许空数组。

最小证据格式为：

```json
{
  "target_event_id": "event-0003",
  "trigger_tool_call_ids": ["call_0_3", "call_1_2"]
}
```

程序根据 `tool_call_id` 找到来源叶子任务，根据 `target_event_id` 找到目标叶子任务：

1. 来源和目标在同一叶子任务时，不生成任务边；其中的 Agent 回合保持固定顺序。
2. 来源和目标属于不同叶子任务时，找到两者最深公共任务。
3. 将两端提升为该公共任务的两个直属子任务。
4. 相同来源任务和目标任务的证据合并为一条边。
5. 校验来源任务早于目标任务、调用属于来源任务、目标回合属于目标任务，并保证全部跨任务证据恰好投影一次。

程序固定边的两端和证据后，一次请求把全部任务边及其原始证据交给 DeepSeek。模型只能为每条边补充一个不超过 100 个字符的 `reason`，不能增删、重排或改向边。原因需要说明来源任务产生了什么信息，以及目标任务如何使用、响应、验证或修复这些信息。

`local_graphs.json` 的边结构为：

```json
{
  "task_id": "task-0001",
  "edges": [
    {
      "source_task_id": "task-0002",
      "target_task_id": "task-0004",
      "reason": "工具检查发现 OCR 组件缺失，因此后续任务安装相应软件包",
      "evidence": [
        {
          "tool_call_id": "call_0_3",
          "target_event_id": "event-0003"
        }
      ]
    }
  ]
}
```

每个任务都有一条 `local_graphs` 记录，叶子任务和没有跨子任务依赖的组合任务使用空 `edges`。

## 可视化

页面默认展开全部任务和 Agent 回合；可以使用“收起子任务”按钮或任务右上角按钮折叠层级。黄色框表示任务，蓝色节点表示叶子任务内部的 Agent 回合。组合任务先根据直属子任务之间的信息依赖计算 DAG 层级：相邻任务层交替采用横向和纵向布局，同一依赖层中的分支沿垂直于主方向的方向展开。叶子任务内的 Agent 回合仍按编号从左向右排列。

蓝色箭头只表示 `local_graphs.json` 中的信息依赖。相邻层依赖在来源与目标任务之间直接连线；跨层依赖沿黄色任务容器内侧的预留通道绕过中间节点。边标签显示 DeepSeek 生成的简短原因及对应 tool call 证据。

黄色任务可以通过标题区域自由拖动，任务内部的所有子任务和 Agent 回合会随其一起移动；蓝色 Agent 回合也可以单独拖动。每次移动时，程序从最内层任务开始计算直属内容的包围盒，依次更新所有祖先黄色框的位置和大小。相关依赖边随后根据更新后的任务边界重新选择上下或左右连接位置。“适应画布”会根据调整后的全部节点范围重新居中和缩放。刷新页面会恢复自动布局。

边标签直接显示 DeepSeek 生成的简短原因，并在下方显示具体 `tool_call_id` 或证据数量。点击任务、Agent 回合或依赖边会虚化无关内容；点击依赖边可在右侧查看完整原因、来源调用参数、完整 observation 和目标回合。折叠子任务后仍可查看父级局部图中的任务边。

## DeepSeek Prompt 文件

通用任务树 prompt 位于 [src/trajectory_graph/prompts/](src/trajectory_graph/prompts/)，Terminal-Bench 2.0 输入和回合标注 prompt 位于 [src/trajectory_graph/adapters/terminal_bench_2_0/prompts/](src/trajectory_graph/adapters/terminal_bench_2_0/prompts/)。程序将公共规则、对应阶段的 system prompt 和 user prompt 组合后发送给模型。

| 用途 | System / 输出格式 | User |
| --- | --- | --- |
| 公共 JSON、证据和安全规则 | [common.md](src/trajectory_graph/prompts/common.md) | — |
| 提取根任务 | [extract_root_v1.md](src/trajectory_graph/prompts/extract_root_v1.md) | [extract_root_user.md](src/trajectory_graph/prompts/extract_root_user.md) |
| Terminal-Bench 2.0 对齐聚合 observation | [align_observations_v1.md](src/trajectory_graph/adapters/terminal_bench_2_0/prompts/align_observations_v1.md) | [align_observations_user.md](src/trajectory_graph/adapters/terminal_bench_2_0/prompts/align_observations_user.md) |
| Terminal-Bench 2.0 标注固定 Agent 回合 | [annotate_turn_v1.md](src/trajectory_graph/adapters/terminal_bench_2_0/prompts/annotate_turn_v1.md) | [annotate_turn_user.md](src/trajectory_graph/adapters/terminal_bench_2_0/prompts/annotate_turn_user.md) |
| 阶段一任务摘要格式 | [task_summary_format.md](src/trajectory_graph/prompts/task_summary_format.md) | — |
| 局部形成叶子任务 | [group_leaf_v1.md](src/trajectory_graph/prompts/group_leaf_v1.md) | [group_leaf_user.md](src/trajectory_graph/prompts/group_leaf_user.md) |
| 分轮归并组合任务 | [merge_tasks_v1.md](src/trajectory_graph/prompts/merge_tasks_v1.md) | [merge_tasks_user.md](src/trajectory_graph/prompts/merge_tasks_user.md) |
| 有限边界复核 | [review_boundary_v1.md](src/trajectory_graph/prompts/review_boundary_v1.md) | [review_boundary_user.md](src/trajectory_graph/prompts/review_boundary_user.md) |
| 汇总根任务状态 | [finalize_root_v1.md](src/trajectory_graph/prompts/finalize_root_v1.md) | [finalize_root_user.md](src/trajectory_graph/prompts/finalize_root_user.md) |
| 选择 tool call 信息来源 | [select_dependencies_v1.md](src/trajectory_graph/prompts/select_dependencies_v1.md) | [select_dependencies_user.md](src/trajectory_graph/prompts/select_dependencies_user.md) |
| 生成任务依赖边原因 | [explain_dependencies_v1.md](src/trajectory_graph/prompts/explain_dependencies_v1.md) | [explain_dependencies_user.md](src/trajectory_graph/prompts/explain_dependencies_user.md) |
| 校验失败后的统一重试 | [retry.md](src/trajectory_graph/prompts/retry.md) | — |

## 程序校验

程序至少检查以下约束：

- 每个 agent event 恰好生成一个 Agent 回合，所有原始 tool call 保持顺序；
- 每个任务只使用 `subtasks` 或 `turns` 中的一种；
- 每个组合任务至少有两个直属子任务；
- 叶子任务中的回合连续，整棵树覆盖全部回合且顺序不变；
- 任务 ID 唯一，根任务目标等于提取后的用户 query；
- 模型只选择后代 event 作为任务证据，原文引用由程序复制；
- dependency 只能引用更早的 tool call，ID 不重复且保持 trajectory 顺序；
- 局部图边只能连接同一父任务的两个直属子任务，并从较早任务指向较晚任务；
- 每条边的 tool call 属于来源任务，目标 event 属于目标任务；
- 每项跨叶子任务证据恰好投影一次，叶子任务内部依赖不绘制任务边。
- 每条最终任务边都有一个非空且不超过 100 个字符的模型原因，模型不能修改固定端点或顺序。

任务划分和信息依赖包含语义判断，仍需结合轨迹 review。程序负责原文、顺序、归属、完整性和图结构校验。

## 代码结构

```text
trajectory-graph/
├── README.md
├── run.py
├── src/trajectory_graph/
│   ├── cli.py
│   ├── adapters/
│   │   └── terminal_bench_2_0/
│   │       ├── annotation.py
│   │       ├── normalize.py
│   │       └── prompts/
│   ├── grouping.py
│   ├── dependencies.py
│   ├── deepseek_client.py
│   ├── validate.py
│   ├── render.py
│   ├── prompts/
│   └── web/
├── runs/terminal-bench-2.0/<input-stem>/
└── tests/terminal_bench_2_0/test_pipeline.py
```
