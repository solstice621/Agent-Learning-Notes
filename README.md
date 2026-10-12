# Agent Learning Notes｜架构与执行机制

这套笔记研究 Codex、OpenCode 和 DeepSeek Harness 的整体架构，以及它们如何接收任务、调用模型、执行工具和恢复工作。每个项目先用一篇架构解析建立模块与调用链地图，再用八篇专题解释具体机制，源码旁附中文注释。

**第一次读，从 [Agent 架构导览](START_HERE.md) 开始，再选一个项目的整体架构篇。** 先看入口、模块职责与一次任务的完整流转，再沿专题进入实现。熟悉一个项目后，再横向比较另外两个。

**[在线阅读网站](https://solstice621.github.io/Agent-Learning-Notes/) · [直接进入架构导览](https://solstice621.github.io/Agent-Learning-Notes/START_HERE.html)**

网站提供目录、中文搜索和流程图，手机和电脑均可阅读。想在本地阅读，参照 [本地 GitBook 阅读说明](LOCAL_BOOK.md)，运行 `npm run book:serve`。

## 研究主题与章节导航

| 你想弄清什么 | Codex | OpenCode | DSH |
|---|---|---|---|
| 系统由哪些模块组成，一次任务如何贯穿它们？ | [00 整体架构](codex/00-architecture.md) | [00 整体架构](opencode/00-architecture.md) | [00 整体架构](dsh/00-architecture.md) |
| 任务正在运行，新消息怎么办？ | [01 输入与循环](codex/01-agent-loop.md) | [01 输入与循环](opencode/01-agent-loop.md) | [01 输入与循环](dsh/01-agent-loop.md) |
| 聊天记录怎样变成模型的上下文？ | [02 上下文](codex/02-context-session.md) | [02 上下文](opencode/02-context-session.md) | [02 上下文](dsh/02-context-session.md) |
| 工具怎样开始、并发和停止？ | [03 工具](codex/03-tools-sandbox.md) | [03 工具](opencode/03-tools-sandbox.md) | [03 工具](dsh/03-tools-sandbox.md) |
| 模型请求、流式输出与后续请求怎样衔接？ | [04 连接与增量请求](codex/04-llm-streaming.md) | [04 断流与重试](opencode/04-llm-streaming.md) | [04 流与尝试记录](dsh/04-llm-streaming.md) |
| 换插件时，旧任务和资源怎么办？ | [05 扩展](codex/05-extension-architecture.md) | [05 扩展](opencode/05-extension-architecture.md) | [05 扩展](dsh/05-extension-architecture.md) |
| 子任务和长期目标由谁负责？ | [06 编排](codex/06-task-orchestration.md) | [06 编排](opencode/06-task-orchestration.md) | [06 编排](dsh/06-task-orchestration.md) |
| 重启以后，系统靠什么继续？ | [07 保存与恢复](codex/07-persistence-reliability.md) | [07 保存与恢复](opencode/07-persistence-reliability.md) | [07 保存与恢复](dsh/07-persistence-reliability.md) |
| 任务出错，怎样找出发生了什么？ | [08 观测](codex/08-observability-evaluation.md) | [08 观测](opencode/08-observability-evaluation.md) | [08 观测](dsh/08-observability-evaluation.md) |

每篇末尾有一道自测及参考答案。读完一组后，可用 [三项目执行机制对比](COMPARISON.md) 整理差异，再做 [阅读与练习](LABS.md) 中的迁移题。想按具体问题检索，查 [48 个问题索引](DESIGN_INDEX.md)。

## 研究范围与版本说明

当前版本包含 **3 篇整体架构 + 24 篇机制专题**。整体架构说明模块如何协作、数据保存在哪里、谁负责执行与收尾；专题继续覆盖原来的 48 个问题。研究依据是三个项目的固定源码，包含入口、调用者、核心实现、相关组件与测试阅读。

代码中的 `// 笔记：` 是本笔记新增的中文注释，其余代码保留上游原文。核验时仅去掉这些显式注释，再与固定源码逐行比较；教学伪代码会单独标明，不混作原文。源码摘录通常不是完整可运行文件。

这轮研究也修正了一些旧解释，例如 Codex 的关闭准入、跨轮连接复用，以及 OpenCode 不同插件更新失败的处理。具体证据见 [重读记录](research/reread/README.md)。

当前成果是源码研究和本仓库的教学模型。上游测试做了阅读，未在本轮运行；没有真实模型质量或性能排名。验证结果见 [验证说明](validation/README.md)。

<details>
<summary>研究来源与维护方式</summary>

- [源码入口](SOURCES.md) · [固定版本](source-lock.json) · [证据方法](RESEARCH_METHOD.md)
- [重要修正](RESEARCH_EVIDENCE.md) · [跨主题理解](RESEARCH_FINDINGS.md) · [修订记录](RESEARCH_CHANGELOG.md)
- [教学模型及验证范围](RESEARCH_EXPERIMENTS.md) · [勘误](ERRATA.md) · [第三方许可](THIRD_PARTY_NOTICES.md)

专题修改 `research/decisions/` 中的源稿；整体架构直接编辑各项目的 `00-architecture.md`。然后运行：

```bash
python3 scripts/build_design_edition.py
python3 scripts/build_design_edition.py --check
python3 -m unittest discover -s tests -v
python3 scripts/verify_notes.py --report /tmp/source-excerpts.json
```

构建器保留源稿中的讲解与代码顺序，不再拼接旧版全文，也不要求克隆旧 Git 历史。源码核验需要网络；离线结构检查使用 `--structure-only`，它不检查源码内容。

</details>
