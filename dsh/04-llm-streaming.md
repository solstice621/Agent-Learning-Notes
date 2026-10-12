# DSH 04｜LLM / Streaming：绑定路由与一次尝试的结算

[总目录](../README.md) · P0 · 对照：[Codex](../codex/04-llm-streaming.md) / [OpenCode](../opencode/04-llm-streaming.md)

**固定源码：** `deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。以下分析默认 Loop 的模型集成消费方，不宣称已逐个审计 provider adapter。原文节选，未调用真实模型。

## 1. 本篇的问题

为什么先确定 adapter 能力，再提交系统提示？为什么失败的模型尝试要记录，但不一定成为模型可见回答？为什么重试可以留在同一个 Step 内？

## 2. 核心源码 A：preparedCall 决定本次路由能力

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

### 逐段讲解

prepareRequest 是 await 边界，之后刷新运行时 context 并再次检查取消。preparedCall 的能力决定 system prompt 如何投影，而不是照着上一次 request/context 的历史元数据猜当前 route。

startsSeries 由显式要求、Surface generation 改变、工具更新能力与当前工具变化共同决定。不能把 resume 或 model 名称变化简单等同于“必定新 series”；实际规则要看完整调用点。

**设计分析：** 将能力判断绑定到准备好的调用，减少“按 A adapter 能力造请求，却由 B 执行”的错位。该分析不代替对 LlmRuntime 注册竞态的完整审计。

## 3. 核心源码 B：同一个绑定调用产生本次流

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

## 4. 核心源码 C：失败尝试先记录，再由策略决定重试

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

### 逐段讲解

失败被结算为 assistant/attempt，保存本次 stream，但不是成功 assistant/message。后者才参与正常模型历史；具体派生规则见 [02](02-context-session.md)。

request-error waterfall 接收 provider-neutral failure、当前路由 retryPolicy 和 signal。没有 handler 返回 retry，就抛结构化 LlmError；返回 retry 则在 Step 的 attempt 循环内继续，而不是重新接纳用户输入。

firstAttempt 在同函数中只让原始 accepted user batch 入历史一次。取消始终有再次检查，不应因某插件要求 retry 而忽略用户停止。

## 5. 部分输出与流记录

同函数的异常分支在取消且已有可见前缀时可结算 interrupted assistant/message；无可见消息则记录 attempt。硬进程在 settlement 前退出，不保证已展示的每个 delta 都已经持久化。

[流协议文档](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/llm-streaming.md) 定义 block index、原始 arguments、usage 与 compact timed stream。流封装的无损压缩与改变模型上下文的摘要压缩是不同事情，不能都用“token 减少”衡量正确性。

## 6. 实验与验收

mock route 在 request preparation 时暂停，改变能力或取消后再释放，检查已提交的 system/user 内容；mock stream 分别在无输出、部分文字、完整工具调用后失败，核对 attempt、message、retry 和实际工具次数。

验收图包含 prepared route → 请求构建 → raw stream → live frames → durable settlement → derived history，注明每次转换的所有者。未运行真实请求；原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
