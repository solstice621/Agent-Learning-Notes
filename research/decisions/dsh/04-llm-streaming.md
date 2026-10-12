# DSH 04｜为什么每次模型尝试只结算一个事件，却仍保存完整流证据？

## 1. 有直接决策记录的矛盾

DSH 的已实施决策记录说明：逐 token 顶层 assistant/chunk 事件保留顺序、时间、usage 和失败前缀，但在持久化、遥测、索引、传输和客户端反复复制 event envelope；只保存成功后的完整文本虽能减小事件量，却丢掉失败输出与精确流证据。[A1]

所以问题不是“流式还是非流式”，而是**实时展示、规范事件数量和持久化证据应如何分层**。

## 2. 决策 D04-D1：为什么把 timed stream 嵌入一次 Attempt 的 settlement？

官方选择 assistant/message 或 log-only assistant/attempt，内部携带 compact timed stream；连续 delta 压缩封装但不合并原 delta 边界。live presentation 使用进程本地 stream，完整结算先写日志再发布 committed end。[A1][F1]

| 官方记录讨论的候选 | 不足或取舍 |
|---|---|
| 只保存成功 assembled message | 失败前缀、时间、usage 与 replay 证据丢失 |
| 保留顶层 chunks，只压物理 JSONL 行 | 字节可少，但逻辑事件与消费者处理量仍随 chunks 增长 |
| stream 放 sidecar | message 与证据分属持久化所有者，协调更复杂 |
| 每 Attempt 一个携带 stream 的 settlement | 降低顶层事件基数，保留已结算流；代价是结算前的丢失窗口 |

这里不能写“日志大小变成只随 attempt 数增长”：顶层事件数量变少，不代表 stream payload 的字节与 chunk 数无关。完整证据仍需要空间。减少 envelope 与消费者对象数量和减少语义内容是两件事。

**最重要的代价有作者直接承认：** 硬进程/宿主丢失发生在 settlement 前，整个在途 stream 可以没有 durable evidence；live stream 不是 WAL。[A1] 这不是实现忘记保存，而是避免第二个持久化所有者的一项明确权衡。

## 3. 决策 D04-D2：为什么能力查询与实际模型调用要绑定？

默认 Loop 先 prepareRequest，使用 preparedCall 的 system/tool update 能力构造历史，再通过该对象 stream；firstAttempt 控制输入只接纳一次。[F1]

**反事实：** 先查询 provider A 支持 in-history prompt 更新，随后插件切换为 B，而实际执行才重新按名字解析 provider。请求按 A 的协议形成却交给 B，会造成能力/执行错位。Prepared Call 把本次路由能力、配置与执行绑定，而不是用“最新路由”覆盖正在准备的请求。

替代方案包括全程锁 registry、在每一步重新校验版本、或禁止运行中路由改变。绑定对象减少反复查找与跨 await 错位，但持有对象会延长旧资源生命；全局锁更简单却限制并发；禁止热更新适合短命应用。哪些能力最终真正绑定，仍要读 LlmRuntime，不应从命名推导全部后端保证。

## 4. 为什么 attempt 不能冒充一条模型可见消息？

失败前输出、重试使用量和 provider replayState 对诊断很重要，但不应不加区分地拼进下一模型对话。assistant/attempt 是日志事实；assistant/message 才按对应语义加入 Surface。[A1][F1] 取消时有可见前缀又可能记录 interrupted message，必须明确它与未发表尝试的区别。

**推导：** 训练/评测轨迹应同时知道“模型生成过什么”与“后续模型实际看到了什么”；如果把所有 raw failure 拼回 messages，会创造一个真实运行中没有发生过的上下文。

格式基数改变还需要重映射引用和 fork cut。官方决策拒绝把被删除 chunk 的引用随意重定向到 settlement，因为二者不是同一个事实。[A1] 这提醒我们：序列号不是无语义的行号，迁移不能只重新编号。

## 5. 验证与选择条件

**上游实验待运行：** accumulator/expand round-trip 逐项核对 chunk 值、时间和边界；在 live chunk 后 settlement 前结束进程，验证声明的丢失窗口；在已结算失败后恢复，检查 attempt 保留但不污染模型历史。不得把 UI 曾展示过文字当作持久化成功。

如果业务要求每个已展示 token 都可在硬故障后恢复，应选择更细检查点或可靠实时日志，并接受写放大；若只需要最终回答，完整 timed stream 又可能过重。没有一种事件粒度适合所有持久性与诊断目标。

本篇要学的是用明确丢失边界换取事件处理成本，而不是以“更可扩展”掩盖牺牲；以及为什么绑定路由和区分 attempts，是请求可解释性的组成部分。

[A1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/.agents/notes/implemented/architecture/2026-09-01-v2-embedded-assistant-streams.md
[F1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L390-L550
