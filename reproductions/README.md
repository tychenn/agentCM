# 复现项目

此目录集中管理外部论文、开源项目和实验方法的复现工作。每个项目保留独立的代码、环境说明和结果记录，便于重复运行和核对差异。

## 项目清单

| 项目 | 来源 | 状态 | 复现目标 | 结果 |
| --- | --- | --- | --- | --- |
| [TraceView](traceview/) | [论文](https://arxiv.org/abs/2606.22110) / [代码](https://github.com/SOAR-Lab/agent-traj-visualization) | `setup` | 启动官方应用并确定论文复现范围 | 待运行 |

状态统一使用：`planned`、`setup`、`running`、`verified` 或 `blocked`。

## 目录约定

```text
reproductions/
├── README.md
├── _template/
│   └── README.md
└── <project-name>/
    ├── README.md          # 来源、版本、命令、结果和差异
    ├── source/            # 上游源码或 Git submodule
    ├── configs/           # 复现实验配置
    ├── scripts/           # 下载、预处理、训练和评测脚本
    ├── patches/           # 对上游代码的独立补丁
    ├── _datasets/         # 本地数据，不提交
    ├── _checkpoints/      # 本地模型和检查点，不提交
    └── _artifacts/        # 日志、图表和运行产物，不提交
```

仅创建项目实际需要的子目录。

## 新增项目

1. 使用简短、稳定的小写名称创建目录，例如 `reproductions/agentbench`。
2. 复制 `_template/README.md`，先填写来源 URL、论文或项目版本、上游 commit 和 License。
3. 明确复现指标、目标值和验收条件，再开始修改代码或运行实验。
4. 原样使用上游代码时，优先把 `source/` 添加为 Git submodule，并固定 commit。
5. 需要直接修改上游源码时，可以将源码纳入当前仓库，同时在 README 中记录上游 commit 和所有差异；不要保留嵌套的 `.git/`。
6. 每次得到可复核结果后，更新本页项目清单和项目 README。

## 文件边界

可以提交：

- 复现说明、配置、脚本和小型测试样例
- 必要的源码修改或补丁
- 体积合理且可直接审查的汇总结果

保留在本地：

- 数据集、模型权重和检查点
- 大型日志、缓存和中间产物
- API Key、Token、账号信息和 `.env`

添加文件前使用 `git status --short` 核对范围。外部源码如果包含独立 `.git/`，应先决定使用 submodule 还是纳入当前仓库，避免产生不可用的嵌套仓库引用。
