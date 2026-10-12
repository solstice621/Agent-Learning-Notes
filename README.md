# Agent Learning Notes｜源码节选与逐段讲解

**Codex CLI × OpenCode × DeepSeek Harness（DSH）｜24 篇专题｜源码导读版**

这套中文笔记面向 Agent Harness / Runtime / Infrastructure 学习。每篇直接展示官方仓库的核心源码，解释输入输出、状态归属、调用顺序、错误与取消边界，再给出设计分析和待运行实验。不是仅列源码路径，也不是把伪代码当作原实现。

## 学习目录

| 专题 | 学习顺序 | Codex CLI | OpenCode | DSH |
|---|---|---|---|---|
| 01 Agent Loop | P0 | [输入接纳与请求快照](codex/01-agent-loop.md) | [Execution / Runner / Step / Attempt](opencode/01-agent-loop.md) | [输入通道与失败收尾](dsh/01-agent-loop.md) |
| 02 Context / Session | P0 | [压缩后的历史重建](codex/02-context-session.md) | [准备、提升与加载](opencode/02-context-session.md) | [事件提交与派生历史](dsh/02-context-session.md) |
| 03 Tool / Sandbox | P0 | [许可、执行门与取消](codex/03-tools-sandbox.md) | [调用发布与 Fiber 结算](opencode/03-tools-sandbox.md) | [滚动池与顺序提交](dsh/03-tools-sandbox.md) |
| 04 LLM / Streaming | P0 | [连接与增量续接](codex/04-llm-streaming.md) | [重试预算与插件覆盖](opencode/04-llm-streaming.md) | [绑定路由与尝试结算](dsh/04-llm-streaming.md) |
| 05 Extension / Plugin | P1 | [类型化贡献与准入](codex/05-extension-architecture.md) | [代际、失败更新与卸载](opencode/05-extension-architecture.md) | [卸载收敛与迟到资源](dsh/05-extension-architecture.md) |
| 06 Task / Multi-Agent | P1 | [身份、驻留与恢复归属](codex/06-task-orchestration.md) | [Prompt 与 Job 分离](opencode/06-task-orchestration.md) | [Goal、授权与检查点](dsh/06-task-orchestration.md) |
| 07 Persistence / Reliability | P1 | [提交策略与恢复资格](codex/07-persistence-reliability.md) | [执行声明与停止意图](opencode/07-persistence-reliability.md) | [模型/工具前的 Flush](dsh/07-persistence-reliability.md) |
| 08 Observability / Evaluation | P2 | [观测边界与并发测试](codex/08-observability-evaluation.md) | [事件扇出与慢订阅者](opencode/08-observability-evaluation.md) | [脱敏、交接与错误隔离](dsh/08-observability-evaluation.md) |

P0/P1/P2 表示学习顺序，不是生产环境的重要性排名。建议先横向读三个项目的 01，再读 03/04/02，之后深入 07/05/06/08。

**配套阅读：** [源码索引](SOURCES.md) · [横向比较](COMPARISON.md) · [实验路线](LABS.md) · [版本差异与证据边界](ERRATA.md) · [第三方许可](THIRD_PARTY_NOTICES.md)

## 每篇怎样阅读

每篇包含 2–4 段带 `rust` 或 `ts` 语法高亮的原文代码。每段上方都有完整 Commit、文件和包含该节选的行号定位链接；HTML `source` 标记供机器核验。代码块保留原缩进和原注释，解释位于块外，不向源码内插入自编注释。

节选可能从完整函数中间开始，或在一个分支中间结束；它们用于阅读，不是可独立编译的程序。省略部分在块外说明，不用自编省略号替代原文。定位范围可能比节选稍宽；核验器会输出实际匹配的起止行。

讲解重点是：这个状态由谁持有、为什么此处等待/提交、取消到达后怎么办、失败意味着什么。标为“分析”的内容是基于代码的推导，不冒充作者的设计原话。源码结构或接口声明也不自动证明某个后端的全部运行行为。

## 固定研究基线

| 官方仓库 | 研究分支 | 完整 Commit |
|---|---|---|
| [openai/codex](https://github.com/openai/codex) | main | `a9b0815167c27ab13719dd12d13b63e02b70d221` |
| [anomalyco/opencode](https://github.com/anomalyco/opencode) | dev | `60a212c0769acd96b446acbadeb790486830f91d` |
| [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) | master | `d743267388641bc76f17c45ce8b4c231aed1d32c` |

研究日期：2026-10-12。机器可读基线见 [source-lock.json](source-lock.json)。这些是研究快照，不是推荐安装版本；没有验证它们与某个发行版二进制完全一致。更新版本不能只替换链接中的 SHA，必须重新检查代码与解释。

## 源码核验

仓库附带仅使用 Python 标准库的检查器。它检查 24 篇是否齐全、每篇是否至少有两段源码、本地导航是否存在、源码是否使用锁定 SHA，以及代码块是否逐行原样出现在对应官方文件定位范围内。只读取源码，不执行上游代码，不使用凭证。

```bash
python3 -m unittest discover -s tests -v
python3 scripts/verify_notes.py --report /tmp/agent-notes-validation.json
```

离线仅检查目录、链接和引用结构：

```bash
python3 scripts/verify_notes.py --structure-only
```

`STRUCTURE_ONLY` 不表示源码一致性已验证。联网检查失败、找不到源码、节选改写或定位越界都会失败，不把无法访问误记为通过。GitHub Actions 使用同一脚本，状态见仓库 Actions；单元测试通过不等于整套笔记已经通过在线比对。

## 实际验证范围

本套完成静态源码分析与导读。**没有编译或运行三个上游 Agent，没有执行上游单元/集成测试、真实模型请求、性能评测或 OS 沙箱安全测试。** 各篇实验均待运行。

源码逐字一致性检查只证明节选和来源匹配，不证明讲解覆盖全部分支或运行时正确性。涉及数据库原子性、provider 取消、沙箱 enforcement、分布式接管等结论，仍需继续阅读实现与做实验。

本仓库不存私人会话、客户代码、凭证或原始运行 trace。实验使用合成输入和临时工作区；公开证据先脱敏。引用源码按原许可保留归属，本项目不是三个上游项目的官方文档。
