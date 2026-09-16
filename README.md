# agentCM

`agentCM` 用于把 Agent 执行轨迹整理为可审查的层级任务树和信息依赖图。当前仓库主要包含 `trajectory-graph`：它读取 ATIF-v1.7 trajectory，保留原始调用证据，生成结构化 JSON 和可交互的离线 HTML 页面。

当前支持两类输入：

| 适配器 | Agent | 原子结点 |
| --- | --- | --- |
| `terminal-bench-2.0` | `terminus-2` | 一个 agent event |
| `terminal-bench-4.0` | `claude-code` | 一个 tool call |

## 仓库结构

```text
agentCM/
├── README.md
├── trajectory.json                   # Terminal-Bench 2.0 示例轨迹
├── trajectory-graph/                 # 轨迹建图程序
│   ├── README.md                     # 设计、Prompt 和数据结构说明
│   ├── run.py                        # 源码目录下的命令行入口
│   ├── src/trajectory_graph/
│   └── tests/
└── terminal-bench-trajectory-datasets/  # 本地数据集，不纳入 Git
```

更完整的算法说明、输出 Schema、DeepSeek Prompt 和校验规则见 [`trajectory-graph/README.md`](trajectory-graph/README.md)。

## 环境要求

- Python 3.10 或以上版本
- 运行测试和本地检查无需安装第三方依赖
- 执行 `build` 需要可用的 DeepSeek API Key

在 `trajectory-graph/.env` 中配置模型访问参数：

```dotenv
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

`.env` 已加入忽略规则，不会提交到 Git。

## 快速开始

进入子项目目录：

```bash
cd trajectory-graph
```

先检查示例轨迹的格式和规模。这个命令不会调用模型：

```bash
python run.py inspect \
  --adapter terminal-bench-2.0 \
  --input ../trajectory.json
```

生成任务树和信息依赖图：

```bash
python run.py build \
  --adapter terminal-bench-2.0 \
  --input ../trajectory.json \
  --output ./runs/terminal-bench-2.0/frontier-test
```

生成离线可视化页面：

```bash
python run.py render \
  --input ./runs/terminal-bench-2.0/frontier-test
```

完成后用浏览器打开：

```text
trajectory-graph/runs/terminal-bench-2.0/frontier-test/tree.html
```

## 主要输出

| 文件 | 内容 |
| --- | --- |
| `normalized_trace.json` | 规范化后的原始轨迹和证据引用 |
| `turn_nodes.json` | 原子结点及语义标注 |
| `execution_tree.json` | 有序层级任务树 |
| `dependency_evidence.json` | 原子结点之间的信息来源证据 |
| `local_graphs.json` | 投影到任务层级的局部依赖图 |
| `tree.html` | 可展开查看任务和证据的离线页面 |

运行产物默认保存在 `trajectory-graph/runs/`，该目录不纳入 Git。

## 开发检查

```bash
cd trajectory-graph
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q run.py src tests
node --check src/trajectory_graph/web/tree.js
```

当前测试使用模拟 transport，不会发送真实 DeepSeek 请求。

## 本地数据集

`terminal-bench-trajectory-datasets/` 体积较大，已在根目录 `.gitignore` 中排除。克隆本仓库后如需运行 Terminal-Bench 4.0 case，请自行准备对应的 ATIF-v1.7 trajectory，并通过 `--input` 指定文件路径。
