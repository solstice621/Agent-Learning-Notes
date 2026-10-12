# DSH 06｜为什么 Goal 的完成状态、继续授权和 Round 调度必须分开？

## 1. 一个 while not done 为什么不够？

让模型在每次回答后判断目标是否完成，没完成就再发一次 prompt，是最容易写的长期任务。它没有回答：用户暂停后是否继续、错误时是否自动重试、任务改版后旧回调是否有效、何时刷盘、是否抢占用户输入，以及最多消耗多少资源。

DSH 分出 goal、tool-goal、command-goal 和 goal-round-driver；当前 driver 同时检查 goal phase、activation、round limit、当前 Agent 对象和竞争输入。[D1][F1] 这些不是多余状态，而是不同种类的问题。

## 2. 决策 D06-D1：为什么 active 不等于现在有权继续执行？

业务 goal 未完成可以保持 active，但系统可能因为错误、用户暂停或检查点失败不再 armed。Driver 检查 active＋armed 才安排后续工作；flush 失败会 disarm。[F1]

| 方案 | 优点 | 反例 |
|---|---|---|
| unfinished 就无限继续 | 最简单 | 用户停止/服务故障后仍耗资源 |
| 把暂停等同于目标完成 | 循环容易停止 | 丢失真实未完成状态 |
| 目标状态＋执行授权分离 | 保留目标，同时可撤回继续权 | 多一个状态维度与恢复规则 |
| 外部工作流统一调度 | 配额/持久任务容易集中 | 需要将模型目标转成稳定工作流协议 |

**设计推导：** 自动续跑是一种可撤回的授权，不只是模型提出的建议。completion 状态与“允许继续”的控制面若由同一个布尔值表达，恢复时很容易违背人的停止意图。

maxGoalRounds 是轮数约束，不是 token、工具执行数、单轮耗时或外部费用的总上限。一个 Round 可能包含多个 Step；因此不能把它说成完整预算管理。需要更强控制时，应在不可绕过的资源/工具边界上组合预算，而不是只让 Prompt 写“别运行太久”。

## 3. 决策 D06-D2：为什么需要 revision 与精确 Agent 对象两种身份？

DriverState 以 Agent 对象为 key；currentGoal 和 readyToDrive 确认 registry 中仍是该对象；RoundIdentity 又携带 goalId、revision、round，区分不同目标版本。[F1]

**反事实 A：** goal 被暂停后立即恢复，revision 已改变，但旧取消回调晚到。如果只检查 goalId，它会再次暂停已经恢复的新版本。**反事实 B：** Session ID 相同的新 Agent 已恢复，旧进程内回调仍持有老对象。只检查 ID 又可能修改新生命周期。

revision 与对象身份解决不同维度的“旧工作不能更改新状态”。二者不是互相替代，也不是跨机器 fencing 的现成实现。分布式平台需要可持久、可校验的 owner epoch，而不能把 JavaScript 对象引用发给另一个 Worker。

为什么 flush 后必须重新检查？await 期间用户可能输入、goal 被改、对象已卸载。`needsCheckpoint=false` 不能永久证明此前条件仍成立，代码会在返回后复查 readyAfterCheckpoint。[F1] 这是围绕异步检查点的具体竞争防线，不只是“防并发”四个字。

## 4. 人的输入为何必须与自动 Round 区分？

Driver 为自己安排的消息保留 messageId、queued/claimed/admitted 与取消状态，管理与普通输入的竞争。[F1] 若自动循环总是抢先向队首注入，用户可能永远无法纠正；若取消时清空全部输入，又可能丢掉其他来源的有用信息。

同 Session Goal 与子 Agent 委派也不能混用：前者继续同一个目标历史，后者有独立 activation、能力参数与结果交付方式。Subagent 的 parent/caller delivery 和 dispose 指向确切 activation，说明“调用返回”与“注入父模型”是不同效果。[D2]

## 5. 验证、选型与读后结论

本仓库机制实验展示相同 goalId、旧 revision 与新生命周期之间的过期回调拒绝；只验证抽象身份条件。

**上游实验待运行：** queued round 后暂停并立即恢复；flush 期间插入用户输入；故意让 persistence 失败；在旧 activation 结束后恢复 child，再调用旧 disposer。分别观察授权、目标 phase、输入保留、通知和资源，不只观察最终回答。

若目标只是一次确定性脚本，普通任务队列比 goal domain 简单；若模型需要在同会话自主跨轮工作，又必须可暂停、限制和恢复，这种分离有明确价值。

应学到的是：愿望、授权、调度和执行是四件事。模型说目标未完成，不构成无限继续的许可；框架有 revision，也不等于已经解决所有分布式接管。

[D1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/README.md
[F1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L1-L300
[D2]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/subagent.md
