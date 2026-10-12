# 目录

* [关于这套笔记](README.md)
* [Agent 架构导览](START_HERE.md)

## Codex

* [00 · 整体架构与任务执行链](codex/00-architecture.md)
* [01 · 执行循环：输入接纳与请求快照](codex/01-agent-loop.md)
* [02 · 上下文管理：历史压缩与状态恢复](codex/02-context-session.md)
* [03 · 工具执行：取消收尾与权限控制](codex/03-tools-sandbox.md)
* [04 · 模型通信：连接复用与增量请求](codex/04-llm-streaming.md)
* [05 · 扩展架构：职责划分与关闭流程](codex/05-extension-architecture.md)
* [06 · 子 Agent 编排：按需加载与归属校验](codex/06-task-orchestration.md)
* [07 · 任务恢复：关闭交接与恢复条件](codex/07-persistence-reliability.md)
* [08 · 可观测性：执行追踪与诊断记录](codex/08-observability-evaluation.md)

## OpenCode

* [00 · 整体架构与任务执行链](opencode/00-architecture.md)
* [01 · 执行循环：持久输入与唤醒协调](opencode/01-agent-loop.md)
* [02 · 上下文管理：指令准备与历史裁剪](opencode/02-context-session.md)
* [03 · 工具执行：实现快照与结果表示](opencode/03-tools-sandbox.md)
* [04 · 模型通信：断流续写与重试边界](opencode/04-llm-streaming.md)
* [05 · 插件管理：状态重算与更新失败处理](opencode/05-extension-architecture.md)
* [06 · 子 Agent 编排：输入提交与后台托管](opencode/06-task-orchestration.md)
* [07 · 任务恢复：执行标记与重启接管](opencode/07-persistence-reliability.md)
* [08 · 事件推送：订阅者队列与积压隔离](opencode/08-observability-evaluation.md)

## DeepSeek Harness

* [00 · 整体架构与任务执行链](dsh/00-architecture.md)
* [01 · 执行循环：输入模式与驱动契约](dsh/01-agent-loop.md)
* [02 · 上下文管理：事件日志与模型视图](dsh/02-context-session.md)
* [03 · 工具调度：并行执行与顺序提交](dsh/03-tools-sandbox.md)
* [04 · 模型通信：流式输出与尝试记录](dsh/04-llm-streaming.md)
* [05 · 扩展架构：执行环境与资源清理](dsh/05-extension-architecture.md)
* [06 · 目标编排：自动续跑与版本校验](dsh/06-task-orchestration.md)
* [07 · 持久化：会话写入权与执行前检查点](dsh/07-persistence-reliability.md)
* [08 · 可观测性：遥测副本与交付边界](dsh/08-observability-evaluation.md)

## 机制对比与练习

* [三项目执行机制对比](COMPARISON.md)
* [Agent 设计要点](RESEARCH_FINDINGS.md)
* [48 个问题索引](DESIGN_INDEX.md)
* [阅读路线与综合练习](LABS.md)
* [教学模型与实验](RESEARCH_EXPERIMENTS.md)

## 来源与研究记录

* [研究方法](RESEARCH_METHOD.md)
* [源码地图](SOURCES.md)
* [重新研究后的修正](RESEARCH_EVIDENCE.md)
* [源码重读记录](research/reread/README.md)
  * [Codex 架构核对](research/reread/codex-architecture.md)
  * [Codex 01–04](research/reread/codex-01-04.md)
  * [Codex 05–08](research/reread/codex-05-08.md)
  * [OpenCode 架构核对](research/reread/opencode-architecture.md)
  * [OpenCode 01–04](research/reread/opencode-01-04.md)
  * [OpenCode 05–08](research/reread/opencode-05-08.md)
  * [DSH 架构核对](research/reread/dsh-architecture.md)
  * [DSH 01–04](research/reread/dsh-01-04.md)
  * [DSH 05–08](research/reread/dsh-05-08.md)
* [验证报告说明](validation/README.md)
* [勘误](ERRATA.md)
* [修订记录](RESEARCH_CHANGELOG.md)
* [源码归属与许可](THIRD_PARTY_NOTICES.md)
* [本地阅读与构建](LOCAL_BOOK.md)
