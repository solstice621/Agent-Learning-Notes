# OpenCode 04｜模型通信：断流续写与重试边界

Agent 已经调用工具写好了一个测试文件，接着模型连接断了。若删掉这轮记录、原样重发任务，模型可能再次写文件；若保留半截工具参数并执行，又可能执行一个它还没说完整的命令。

**是否重试，既要看错误能否恢复，也要看这次尝试已经留下了什么。**

OpenCode 把这件事放在 Attempt 中：读取模型事件、处理工具、保存结果，最后向 Runner 报告下一步。Runner 决定等待多久、使用哪个消息 ID，以及怎样组装后续请求。

<!-- decision: O04-D1 | 断线前已经有内容，接下来应重试还是续写？ -->
## 部分输出后的重试与续写

对策略允许恢复的故障，尚未开始记录输出时，可以沿用原来的 assistant 消息 ID 重试。源码中的这个分支很短：

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L204-L209 -->
```ts
        // 笔记：只有策略允许恢复、且尚未开始记录任何输出时，才进入原消息上的重试。
        if (llmFailure && llmError && retry?.retry && !recorded.outputStarted) {
          // Retry state projects onto the existing assistant, even before it has produced output.
          yield* publisher.startAssistant()
          // 笔记：Attempt 只报告重试结果，等待和下一次请求仍由外层 Runner 安排。
          return Outcome.Retry({ error: llmError, decision: retry })
        }
        if (llmError) yield* publisher.failAssistant(llmError)
```

`outputStarted` 比“屏幕上是否出现了字”更早：文本开始、推理开始、工具输入开始，都可能把它设为真。只有创建了步骤记录，不一定算输出已经开始。

一旦已经留下内容，Attempt 会先结算工具及失败状态，再返回 `Continue`。Runner 保存“接着完成，别重复已完成内容”的续写提示，并创建新的 assistant 消息。旧回答不会被抹掉。

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L278-L286 -->
```ts
          Continue: Effect.fnUntraced(function* (outcome) {
            // 笔记：部分输出后的续写也遵守退避策略，避免断流后立刻再次冲击服务商。
            yield* retry.wait({
              decision: outcome.decision,
              error: outcome.error,
              assistantMessageID,
            })
            // 笔记：把续写提示存进历史，再换新的 assistant ID；已有回答与工具结果得以保留。
            yield* bus.publish(SessionEvent.Synthetic, { sessionID, text: CONTINUE_AFTER_INCOMPLETE_STREAM })
            assistantMessageID = SessionMessage.ID.create()
          }),
```

所以写文件后断流的路径是：保存工具结果 → 保留失败的这一轮 → 把历史和续写提示交给模型。[上游测试](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-runner.test.ts#L5779-L5813)检查了已完成的本地工具只执行一次，下一请求同时包含调用、结果和续写提示。

参数没收完整的本地调用会记录为未执行；服务商代为执行的调用若缺结果，则记录结果缺失，不能自行在本地补跑。这个区别让错误记录更诚实。它仍不能保证外部副作用绝不重复，尤其是进程在操作成功与结果落库之间崩溃时。

<!-- decision: O04-D2 | 设置重试次数，为什么还不能算出最长等待时间？ -->
## 重试策略与插件调整范围

固定版本的一般策略允许最多十次重试；间隔按 2、4、8、10 秒等增长，再加随机抖动。服务商建议的等待时间可能更长。超时另有默认限制，因为每次超时本身已耗费时间。

关键顺序是：先计算默认决定，再交给插件，最后读取决定。

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/retry.ts#L78-L90 -->
```ts
        const event: PluginHooks.Domains["session"]["retry"] = {
          sessionID,
          agent: input.agent,
          model: input.model,
          error: input.error,
          attempt,
          // 笔记：先按故障分类和超时次数给出默认决定；此时它还不是最终决定。
          decision: input.retry && timeouts <= MAX_TIMEOUT_RETRIES ? { retry: true, delay } : { retry: false },
        }
        // 笔记：插件可修改同一个事件里的 decision，因此默认超时限制不等于不可改的硬上限。
        yield* input.hook(event)
        if (!event.decision.retry) return event.decision
        // 笔记：只校验最终延迟是有限非负数；这里没有给插件延迟另设最长等待时间。
        const normalized =
          Number.isFinite(event.decision.delay) && event.decision.delay >= 0 ? Math.ceil(event.decision.delay) : delay
        return { retry: true as const, attempt, delay: normalized }
```

因此“超时最多重试三次”是默认政策，插件能改这次决定和延迟。但整体次数调度用尽时，会在调用插件之前直接返回，不能反过来说插件能突破所有上限。

只做固定重试容易理解，却难适应不同服务商；提供扩展点更灵活，也意味着不能把默认退避总和写成任务最长耗时。真实耗时还包括每次请求、工具执行及插件修改。产品若要严格截止时间，需要另设不可放宽的总预算。

**自检：** 屏幕还没有字，但已经收到 `tool-input-start`，随后断流，能把这一轮当成“什么都没发生”吗？

<details>
<summary>参考答案</summary>

不能。工具输入已经开始记录。系统需结算未完成调用；若允许恢复，应带着已有历史继续。该调用尚未凑齐参数，也不能直接执行。

</details>

本篇阅读了流事件发布、Attempt、重试策略和对应测试，未运行上游测试。源码及测试采用十次一般重试；同版本 Session 文档仍写四次，本文按实现说明。
