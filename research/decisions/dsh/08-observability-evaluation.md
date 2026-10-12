# DSH 08｜为什么遥测游标不是送达回执，事件隔离也可能留下永久缺口？

## 1. 问题：观测不能拖死主任务，但数据消费者又想要完整账本

遥测想采集规范 Session facts，导出系统却可能慢、失败或因脱敏政策拒绝数据。若错误直接传播，诊断系统会破坏 Agent；若完全吞掉，又会让消费者误把残缺数据当完整运行记录。

当前 coordinator clone 事件副本，经 redaction waterfall，调用 backend.emit，再推进 handoff cursor；同步异常被 contain 捕获。sink 契约要求 emit 不阻塞，handoff 明确不等于 delivered。[F1][D1]

## 2. 决策 D08-D1：为什么克隆与脱敏发生在导出副本，而不是原始 Session？

规范日志用于上下文重建与恢复；对外观测有另外的访问/隐私政策。若为了遥测脱敏直接改原日志，模型历史和工具证据会改变；若完全不拷贝，后端异步序列化又可能看到意外变化。

| 方案 | 好处 | 代价或反例 |
|---|---|---|
| 直接导出原始对象 | 少一次复制 | 身份与权限混合，后端获得完整事实 |
| 在 canonical log 上直接脱敏 | 全局只剩一份内容 | 恢复/模型重建丢信息，改变真实历史 |
| 导出副本＋独立 redaction | 明确外发边界，不影响本地事实 | clone CPU/内存与脱敏规则维护 |
| 独立最小指标而非完整事件 | 风险和成本较低 | 无法完整重建失败细节 |

契约本身不附通用脱敏规则；没有 listener 时是 pass-through。[D1] 因此“经过 redact()”不是“已安全脱敏”的证明；还要检查具体 deployment 装配、允许字段、历史采集授权和外发模式。includeHistory 也不是授权本身。

这里区分了 privacy policy 与 event truth，不等于所有场景都必须永久保留敏感原始日志。本地保留、删除和访问权限仍需单独治理。

## 3. 决策 D08-D2：为什么 best-effort cursor 不能当连续确认水位？

当前 deliver 先 emit，再按 event.seq 设置 handoffCursor；captureSession 从 cursor+1 读取，单事件失败由 contain 隔离，后续事件仍继续。[F1] 文档明确允许丢失或重复，ledger 接收端按身份去重；ops 并不伪装成精确账本。[D1]

**从代码推导的具体缺口：** seq=5 在脱敏或 emit 时抛错，被 contain 隔离；seq=6 成功交接，cursor 到 6；下一次从 7 读取不会再补 5。因此这个 cursor 是已交接的高水位，不是“所有 <=cursor 都送达”的证明。若后端内部还有队列，emit 返回也不表示远端 ACK。

这不应自动称为 bug：它符合 best-effort 与不阻塞其他记录的契约。若消费者想计费、精确训练样本或审计，则需要另一种可靠协议：durable outbox、逐项 ACK/连续水位、缺口重试、去重与背压。加一个重试装饰器不能消除进程丢失与游标跳过的全部窗口。

**权衡：** 把所有失败记录堵在队首，能保留连续性，却让一条不可编码/不能脱敏的记录阻塞后续；跳过能维护主任务与后续观测可用，但必须承认缺口；dead-letter 加显式缺口事实是另一个选择，会增加政策和存储复杂度。

## 4. 为什么 ledger、ops、live stream 不能直接相加？

ledger 对应规范 Session 事件；ops 是 agent-error/shutdown 等运行信号；live assistant-stream 是即时呈现。[D1] 把三者无条件合并成 token 数、错误数或任务数，可能重复统计同一事实，也可能把没持久化的在途 delta 当恢复证据。

handoffCursor 使用 Session 对象 WeakMap，在同一对象被 telemetry 重载重新接管时有帮助；新对象重放则可能重复。[F1] 接收端应使用稳定 ledger identity，而非进程内对象地址。ops 没有相同去重身份时，只能按其明示的信号语义消费。

缺失 usage 不能默认为 0；成功交接不能默认为成功送达；无错误遥测不能默认为无错误执行。这三条直接关系到评测归因可信度。

## 5. 验证、替代与读后结论

本仓库机制实验制造一项 emit 失败后下一项成功，检查高水位跳过缺口；它不运行 DSH telemetry，也不保证任何后端的队列策略。

**上游实验待运行：** 本地 fake sink 抛错/缓慢/重复接收；逐项核对 canonical log 未变、失败记录未外发、后续记录是否继续、重新 capture 从何处开始；卸载时 shutdown 失败不应破坏其他清理。不开真实外发端点。

如果目标是聚合健康监控，best-effort 隔离往往合理；如果是合规审计或费用账本，必须另建更强确认通路。可观察性的首要能力，是告诉读者哪些数据可以信到什么程度，而不是把所有记录包装成一条看似完整的轨迹。

[F1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/coordinator.ts#L1-L300
[D1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/session-telemetry.md
