# DSH 07｜持久化：会话写入权与执行前检查点

Agent 让工具修改配置。工具做完了，进程却在保存结果前崩溃。重启后，如果日志连“调用过哪个工具”都没有，系统很难解释文件为什么变了，也无法判断该不该重试。

**DSH 先明确谁能写这段历史，再在关键动作前保存已有记录。** AgentLoop 持有会话的写句柄，JSONL 后端负责实际存储，检查点插件在模型请求和工具执行前等待保存完成。

<!-- decision: D07-D1 | 为什么写日志要先拿句柄，不能随时 append(id)？ -->
## 会话写句柄与单写入者约束

假设两个窗口都恢复会话 A。若任意地方都能 `append('A', event)`，两个写者可能都以为下一个序号属于自己。

DSH 让恢复者先拿到 `write` 句柄，再读取与修复历史：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L876-L883 -->
```ts
          // Taking write ownership FIRST excludes a concurrent resume of the
          // same id (in this process, a live agent's handle holds the claim).
          // 笔记：先拿写权再恢复历史，避免两个恢复者同时修复并追加同一会话。
          handle = await raceAbortCall(
            () => persistence.open(id, 'write', { signal: fused }),
            fused,
            id,
            // 笔记：取消等待后若句柄才到达，仍关闭它，避免写权一直被占用。
            (abandoned) => { void abandoned.close() },
          )
```

句柄可以理解为这次运行持有的写入凭证：它能读、追加、刷盘，结束时 `close()` 释放所有权。只读查看者拿 `read` 句柄，不占写权限，也不能修改记录。恢复时补齐中断轮次的结束事件，由已取得写权的 Agent 层完成。

这里已经有具体实现。[JSONL 后端](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-persistence-jsonl/src/index.ts#L381-L405)先取得进程内写资格，再申请会话目录的内核锁；POSIX 使用 `flock`，Windows 使用内核 semaphore。锁跟随句柄释放，进程退出也会释放；活着但卡住的写者会继续占锁，这是避免两个写者同时工作的代价。

后端仍然监听 `session/event`，但它将事件转给[已持有的写句柄](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-persistence-jsonl/src/storage.ts#L534-L546)，并不会在每次事件到来时重新猜谁拥有写权。小型单写者脚本可以直接持有一个文件流；多个生命周期共用存储时，显式句柄更容易管理。

<!-- decision: D07-D2 | 为什么工具动手前还要等待一次保存？ -->
## 工具执行前的持久化检查点

句柄解决“谁写”，检查点解决“何时必须写到可靠存储”。一般接口里的 `append()` 只承诺接纳并可见，`flush()` 才是耐久性承诺；当前 JSONL 实现的显式 append 更强，但实时事件仍会先进入缓冲。

基础配置挂载的检查点插件，在顶层工具执行前这样处理：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-checkpoint-policy/src/index.ts#L70-L75 -->
```ts
  ctx.on('tools/execute', async (exec, next): Promise<ToolExecutionResult> => {
    // 笔记：只检查 Agent 发起的顶层工具；嵌套调用复用外层检查点。
    if (exec.agent === undefined || exec.parent !== undefined) return next()
    // 笔记：先保存调用前缀；这里抛错就不会进入下面的工具执行体。
    await ctx.sessions.flush(exec.agent.session)
    // 笔记：保存检查点等待期间也能被取消，所以真正分派前还要再查一次。
    if (exec.signal.aborted) return abortedBeforeDispatchResult()
    return next()
  })
```

先把调用前缀保存下来，再检查等待期间有没有取消，最后才通过 `next()` 进入工具。保存失败会让调用返回错误，工具主体不会执行；嵌套工具复用外层检查点。模型请求同样先等待保存，然后才创建下游模型流。

这比每个事件都同步刷盘少一些等待，又比只在任务结束时保存更能解释中途崩溃。代价也直接：存储慢会拖慢行动，存储失败会阻止行动。

不过，回到开头：先保存调用，再改文件，仍可能在保存结果前崩溃。此时能确定的是“曾准备执行这个调用”，不能仅凭日志断定外部修改是否完成。检查点保留了追查依据，没有把文件修改和日志写入变成一个事务。

[上游测试](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-checkpoint-policy/tests/session-checkpoint-policy.spec.ts#L138-L194)覆盖了刷盘期间取消、刷盘失败两种情况，并断言工具未执行；[锁测试](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-persistence-jsonl/tests/lease.spec.ts#L158-L190)检查第二个实例被拒绝、关闭后可接管。本次仅阅读，未重跑。新建空会话延迟落盘，跨实例创建冲突可能到第一次实际写入才暴露。

## 自测

日志里有 `tool/call`，没有 `tool/result`。恢复时能直接重试吗？

<details>
<summary>展开答案</summary>

不能仅凭这两条信息决定。工具可能尚未执行，也可能已经修改文件。应先检查外部状态，或依赖工具自己的幂等设计。写句柄防止并行写坏历史，检查点保存行动依据，都不能单独保证外部动作只发生一次。

</details>
