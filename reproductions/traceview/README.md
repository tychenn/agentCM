# TraceView

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 论文 | [TraceView: Interactive Visualization of Agentic Program Repair Trajectories](https://arxiv.org/abs/2606.22110) |
| 作者 | Amirali Sajadi、Tu Nguyen、Kimmie Huynh、Esteban Parra、Preetha Chatterjee |
| 会议 | ICSME 2026 Tool Demonstration and Data Showcase Track |
| 官方代码 | [SOAR-Lab/agent-traj-visualization](https://github.com/SOAR-Lab/agent-traj-visualization) |
| 上游分支 | `main` |
| 固定 commit | `4b55f40efb495b9f7801ce9d25f473ed5ee2dffb` |
| 获取日期 | 2026-09-17 |
| 管理方式 | Git submodule，路径为 `source/` |
| 状态 | `setup` |
| 代码 License | 上游仓库当前未发现 `LICENSE` 或 `COPYING` 文件，待向作者或仓库维护者确认 |

## 工作简介

TraceView 是一个基于 Streamlit 的 Agent 轨迹标注与可视化工具。它把程序修复 Agent 的步骤组织为 Thought、Action 和 Result 结点，支持动作类别、语义关系、补丁结果、关系统计以及结点证据查看。

官方仓库包含 AutoCodeRover 风格的已标注数据、重建轨迹、评估样例和用户研究材料。应用入口为 `source/traceview.py`，主要实现位于 `source/traceview_app/`。

## 初步复现目标

1. 建立与上游一致的 Python 3.14 环境并安装锁定依赖。
2. 启动官方 Streamlit 应用。
3. 验证仓库内置 AutoCodeRover 样例可以进入 Overview 和 Analysis 页面。
4. 验证原始轨迹的 Labeling、导出和可视化流程。
5. 阅读论文与评估材料后，再确定需要复现的论文图表、功能演示和用户研究边界。

## 本地隔离环境

| 项目 | 当前配置 |
| --- | --- | --- |
| 系统默认 Python | `3.12.3`，保持不变 |
| 项目 Python | uv 管理的 CPython `3.14.6` |
| uv | `0.12.15`，安装在 `/home/cty/.local/bin/uv` |
| 虚拟环境 | `source/.venv` |
| 依赖来源 | 上游 `uv.lock`，使用 `--locked` 安装 |

项目虚拟环境约占 509 MB。系统 `python` 仍指向 `/home/cty/anaconda3/bin/python`，其他项目不会自动使用 TraceView 的 Python 3.14 或依赖。

## 获取源码

克隆 `agentCM` 后初始化该 submodule：

```bash
git submodule update --init --recursive reproductions/traceview/source
```

当前固定版本可这样核对：

```bash
git -C reproductions/traceview/source rev-parse HEAD
```

预期输出：

```text
4b55f40efb495b9f7801ce9d25f473ed5ee2dffb
```

## 安装与运行

本机使用以下命令完成隔离环境安装：

```bash
cd reproductions/traceview/source
uv python install 3.14
uv sync --python 3.14 --locked
uv run streamlit run traceview.py
```

检查环境与锁文件是否一致：

```bash
uv sync --locked --check
uv run --locked python --version
uv run --locked streamlit --version
```

## 结果

2026-09-17 完成环境安装和启动检查：

- `uv sync --locked --check` 检查 91 个包，未要求修改环境或锁文件；
- 核心依赖可以导入，Streamlit 版本为 `1.54.0`，pandas 版本为 `2.3.3`；
- 应用在临时端口 `127.0.0.1:18501` 启动；
- `/_stcore/health` 返回 `ok`，首页返回 HTTP 200；
- 检查完成后已停止服务，没有保留监听进程；
- 尚未验证内置样例、Labeling 流程和论文功能对应关系。

## 与上游的差异

当前没有修改上游源码。父仓库只记录 submodule 的固定 commit。

## 注意事项

- 论文预印本页面标注的是论文文本许可，不能直接推定代码许可。
- 在代码 License 得到确认前，保留上游来源和 commit 记录，避免复制或重新发布源码内容。
- 更新 submodule 前先记录现有复现结果，确认新 commit 的行为变化后再修改父仓库指针。
