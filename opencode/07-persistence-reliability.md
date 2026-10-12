# OpenCode 07｜Reliability：持久执行声明与不同停止意图

[总目录](../README.md) · P1 · 对照：[Codex](../codex/07-persistence-reliability.md) / [DSH](../dsh/07-persistence-reliability.md)

**固定源码：** `anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。精读 Execution 里的 claim/terminal 处理；数据库事务内部与启动恢复扫描仍需另行审计。未运行 crash 实验。

## 1. 本篇的问题

怎样在进程来不及执行 shutdown hook 就死亡时，仍知道它有未完成任务？用户主动停止与服务重启为什么不应使用同样恢复意图？

[Session 文档](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/session.md) 描述先记录 durable inbox，再 advisory wake。本篇直接进入执行开始/结束的源代码。

## 2. 核心源码 A：claim 与事件提交绑定

源码：[`session/execution.ts`，L66–L182](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L66-L182)。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L66-L182 -->
```ts
    const claimOnCommit = (sessionID: SessionSchema.ID) => ({
      commit: () => store.claim(sessionID),
    })
    const releaseOnCommit = (sessionID: SessionSchema.ID) => ({
      commit: () => store.release(sessionID),
    })
```

调用者不是在任意时刻单独改内存 busy 标记，而是构造提交回调，与 Bus 发布生命周期事件连接。上方源码注释把这一契约称作 write-ahead claim；要验证数据库原子性，还需继续读 Bus 与 Store，不能只因字段叫 commit 就宣称完整事务已经审计。

**分析：** 可恢复事实应在开始工作时留下，而不是只依靠工作结束时写清理记录。异常退出、SIGKILL 或节点驱逐可能根本不给 shutdown hook 机会。

## 3. 核心源码 B：一个 busy period 对应一次终态结算

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L66-L182 -->
```ts
    const coordinator = yield* SessionRunCoordinator.make<SessionSchema.ID, SessionRunner.RunError, InterruptReason>({
      started: (sessionID) =>
        reportLifecycle(
          sessionID,
          bus.publish(SessionEvent.Execution.Started, { sessionID }, claimOnCommit(sessionID)),
        ),
      drain: (sessionID, force, promotable) => drain(sessionID, force, undefined, promotable),
      // One terminal observation per busy period, covering every coalesced drain.
      settled: (sessionID, exit, reason) =>
```

这是 coordinator 配置的开始部分，未伪装成完整对象。started 发布事件并提交 claim；多个 coalesced drain 被同一个 busy period 包围，最终 settled 才处理一次生命周期结束。

因此“wake 调了三次”“drain 执行三次”“创建了三个 durable claim”不是等价关系。必须读协调器怎样合并唤醒，而不能只统计 API 调用。

## 4. 核心源码 C：用户停止释放，shutdown 保留

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L66-L182 -->
```ts
            if (outcome.type === "succeeded") {
              yield* bus.publish(SessionEvent.Execution.Succeeded, { sessionID }, releaseOnCommit(sessionID))
              return
            }
            if (outcome.type === "interrupted") {
              // Deliberate stops release the claim; shutdown keeps it for restart continuity.
              if (outcome.reason !== "shutdown") yield* jobs.cancel(sessionID)
              yield* bus.publish(
                SessionEvent.Execution.Interrupted,
                { sessionID, reason: outcome.reason },
                outcome.reason === "shutdown" ? undefined : releaseOnCommit(sessionID),
              )
              return
            }
```

### 逐段讲解

成功释放 claim。中断则先看原因：显式停止取消相关 jobs，并在 Interrupted 事件中释放；shutdown 不传 release 回调，保留后续恢复线索。

保留的是“曾有未完成执行”的持久意图，不是“旧进程仍然活着”的证明。当前本地 active 集合、历史 Started 事件和 durable claim 应分别使用。

**最重要的限制：** claim 不记录每个外部副作用的原子提交。工具可能已写文件或完成外部操作，但结果没来得及持久化。恢复系统不能从未知结果推导“从未执行”，也不能随意重演。

## 5. 中断 ACK 与清理完成

同文件接口区分 interrupt acceptance、awaitSettlement 和 awaitIdle。清理期间又可能接纳后继输入，所以等待“当前被中断的 execution”与等待“整个 Session 不再忙”不同。这一边界要结合 [01](01-agent-loop.md) 与 [03](03-tools-sandbox.md) 的 Fiber 结算阅读。

## 6. 实验与验收

比较正常成功、用户 interrupt、正常服务 shutdown、无清理进程死亡四种场景。对每次记录 claim、终态、pending input 和实际工具效果。只在测试进程/临时目录操作。

另测试输入已持久化但尚未 wake 的窗口，确认 admission 与执行权分离。验证重复 ID 时区分相同 Session/type 与跨 Session 冲突，不按文本相同猜测幂等。

验收必须能画出“记录输入—取得执行权—发生副作用—记录结果—释放 claim”的时间线，并明确哪些阶段只有文档契约、哪些已做实测。

**迁移到 Infra：** 本地 claim 不是集群 lease/fencing；跨节点接管仍需独立协议。原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
