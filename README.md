# agentCM

`agentCM` 用于把 Agent 执行轨迹整理为可审查的层级任务树和信息依赖图。当前仓库主要包含 `trajectory-graph`：它读取 ATIF-v1.7 trajectory，保留原始调用证据，生成结构化 JSON 和可交互的离线 HTML 页面。

项目目标与研究路线见[项目介绍](PROJECT_OVERVIEW.md)；相关工作和待审核方案见[研究调研与方案评审](RESEARCH_REVIEW.md)，待办事项见 [TODO](TODO.md)。

当前支持两类输入：

| 适配器 | Agent | 原子结点 |
| --- | --- | --- |
| `terminal-bench-2.0` | `terminus-2` | 一个 agent event |
| `terminal-bench-4.0` | `claude-code` | 一个 tool call |

## 仓库结构

```text
agentCM/
├── README.md
├── PROJECT_OVERVIEW.md                # 项目介绍与图示
├── RESEARCH_REVIEW.md                 # 待审核的调研与方案
├── TODO.md                           # 项目待办
├── trajectory.json                   # Terminal-Bench 2.0 示例轨迹
├── reproductions/                    # 外部工作的复现项目
├── rzp/                              # 边类型发现仓库，Git submodule
├── trajectory-graph/                 # 轨迹建图程序
│   ├── README.md                     # 设计、Prompt 和数据结构说明
│   ├── run.py                        # 源码目录下的命令行入口
│   ├── src/trajectory_graph/
│   └── tests/
└── terminal-bench-trajectory-datasets/  # 本地数据集，不纳入 Git
```

更完整的算法说明、输出 Schema、DeepSeek Prompt 和校验规则见 [`trajectory-graph/README.md`](trajectory-graph/README.md)。

## 在另一处获取完整代码

克隆时同时初始化子模块：

```bash
git clone --recurse-submodules https://github.com/tychenn/agentCM.git
cd agentCM
```

如果已经克隆过仓库：

```bash
git pull --ff-only
git submodule update --init --recursive
```

父仓库固定以下子模块版本，完整克隆会获取对应源码：

| 路径 | 来源 | 固定 commit |
| --- | --- | --- |
| `rzp/` | [llm_Iterative_Edge_Type](https://github.com/ZPRRR2004/llm_Iterative_Edge_Type) | `cb32e964d262854ec5a0fe135f6a05505aa8c532` |
| `reproductions/traceview/source/` | [agent-traj-visualization](https://github.com/SOAR-Lab/agent-traj-visualization) | `4b55f40efb495b9f7801ce9d25f473ed5ee2dffb` |

子模块保持各自的 Git 历史和远程地址。修改子模块代码后，需要先在该子模块中提交并推送，再在父仓库提交更新后的版本指针。可用 `git submodule status --recursive` 检查当前版本。

根仓库忽略的本地数据集、`trajectory-graph/runs/` 运行产物、虚拟环境、缓存和 `.env` 不随克隆迁移。新环境需另行准备数据与密钥，并按各项目说明安装依赖。子模块自身已经提交的文件按其固定版本获取。

## 复现项目

外部工作的代码、复现记录和实验结论统一放在 [`reproductions/`](reproductions/) 中。每项工作使用独立目录，并记录原始论文或项目地址、上游代码版本、环境、命令、预期结果、实际结果和必要改动。

新建项目时复制 [`reproductions/_template/README.md`](reproductions/_template/README.md) 作为记录模板。数据集、模型权重、检查点和运行产物分别放入 `_datasets/`、`_artifacts/`、`_checkpoints/` 等本地目录，这些目录不会提交到 Git。

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
