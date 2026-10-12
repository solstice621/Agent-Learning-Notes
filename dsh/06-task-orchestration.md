# DSH 06｜Goal：目标状态、自动授权与检查点竞争

[总目录](../README.md) · P1 · 对照：[Codex](../codex/06-task-orchestration.md) / [OpenCode](../opencode/06-task-orchestration.md)

**固定源码：** `deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。精读 `goal-round-driver`，不是把“目标未完成就继续”重写成伪代码。未运行自动续跑。

## 1. 为什么分开 Goal 与 Driver？

goal 保存同一 Session 的目标和状态；tool-goal 与 command-goal 提供模型/人的操作；goal-round-driver 才负责自动接续 Round。这是 [官方包组说明](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/README.md) 的分工。

业务目标尚未完成，不等于系统目前仍有权消耗模型额度和执行副作用。以下代码把业务 phase、自动 activation 与运行时就绪分开。

## 2. 核心源码 A：必须仍是同一个活 Agent

源码：[`goal-round-driver/src/index.ts`，L88–L199](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L88-L199)。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L88-L199 -->
```ts
  function currentGoal(state: DriverState): GoalView | undefined {
    if (ctx.agents.get(state.agent.id) !== state.agent) return undefined
    return ctx.goals.get(state.agent)
  }

  /** Whether this exact lifecycle is quiescent with no competing prompt. */
  function readyToDrive(state: DriverState): boolean {
    return ctx.fiber.state === FiberState.ACTIVE
      && !state.stopping
      && ctx.agents.get(state.agent.id) === state.agent
      && state.agent.status === 'idle'
      && !state.competingQueued
  }
```

### 逐段讲解

registry 中同 ID 的对象必须与 state.agent 相同，防止旧生命周期的回调驱动后来恢复的新 Agent。状态还要求插件 Fiber 活跃、未停止、Agent idle、没有竞争中的 queued prompt。

这些是允许尝试驱动的运行时条件，不是目标已完成的判定。不要把 idle 理解为所有外部资源都静止；这里只是在明确的 Driver 契约下检查它。

**设计分析：** 本地对象身份解决 stale lifecycle；Goal revision 解决 stale objective。它们针对不同的过期状态，都不等同于跨机器 fencing token。

## 3. 核心源码 B：flush 之后必须重新检查条件

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L88-L199 -->
```ts
    if (state.needsCheckpoint) {
      state.needsCheckpoint = false
      try {
        await ctx.sessions.flush(agent.session)
      } catch (error: unknown) {
        ctx.logger.warn(`goal-round-driver: durability checkpoint failed for agent "${agent.id}": ${renderThrown(error)}`)
        disarm(state)
        return
      }
      // A mutation or ordinary prompt may have arrived while the checkpoint
      // was settling. Give it its own checkpoint / turn before reserving.
      if (!readyAfterCheckpoint(state)) return
    }
```

### 逐段讲解

flush 失败时 disarm 并返回，不只是写 warning 后继续预留新轮次。disarm 撤回自动执行权，但不是把目标内容和全部状态删除。

先将 needsCheckpoint 清掉，再 await。如果期间又发生变化，新通知可以重新设为 true；readyAfterCheckpoint 既重查 readyToDrive，也检查该标志。这样不能把刚 flush 完成误认为“等待期间没有任何新工作”。

这是典型异步检查—使用竞争：await 之前成立的前提，await 之后不一定仍成立。

## 4. 核心源码 C：业务状态、授权与预算分别校验

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L88-L199 -->
```ts
    const goal = currentGoal(state)
    if (goal === undefined || goal.phase !== 'active' || goal.activation !== 'armed') return
    if (goal.roundsStarted >= goal.maxGoalRounds) {
      ctx.goals.block(agent, goalRef(goal), {
        code: 'round-limit',
        message: `Goal reached its configured limit of ${goal.maxGoalRounds} rounds.`,
      })
      return
    }

    const round = goal.roundsStarted + 1
    const content = renderGoalRoundPrompt(goal, round)
    const message = createUserMessage({
      content,
      source: { kind: 'goal', goalId: goal.id, revision: goal.revision, round },
    })
```

只有 active 且 armed 才继续，轮数到上限则 block 并给明确原因。每条续跑消息带 goalId、revision、round，不能只用一段“请继续”文本识别归属。

下一段创建 RoundAttempt，再通过公开 agent.followup 入队。这不是递归直接调用模型；真正 Turn/Step 仍由默认 Loop 处理，见 [01](01-agent-loop.md)。

轮数预算不等于 token 或时间预算；一个 Round 内仍可能多 Step。若平台要控制成本，还需新的计量/准入策略，不能从 maxGoalRounds 推出费用上限。

## 5. Subagent 是另一种编排

[Subagent 契约](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/subagent.md) 区分 provider capabilities、parent/caller delivery 与精确 activation 的 dispose。Goal 是同一 Session 续跑，subagent 是委派，二者不应混成无限递归工作流。

这里 Subagent 部分仍是契约阅读，不声称已审计所有后端启动与恢复实现。

## 6. 实验与验收

在 flush 等待中加入用户输入或更新目标，验证不会按旧条件立即预留；暂停后立即恢复，核对旧 revision 回调不再暂停新目标；让 flush 失败，检查 activation 被撤回且不继续产出 Round。

再达到 maxGoalRounds，核对 block 原因与消息归属。验收分别画 Goal 状态机和 Driver 调度状态机，不能只画一个 while goal.active。

原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
