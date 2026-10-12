# DSH 04｜为什么每次模型尝试只结算一个事件，却仍保存完整流证据？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

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

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：preparedCall 决定本次路由能力

源码：[`agent-loop/src/agent.ts`，L400–L541](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L400-L541)。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L400-L541 -->
```ts
      const { config, preparedCall } = await this.prepareRequest(turn, step, signal)
      const currentContext = this.loopCtx.systemPrompt.refreshContext(assembly, assembleContextFor(this, signal))
      const sections = renderContextSections(currentContext)
      const context = this.runtimeContext.project(joinContextSections(sections), sections)
      signal.throwIfAborted()
      const startsRequestSeries = firstAttempt && decision.startsRequestSeries === true
      const commits = this.systemPrompt.project(renderedPrompt, {
        inHistory: preparedCall?.systemPromptUpdate === 'in-history',
        startsSeries: startsRequestSeries
          || this.requestSurfaceGeneration !== this.session.surface.contentGeneration
          || (preparedCall?.toolUpdate === undefined && this.toolsChanged(assembly.tools)),
      })
```

#### 逐段讲解

prepareRequest 是 await 边界，之后刷新运行时 context 并再次检查取消。preparedCall 的能力决定 system prompt 如何投影，而不是照着上一次 request/context 的历史元数据猜当前 route。

startsSeries 由显式要求、Surface generation 改变、工具更新能力与当前工具变化共同决定。不能把 resume 或 model 名称变化简单等同于“必定新 series”；实际规则要看完整调用点。

**设计分析：** 将能力判断绑定到准备好的调用，减少“按 A adapter 能力造请求，却由 B 执行”的错位。该分析不代替对 LlmRuntime 注册竞态的完整审计。

### 3. 核心源码 B：同一个绑定调用产生本次流

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L400-L541 -->
```ts
        const stream = preparedCall?.stream(request) ?? this.loopCtx.llm.stream(request)
        signal.throwIfAborted()
        live.start()
        started = true
        for await (const chunk of stream) {
          signal.throwIfAborted()
          live.push(chunk)
        }
        signal.throwIfAborted()
```

优先使用 preparedCall.stream，缺省才走通用 runtime；创建流、逐 chunk 消费、流结束都检查取消。live 是本次 AssistantStreamAttempt，负责承接实时与最终结算，而不是直接把每个 chunk 当作独立的成功消息。

`started` 区分尚未开始尝试与已经开始后失败。外层 catch 会据此决定是否需要结算。这里检查 AbortSignal 不意味着 provider 已经可靠停止后台网络操作，adapter 自身仍需履行取消契约。

### 4. 核心源码 C：失败尝试先记录，再由策略决定重试

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L400-L541 -->
```ts
        const finish = live.finish
        if (finish.kind === 'error' || finish.kind === 'aborted') {
          live.settle(
            'assistant/attempt',
            () => this.session.append('assistant/attempt', { turn, step, stream: live.stream }).seq,
          )
          const action = await this.dispatch.waterfall(
            'agent/request-error', {
              turn,
              step,
              provider: request.provider,
              failure: finish.failure,
              retryPolicy: preparedCall?.retryPolicy,
              signal,
            },
            () => Promise.resolve<RequestErrorAction>(undefined),
          )
          signal.throwIfAborted()
          if (action?.kind !== 'retry') {
            throw new LlmError(finish.failure.message, finish.failure.code, finish.failure)
          }
          continue
        }
```

#### 逐段讲解

失败被结算为 assistant/attempt，保存本次 stream，但不是成功 assistant/message。后者才参与正常模型历史；具体派生规则见 [02](02-context-session.md)。

request-error waterfall 接收 provider-neutral failure、当前路由 retryPolicy 和 signal。没有 handler 返回 retry，就抛结构化 LlmError；返回 retry 则在 Step 的 attempt 循环内继续，而不是重新接纳用户输入。

firstAttempt 在同函数中只让原始 accepted user batch 入历史一次。取消始终有再次检查，不应因某插件要求 retry 而忽略用户停止。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/dsh/04-llm-streaming.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
