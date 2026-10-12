# OpenCode 01｜执行循环：持久输入与唤醒协调

你让 Agent 修测试。它快做完时，你又补了一句：“也检查一下空输入。”如果服务器因为“这个会话正在忙”就忽略这次通知，旧任务可能恰好退出，补充要求便一直躺在队列里。

**OpenCode 把“记下用户说了什么”和“提醒执行器来取”分开：消息保存在数据库里，提醒可以合并，但不能被忙碌状态吞掉。**

先看它在项目中的位置：界面把输入交给 HTTP 接口；Core 的 Session 操作负责保存输入；执行协调器安排同一会话依次运行；Runner 再负责模型与工具的循环。页面连接并不直接拥有这个循环。

<!-- decision: O01-D1 | 忙的时候收到新消息，怎样保证稍后还会处理？ -->
## 持久收件箱与唤醒信号

[Session.prompt](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/session.ts#L145-L175)先做输入去重和准备，再写入待处理队列，最后调用 `wake`。即使设置 `resume: false`，消息仍会保存，只是不启动执行。重复请求若使用相同消息 ID，也不会再插入一条用户输入。

`wake` 可以理解为门铃。有人在工作时，门铃只需留下“还有事”的记号；实际内容仍在队列中。

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/run-coordinator.ts#L136-L145 -->
```ts
    const wake = (key: Key, scope: Promotable = "input") =>
      Effect.sync(() => {
        // 笔记：此协调器内，同一会话只保留一个执行者；新消息已另存于收件箱，这里只处理唤醒。
        const execution = executions.get(key)
        if (execution !== undefined) {
          // Coalesced wakes keep the widest scope: "input" subsumes "steer".
          // 笔记：合并提醒时保留更宽的 input 范围，避免后来的 steer 提醒缩小待处理范围。
          execution.pendingWake = execution.pendingWake === "input" ? "input" : scope
          return
        }
        // 笔记：空闲时创建执行者；真正处理在异步执行中进行，wake 不等待任务结束。
        start(key, false, scope)
      })
```

关键是 `pendingWake`：当前循环结束前会检查它。若提醒来得更晚，落在清理阶段，[收尾函数](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/run-coordinator.ts#L114-L120)还会据此启动下一次执行。因此，“已检查过队列”与“进入空闲”之间的新消息也有人接手。

最简单的 `if (busy) return` 少了这个记号。定时扫描队列也能补救，但会增加等待和扫描成本。这里选择的是一个进程内、按会话串行的协调器；不同会话仍能并发。

<!-- decision: O01-D2 | 请求失败时，究竟重做哪一段？ -->
## Turn、Step 与 Attempt 的执行层次

一次正常执行可以这样跟：递送用户消息 → 向模型提问 → 执行它提出的工具 → 保存结果 → 把结果交给模型继续。这里的一轮模型工作叫 Step；其中一次真实请求和它带出的工具处理叫 Attempt。

假设连接在输出前失败，只需要重试这个 Step。若重新从入口提交“修测试”，就把已接纳的工作又提交了一遍。Runner 因而把重试放在内层：重新准备请求，却不再次递送待处理消息。

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L206-L217 -->
```ts
    const runStep = Effect.fn("SessionRunner.runStep")(function* (first: SessionContext.Loaded, step: number) {
      const sessionID = first.session.id
      let assistantMessageID = SessionMessage.ID.create()
      // 笔记：重试策略属于当前 Step，循环内的各次 Attempt 共用其次数和等待状态。
      const retry = yield* SessionRunnerRetry.make(bus, sessionID)
      let initial: SessionContext.Loaded | undefined = first
      let recoverOverflow = true
      let recoverContinuation = true
      while (true) {
        // Reuse boundary preparation once; retries refresh context without delivering more input.
        // 笔记：首轮复用已准备的上下文；重试刷新上下文，但不会再次从收件箱递送输入。
        const loaded = initial ?? (yield* prepareContext(sessionID).pipe(Effect.flatMap(context.load)))
        initial = undefined
        const compacted = yield* compaction.compact({ reason: "auto", context: loaded })
```

`initial` 第一次使用已经准备好的上下文，之后重新加载；这段循环没有 `SessionInbox.promote`。递送输入发生在外面的步骤边界。工具完成、需要模型继续时，Runner 才进入后续 Step。

这样做还让停止的含义更清楚：接受取消、旧执行清理完毕、整个会话空闲，是三个时刻。新输入在清理期间到达时，旧执行可以结束，后续执行接着工作。

代价是多了几层状态。只有一个调用者、没有排队和恢复要求的小脚本，可以先用一个循环；一旦允许运行中补充输入，就需要明确谁保存消息、谁接手它、失败后重做哪里。

**想一想：** 同一会话收到两条不同消息，却只留下一个 `pendingWake`，会丢掉其中一条吗？

<details>
<summary>参考答案</summary>

不会因为提醒合并而丢消息。两条输入各自持久保存，门铃只是要求重新检查队列；具体何时递送仍由 steer、queue 和控制项的顺序决定。

</details>

本篇重新阅读了入口、协调器、Runner 及[协调器测试](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-run-coordinator.test.ts#L263-L280)；测试用受控等待制造收尾期间的新提醒。本轮未运行上游测试；这里也不包含跨进程唯一执行保证。
