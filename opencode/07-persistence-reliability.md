# OpenCode 07｜为什么执行开始要写 claim，主动停止又和服务关闭不同？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 从重启后的数据库倒推设计

内存中 `busy=true` 只能告诉当前进程有任务。进程被 kill、容器驱逐或宿主重启后，这个信息消失。仅保留用户 prompt 也无法判断它从未开始、正在工作、已成功还是明确取消。

execution.ts 的注释说明 write-ahead claim 与 Started 事件在同一事务提交，终态释放；shutdown interruption 保留 claim。没有终态的残留 claim 使后续启动能识别未结束意图。[F1] 这是一条作者明确解释过的恢复思路，而不是仅凭变量名猜测。

## 2. 决策 O07-D1：为什么不能只在 shutdown hook 保存任务？

SIGKILL、崩溃和掉电不保证执行正常关闭钩子。先在开始时记录执行意图，结束时清除，能把“未结算”变成数据库中的可见状态；关闭钩子只补充正常路径，不再是恢复前提。[F1]

| 策略 | 好处 | 故障窗口 |
|---|---|---|
| 只有内存状态 | 快且简单 | 重启忘记所有 active work |
| 退出时写待恢复列表 | 正常关闭够用 | 无清理退出完全丢失 |
| Started 与 claim 分开写 | 能留下部分信息 | 可能只写一边，形成相互矛盾状态 |
| Started＋claim 同事务 | 意图与事件相伴 | 还需恢复扫描、工具结算与执行归属 |

“同事务”是本层注释与 commit 回调的契约；本轮没有证明数据库驱动所有隔离/崩溃设置。claim 也不是带 owner epoch 和 expiry 的集群租约。多个进程共享存储要讨论 fencing、并发恢复和租约丢失后的旧 Worker，不能直接复用本地 map 假装完成。

## 3. 决策 O07-D2：为什么 user interrupt 应释放，shutdown 却保留？

用户按停止通常表达“不要继续这份意图”；服务重启通常只表达“当前执行载体不可用”。若不区分原因，恢复会自动继续被用户取消的任务，或让维护重启意外丢掉所有待完成工作。

源码在 deliberate stop 路径取消相关 job、释放 claim；shutdown interruption 留下 claim。[F1] 这种语义必须与产品约定一致：某些批处理系统把用户断连也视为继续，某些交互任务则把会话关闭视为取消。因此不要把网络掉线、用户停止和进程关闭直接对应为一个 canceled 状态。

**竞争点：** 中断接受后 cleanup 仍在执行，新输入可能到达。Coordinator 的 awaitSettlement 只等原 execution，awaitIdle 还会跟随后继执行。[F2] 对旧任务解除 claim 与后继新任务开始，需要可区分的忙期和终态，不应只让一个 Session-level bool 代表所有历史。

## 4. write-ahead 意图为什么仍不能提供副作用 exactly-once？

Started/claim 表示系统应处理工作，不证明每个工具的外部效果已提交。工具在修改外部世界后、结果落盘前崩溃，恢复者面对结果未知。统一重跑会重复效果；统一跳过会遗漏尚未做的动作。

本仓库机制实验以两个世界展示相同日志可能对应不同副作用；它不是 OpenCode 的故障复现。要增强保证，需要工具幂等、外部状态查询、事务型资源或人工核对，不能仅增加 retry 次数。

Durable inbox 的请求 ID 也只解决相应接纳层的重复；它不是任意 Shell 命令的幂等键。相同文本不同 ID、相同 ID 不同 Session/type，以及已有调用结果未知，都应分开设计。[D1]

## 5. 验证、选型与学习重点

**上游实验待运行：** 接纳后 wake 前退出；Started/claim 事务前后退出；user interrupt、shutdown、无清理 SIGKILL 对比；工具效果后结果前退出。记录每类恢复究竟重建了输入、执行意图、模型历史还是外部状态。

**反证条件：** 若业务只运行可随时重做的纯计算，复杂逐步恢复可能比从头重跑更贵；若有重要外部副作用，只有 claim 没有工具级协议则仍不足。

应带走的原则：把恢复所需事实前置到失败前记录；区别业务停止意图与执行载体故障；对未知结果保持诚实。恢复能力不是“resume 按钮存在”，而是每个故障窗口都有明确可证明的状态。

[F1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L70-L180
[F2]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/run-coordinator.ts#L1-L245
[D1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/session.md

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：claim 与事件提交绑定

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

### 3. 核心源码 B：一个 busy period 对应一次终态结算

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

### 4. 核心源码 C：用户停止释放，shutdown 保留

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

#### 逐段讲解

成功释放 claim。中断则先看原因：显式停止取消相关 jobs，并在 Interrupted 事件中释放；shutdown 不传 release 回调，保留后续恢复线索。

保留的是“曾有未完成执行”的持久意图，不是“旧进程仍然活着”的证明。当前本地 active 集合、历史 Started 事件和 durable claim 应分别使用。

**最重要的限制：** claim 不记录每个外部副作用的原子提交。工具可能已写文件或完成外部操作，但结果没来得及持久化。恢复系统不能从未知结果推导“从未执行”，也不能随意重演。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/opencode/07-persistence-reliability.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
