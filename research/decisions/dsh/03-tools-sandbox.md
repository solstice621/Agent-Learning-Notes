# DSH 03｜工具调度：并行执行与顺序提交

假设模型同时要求读取两个文件：A 要 10 秒，B 只要 1 秒。第 1 秒，B 已返回内容，Session 却还没有它的工具结果。直到 A 完成，系统才依次记录 A、B。

**要点：工具可以同时执行，结果的后续处理仍可以按调用顺序进行。**

在 DSH 中，默认循环拿到模型的工具调用后，交给 `executeToolCalls` 调度；工具注册表负责权限检查、实际执行和后处理；最后结果进入 Session，供下一次模型请求使用。这里讨论的是调度顺序，沙箱限制工具能做什么，属于另一层。

<!-- decision: D03-D1 | 为什么并行执行，却按模型顺序提交结果？ -->
## 工具完成顺序与结果提交顺序

调度器先依次做执行前检查，再让允许并行的工具执行体重叠运行。A、B 的结果各存进自己的 `slot`，也就是临时格子。提交指针从 A 开始，只有前面的格子有结果，才能继续：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L148-L159 -->
```ts
    // 笔记：提交指针按模型调用顺序移动，与各工具实际完成的先后无关。
    while (committed < group.length) {
      const slot = slots[committed]
      // 笔记：前面的结果未到就停住；后面的结果即使完成也先留在 slots。
      if (slot === undefined) break
      const call = group[committed]
      // 笔记：后处理调用也逐个等待，不会因后面的工具先完成就先处理它。
      const result = slot.needsPost
        ? await ctx.tools[TOOL_RUNTIME_SCHEDULER].finalize(slot.exec, slot.result)
        : ctx.tools[TOOL_RUNTIME_SCHEDULER].finish(slot.exec, slot.result)
      // oxlint-disable-next-line typescript/no-non-null-assertion -- bounded index
      appendToolResult(session, turn, step, call!.block, result, callSeqs[committed]!)
      // 笔记：结果及补充背景依次接纳，供下一 Step 构造上下文。
      for (const context of result.additionalContexts ?? []) acceptContext(context)
      concluded ||= result.concludesTurn === true
      committed++
```

所以 B 先完成时停在格子里。A 完成后，先运行 A 的后处理、记结果、接纳额外背景，再处理 B。`finalize` 会调用工具后处理插件，`acceptContext` 把补充信息排到下一 Step；“提交”包含这些动作，不只是把数组排个序。

这解释了为什么顺序值得控制：工具后处理可以修改注册表，额外背景也有阅读顺序。如果完成即提交，仅仅网络快慢变化就会改变这些动作的先后。按模型顺序可以减少这类变化，代价是前面的慢工具拖住后面的结果。

这不能保证并发工具的外部副作用也有序。两个工具若同时写同一文件，事后排好结果没有补救作用。DSH 要求工具的并发判断明确返回 `true` 才归为 parallel；其他情况按 exclusive 单独运行。声明是否可信，仍取决于工具实现。

<!-- decision: D03-D2 | 最多同时跑两个工具，为什么仍会积压很多结果？ -->
## 并发上限与待提交结果积压

补充执行位置时，检查的是 `inFlight.size`，即尚未结算的执行数：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L199-L209 -->
```ts
  const fillPool = async (): Promise<void> => {
    // 笔记：上限统计尚未结算的执行；已完成但未提交的 slots 不占这个计数。
    while (!aborted && nextToStart < group.length && inFlight.size < maxParallelToolCalls) {
      // Re-read later modes after ordered commits so registry changes can create a barrier.
      // oxlint-disable-next-line typescript/no-non-null-assertion -- bounded by the loop condition
      const nextCall = group[nextToStart]!
      // 笔记：前面的提交可能改变工具注册表，后续调用要重新检查是否仍能并行。
      if (nextToStart > 0 && mode === 'parallel'
        && ctx.tools.executionMode(nextCall.exec).kind !== 'parallel') break
      await startCall(nextToStart)
      nextToStart++
      throwSchedulerFailure()
      // 笔记：每次补位后尝试推进提交，但慢的首项仍可挡住整组结果。
      await commitReady()
```

一个执行结束后，主循环会先把它从 `inFlight` 删除，尝试顺序提交，再补充新调用。设上限为 2，A 很慢，后面 B 到 G 都很快，而且全部可并行：

1. 先启动 A、B；B 做完但等 A，空出一个执行位置。
2. 这个位置继续做 C、D、E、F、G。
3. A 没结束时，已有六份结果留在格子里，执行中的数量仍不超过 2。

因此，“并发数为 2”不是完整的内存预算。结果有多大、整组调用有多少、已提交结果何时释放，都要另外计算。这个调度器会保留 slots 到整组结束，单看执行计数无法推出内存上限。

更简单的办法是全串行；若要并行，可以同时限制“已启动但未提交”的数量，代价是 A 很慢时停止补任务。也可以让可交换的结果完成即处理，但要先确认后处理和背景顺序不影响行为。`Promise.all` 本来就能按输入顺序返回数组；DSH 额外解决的是滚动补位、执行前检查和动态独占屏障。

<details>
<summary>源码与核对范围</summary>

已静态核对[默认循环调用方](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L549-L555)、[工具执行与后处理](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/tools/src/index.ts#L1495-L1664)、[移除已结算执行再补位](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L219-L246)。上游测试检查[B 先完成仍按 A、B 记结果](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/tests/tool-calls.spec.ts#L230-L251)、[后处理与额外背景有序](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/tests/tool-calls.spec.ts#L359-L408)、[结果观察者改变后续并发模式](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/tests/tool-calls.spec.ts#L194-L226)。本轮未运行上游；六份积压是按源码构造的推演，未测 RSS，也不能据此断言其他层没有输出限制。

</details>

**小自测：** B 的耗时从 1 秒变成 0.1 秒，能让它的后处理早于 A 执行吗？

<details>
<summary>参考答案</summary>

不能。B 只是更早填好自己的格子；提交指针仍停在 A。若想降低等待，需要改变提交规则或调用顺序，单纯加速 B 没用。

</details>
