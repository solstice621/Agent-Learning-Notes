# Agent Learning Notes｜设计研究版 v3

**Codex CLI × OpenCode × DeepSeek Harness｜24 篇主笔记｜48 项设计决策｜70 段原文源码**

本版不以变量解释为主线，而从真实问题、约束和简单替代方案出发：为什么需要当前结构，不这样做会怎样，付出了哪些代价，哪些前提改变后应选择另一种实现。每篇随后保留核心源码与逐段讲解，所有引用固定版本。

## 学习目录

| 专题 | Codex CLI | OpenCode | DSH |
|---|---|---|---|
| 01 Agent Loop | [输入接纳与请求快照](codex/01-agent-loop.md) | [运行协调与丢失唤醒](opencode/01-agent-loop.md) | [信息注入与工作授权](dsh/01-agent-loop.md) |
| 02 Context / Session | [摘要与确定性重建](codex/02-context-session.md) | [准备前提与上下文失效](opencode/02-context-session.md) | [事件视图与缓存剩余成本](dsh/02-context-session.md) |
| 03 Tool / Sandbox | [取消结算、并发与隔离](codex/03-tools-sandbox.md) | [工具捕获与结果表示](opencode/03-tools-sandbox.md) | [顺序提交与结果积压](dsh/03-tools-sandbox.md) |
| 04 LLM / Streaming | [连接、续接与认证归属](codex/04-llm-streaming.md) | [已提交状态与重试预算](opencode/04-llm-streaming.md) | [尝试结算与在途丢失窗口](dsh/04-llm-streaming.md) |
| 05 Extension / Plugin | [类型化贡献与准入](codex/05-extension-architecture.md) | [贡献重放与插件代际](opencode/05-extension-architecture.md) | [能力世界与迟到资源](dsh/05-extension-architecture.md) |
| 06 Task / Multi-Agent | [身份、驻留和父归属](codex/06-task-orchestration.md) | [接纳、执行与交付](opencode/06-task-orchestration.md) | [目标、授权与版本围栏](dsh/06-task-orchestration.md) |
| 07 Persistence / Reliability | [ACK、检查点与恢复资格](codex/07-persistence-reliability.md) | [write-ahead 意图与停止语义](opencode/07-persistence-reliability.md) | [Handle 所有权与副作用前 Flush](dsh/07-persistence-reliability.md) |
| 08 Observability / Evaluation | [原始证据与离线解释](codex/08-observability-evaluation.md) | [独立故障域与事件交付](opencode/08-observability-evaluation.md) | [脱敏、交接游标与缺口](dsh/08-observability-evaluation.md) |

**研究入口：** [48 项决策索引](DESIGN_INDEX.md) · [研究方法与证据等级](RESEARCH_METHOD.md) · [新增直接证据](RESEARCH_EVIDENCE.md) · [横向研究结论](RESEARCH_FINDINGS.md) · [机制实验与验证矩阵](RESEARCH_EXPERIMENTS.md) · [本轮修正记录](RESEARCH_CHANGELOG.md)

原源码索引与学习路线仍在 [SOURCES.md](SOURCES.md)、[LABS.md](LABS.md)，旧版架构比较与路径差异仍可查 [COMPARISON.md](COMPARISON.md)、[ERRATA.md](ERRATA.md)。设计层的新结论和边界以本轮研究记录为准，原始版本保留在 Git 历史中。

## 每篇的组织方式

先给一个不需要复杂架构的简单实现，再说明新增需求制造了什么矛盾；深入两项带编号的设计决策，比较候选方案与反事实；讨论代价、适用条件和反证；最后回到固定源码和实验。候选方案除明确引自作者记录外，均是研究比较，不冒充维护者实际讨论史。

70 段源码从上一版完整保留，代码、缩进、定位范围与顺序由构建器检查。研究源稿位于 `research/decisions/`，它们用于生成 24 篇主笔记，不是额外 24 篇新的源码课程。修改设计论证后运行构建器，避免主笔记与源稿不同步。

## 固定基线

| 项目 | 完整 Commit |
|---|---|
| openai/codex | `a9b0815167c27ab13719dd12d13b63e02b70d221` |
| anomalyco/opencode | `60a212c0769acd96b446acbadeb790486830f91d` |
| deepseek-ai/deepseek-harness | `d743267388641bc76f17c45ce8b4c231aed1d32c` |

研究日期：2026-10-12；上一版笔记基线：`69577b8d1dc34b052090b43206faa9fcd2c597b2`。源码基线不滚动，避免把版本变化与设计解释混为一谈。它们是研究快照，不是推荐安装版本，也未验证发行版二进制等价。机器记录见 [source-lock.json](source-lock.json)。

## 实际验证的四个层次

| 层次 | 方法 | 不证明什么 |
|---|---|---|
| 原文源码一致性 | `verify_notes.py` 联网逐行匹配 70 段、检查链接与 SHA | 不证明设计动机与全部运行行为 |
| 设计版生成完整性 | `build_design_edition.py --check` 检查 24 篇、48 决策、原文保留与生成文本一致 | 不会自动判定论证正确 |
| 自建机制实验 | 22 项确定性 Python 教学模型 | 不是三个上游 Agent 的测试或性能基准 |
| 文档工具测试 | 原核验器 7 项＋构建器 4 项 | 不验证模型、数据库、OS 沙箱 |

实际结果以 [validation](validation/README.md) 内机器报告和 [GitHub Actions](https://github.com/solstice621/Agent-Learning-Notes/actions) 为准。主笔记里的上游实验仍是 **NOT RUN**。本轮没有编译上游 Agent、发起真实模型请求、测量端到端性能、执行沙箱攻击测试或验证多节点接管。

```bash
# 需要包含上一版基线的本仓库 Git 历史；浅克隆需先获取该历史。
python3 scripts/build_design_edition.py
python3 scripts/build_design_edition.py --check
python3 -m unittest discover -s tests -v
python3 scripts/run_mechanism_models.py --report /tmp/mechanism-models.json
python3 scripts/verify_notes.py --report /tmp/source-excerpts.json
```

在线匹配失败必须报告失败；`--structure-only` 只检查结构，不能称为源码验证通过。CI 的长期校验工作流仅有读取权限。

## 面向 Agent Infrastructure 的学习目标

读完以后应能脱离函数名，解释要解决的故障窗口、状态归属、可重做范围、授权、资源预算和交付保证；还应能判断什么时候不需要复制这些复杂设计。推荐先横向读 01/03/04，再读 02/07，最后研究 05/06/08。

源码按原许可保留归属，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本项目不是上游官方文档，不保存私人会话、客户代码、凭证或原始执行轨迹。
