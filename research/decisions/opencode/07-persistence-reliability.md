# OpenCode 07｜任务恢复：执行标记与重启接管

Agent 正在修改代码，服务突然退出。重启后只看到聊天记录：它是真的做完了，还是刚开始就崩了？如果只在内存里保存“忙碌中”，这个线索已经消失；如果打算退出时再存，强制结束进程又可能不给它机会。

**OpenCode 在开始执行前先留下“这轮还没结束”的记录，正常收尾再清除。** 重启恢复依靠这条记录，而不是期待退出钩子一定运行。

这里讲的是 Core 的执行与存储层：协调器启动一轮执行，事件总线提交开始事件对应的数据库投影，SessionStore 保存待完成标记，受管理的服务在启动时调用恢复器。

<!-- decision: O07-D1 | 为什么必须先记下来，再开始做？ -->
## 执行前的持久标记

源码把它叫 `claim`，可以先理解成“未结账标记”。它与开始事件对应的投影更新放在同一次数据库事务里：

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L76-L86 -->
```ts
    // Write-ahead claim: starting records the durable intent that a turn is in flight, in the same
    // transaction as the started event. Terminals release it — except shutdown interruption, which
    // preserves the claim so the next server start resumes the turn. A claim that survives with no
    // terminal is the signature of a process that died without teardown (crash, SIGKILL, eviction);
    // recovery is a property of the database, never of a shutdown hook that may not run.
    // 笔记：回调交给事件总线，让开始事件的投影更新与未完成标记在同一次事务中提交。
    const claimOnCommit = (sessionID: SessionSchema.ID) => ({
      commit: () => store.claim(sessionID),
    })
    // 笔记：正常终态用这个回调清除标记；服务关闭的中断分支会特意省略它。
    const releaseOnCommit = (sessionID: SessionSchema.ID) => ({
      commit: () => store.release(sessionID),
    })
```

沿调用链往下看，`started` 把 `claimOnCommit` 交给 `bus.publish`；Bus 在事务内更新投影并执行这个回调。协调器等开始步骤完成后，才进入真正的执行循环。这样不会出现已经干活、数据库却从未记录开始的正常路径。

这里持久保存的是业务状态与 claim；完整事件载荷是否另存到事件表，由 `events.persist` 配置决定，默认未开启。不能因为事件叫 durable，就推断每个部署都保留全量事件日志。见 [Bus 默认值](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/bus.ts#L198-L204)与[事务中的条件写入](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/bus.ts#L395-L430)。

更具体地说，`claim` 写的是会话表的 `time_suspended` 字段。名字虽然像“暂停时间”，实际在执行开始时就写入。任务成功或失败时，终态投影与清除标记一起提交。若进程直接消失，未清除的标记就留给下一次启动。

恢复器不会先删标记再试跑，否则恢复过程中再次崩溃就会丢线索。它先持久增加尝试次数，再继续工作；默认一轮最多自动恢复 10 次，避免反复崩溃后永远自启。见[恢复准备](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution/restart.ts#L77-L98)。

<!-- decision: O07-D2 | 用户按停止，和服务被关闭，为什么不能一样处理？ -->
## 用户取消与服务关闭的恢复语义

用户按停止，是撤回继续执行的意图。服务维护重启，则通常还希望任务继续。代码在中断收尾时按原因分支：

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L128-L136 -->
```ts
            if (outcome.type === "interrupted") {
              // Deliberate stops release the claim; shutdown keeps it for restart continuity.
              // 笔记：用户主动停止要撤回继续执行的意图；服务关闭则为下次启动保留任务。
              if (outcome.reason !== "shutdown") yield* jobs.cancel(sessionID)
              yield* bus.publish(
                SessionEvent.Execution.Interrupted,
                { sessionID, reason: outcome.reason },
                // 笔记：是否恢复取决于持久标记是否保留；同为 Interrupted 事件，提交动作却不同。
                outcome.reason === "shutdown" ? undefined : releaseOnCommit(sessionID),
              )
              return
```

`shutdown` 保留标记；用户停止和闲置中断会取消相关 Job，并随中断事件清除标记。否则用户刚叫停的任务，下一次重启又可能自己跑起来。

停止请求被接受，也不等于资源清理已经结束。执行器会异步收尾；需要确认已经停稳时，还要等待结算或空闲。清理期间新提交的工作是新意图，协调器会另外启动后续执行。

## 恢复范围与外部效果的不确定性

它恢复的是“这轮还有工作要继续”，不是把进程内存和每个外部动作倒回原处。假设工具已提交一次外部修改，却在结果落盘前崩溃，重跑可能重复修改。因此恢复器明确采用至少一次语义，工具仍需幂等、查询外部状态或单独核对。

恢复入口也有范围：受管理的服务器启动时才自动安装扫描；顶层会话按 claim 恢复，后台子会话另走 Job 的恢复记录。不能把它直接当作多个并行服务器争抢任务的租约系统。

可随时重做的纯计算，从头再跑通常更简单。只有确实要跨重启继续工作，才值得承担持久标记、恢复预算和副作用核对的成本。

**小自测：** 一轮任务被用户停止，另一轮因服务关闭而中断，重启时哪轮应该继续？继续前能否先删 claim？

<details>
<summary>展开答案</summary>

后者保留继续意图，前者应停下。不能先删标记；否则恢复途中再次退出，就失去了下一次恢复的依据。

</details>

> 证据边界：已追到 Bus 事务、启动扫描及数据库断言测试，未运行真实进程崩溃实验；外部副作用不会因 claim 自动获得仅执行一次的保证。
