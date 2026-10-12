# DSH 04｜模型通信：流式输出与尝试记录

模型已经输出半段回答，窗口里看得清清楚楚。此时进程突然退出，重新打开会话，那半段文字却不见了。要理解这种情况，得先区分：文字被展示、尝试被记入日志、日志被保存到磁盘，是三个时刻。

**要点：DSH 实时展示每个片段，等一次模型尝试结束，再把这次流整体交给 Session。**

这里的 **Attempt** 就是一次实际模型尝试。一个 Step 可能失败重试，所以会有多个 Attempt。默认循环负责尝试和重试，LLM 层负责调用适配器，`AssistantStreamAttempt` 一边积累片段，一边发实时事件；Session 和持久化插件接手后续保存。

<!-- decision: D04-D1 | 为什么整次尝试结束后才统一记日志？ -->
## 实时流事件与 Attempt 日志

每个 chunk 到达时，会加入内存中的流记录、更新回复内容，并发送给实时消费者。等尝试结束，再记录一个完整事件：成功回复是 `assistant/message`；失败重试是只留作诊断的 `assistant/attempt`。

结算函数先追加 Session，再通知界面这次尝试已结束：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/assistant-stream.ts#L83-L96 -->
```ts
    try {
      // 笔记：先把整次 Attempt 写入内存 Session，拿到正式事件序号。
      seq = append()
    } catch (error: unknown) {
      // 笔记：追加失败时结束实时流的有效性，不能向界面宣称已提交。
      this.abandon()
      throw error
    }
    // 笔记：只有追加成功才发 committed end；这不等于存储 flush 已完成。
    this.terminal = true
    this.emit({
      type: 'end',
      attemptId: this.attemptId,
      revision: this.nextRevision(),
      index: this.index,
      outcome: { kind: 'committed', eventType, seq },
    })
```

这样减少了逐片段事件的重复包装和消费者处理次数，同时保留片段内容、时间与失败前缀。流内容本身仍占空间，并没有因为“只记一个事件”就变成固定大小。

失败前缀不自动成为下一请求的正式历史。比如第一次生成“答案是……”后报错，第二次重试成功，后续模型应读到成功回复，失败尝试留在日志中供排查。用户主动停止则稍有不同：已有的文本或思考前缀可以保存为 `interrupted` 消息；半截工具调用不会因此执行。

开头的丢失发生在哪里？**尝试还没结算时，硬退出可能丢掉整个在途流。** 而代码里的 `committed` 只说明 Session 已接受；JSONL 插件随后还会缓冲和批量写入。即使收到 end，也不能当作磁盘已经保存成功；公共持久化契约以完成的 `flush` 为保证。

如果要求每个已展示片段都能在硬故障后恢复，就要增加可靠的逐片段记录或检查点，承担更多写入。只需要最终回复的简单程序，也可以只存最终文本，接受失去失败过程的诊断资料。

<!-- decision: D04-D2 | 组装请求时看的模型能力，怎样与实际调用保持一致？ -->
## 模型能力快照与请求适配

还有一种变化发生在发出请求之前：插件刚查询接口 A 的能力，配置就被切换为接口 B。若临到发送又查一次“当前接口”，请求可能按 A 的规则组装，却交给 B。

DSH 的默认路径先取得 `preparedCall`：一个把本次配置、能力与执行入口放在一起的对象。循环按它判断系统提示和工具更新怎样进入历史，最后仍调用它的 `stream`。DeepSeek 适配器的核心很短：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/llm/llm-deepseek/src/adapter.ts#L43-L49 -->
```ts
  override prepareCall(provider: string, model: string, _signal?: AbortSignal): Promise<PreparedAdapterCall> {
    // 笔记：在准备阶段固定连接；能力查询与之后的生成闭包共用同一个值。
    const connection = this.dependencies.options()
    return Promise.resolve({ model: modelInfo(connection, provider, model), stream: options => this.generate(options, connection) })
  }
  // 笔记：直接 stream 则重新读取当前连接；它与已准备调用的绑定时机不同。
  stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    return this.generate(options, this.dependencies.options())
  }
```

`prepareCall` 先取得 `connection`，查能力和真正生成都使用这份连接配置。普通 `stream` 则在调用时重新读配置。上层 LLM runtime 还会冻结解析后的配置，拒绝配置漂移和重复分派同一个外层 prepared call。

准备阶段若被取消，循环还没提交这次用户输入与系统提示；重试时重新准备调用，但不会重复追加原始用户消息。这样一次请求的来源更清楚。短命、配置永不变化的程序可以直接调用；运行中允许切换适配器时，显式绑定更容易推理。

<details>
<summary>源码与核对范围</summary>

已静态核对[循环的结算与重试](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L400-L546)、[流积累与发布](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/assistant-stream.ts#L59-L96)、[JSONL 后台缓冲](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-persistence-jsonl/src/storage.ts#L267-L315)及[flush 契约](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-persistence/src/handle.ts#L85-L109)。上游测试检查[先入 Session 再发 end](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/tests/loop.spec.ts#L76-L120)、[取消前缀进入下一请求](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/tests/cancel.spec.ts#L571-L604)、[配置切换后旧 prepared 仍用旧连接](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/llm/llm-deepseek/tests/prepared-call.spec.ts#L42-L58)。本轮未运行上游或硬退出实验。这里说明默认适配器路径，流中间件仍有接管入口；单次分派限制属于外层 PreparedLlmCall。

</details>

**小自测：** 界面收到 `outcome.kind = committed`，是否可以宣布“断电也不会丢”？

<details>
<summary>参考答案</summary>

不可以。这表示完整尝试已进入 Session；持久化插件还可能在缓冲。需要等约定的 flush 完成，才能依据存储契约判断持久性。

</details>
