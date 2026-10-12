# DSH 01｜Agent Loop：输入通道、零 Step Turn 与失败收尾

[总目录](../README.md) · P0 · 对照：[Codex](../codex/01-agent-loop.md) / [OpenCode](../opencode/01-agent-loop.md)

**固定源码：** `deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。原文来自默认 `ReactLoopAgent`，不是所有自定义 Agent 实现。未运行模型或测试。

## 1. 先分清接口与实现

DSH 公开 Agent 契约与默认 agent-loop 分开。本篇阅读默认实现，理解其他插件依赖的输入/状态边界，而不是简单把“Loop 也是插件”当作结论。

## 2. 核心源码 A：输入目的地与是否唤醒是两个维度

源码：[`agent-loop/src/agent.ts`，L156–L191](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L156-L191)。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L156-L191 -->
```ts
  followup(input: UserMessage): void {
    this.send(input, 'next-turn', true)
  }

  steer(input: UserMessage): void {
    this.send(input, 'next-step', true)
  }

  inject(input: UserMessage): void {
    this.send(input, 'next-step', false)
  }
```

### 逐段讲解

followup 指向下一 Turn 并唤醒；steer 指向下一 Step 并唤醒；inject 指向下一 Step 但不主动唤醒。三个函数不是命名不同的同义接口。

**推导实例：** 一个文件变化通知可能只想补充下一请求的上下文，不需要立即单独花一次模型请求；inject 正好表达这种意图。但具体后续何时启动取决于其他 waking input，不能承诺注入会立即得到回答。

同文件 send 在取消后的活动尚未收敛时，会把新 waking input 导向 next-turn，避免加入已经 abort 的执行。这说明 inbox 目标还需结合生命周期解释。

## 3. 核心源码 B：Turn 可以没有任何模型请求

源码：[`agent.ts`，L307–L390](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L307-L390)。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L307-L390 -->
```ts
        const decision = await this.preStep(target, { turn, step })
        if (decision.kind === 'reject') {
          turnEnds = { kind: 'blocked' }
          return false
        }
        if (turnEnds && decision.messages.length === 0) break
        // A removed waking message or an enter decision rewritten to empty
        // still owns the initial turn boundary, but it spends no model call.
        if (phase.step === 0 && decision.messages.length === 0) {
          turnEnds = { kind: 'completed' }
          return false
        }
        signal.throwIfAborted()
        this.session.append('step/start', { turn, step })
```

### 逐段讲解

Turn 在此前已经打开，但 preStep 仍可拒绝或把输入改为空。拒绝记录 blocked；首个接受结果为空则 completed，不写 step/start，也不调用模型。**一组 Turn 边界里没有 Step 不一定表示日志损坏。**

`await preStep` 后再检查取消，防止等待期间已经收到停止却仍继续开 Step。用户输入接纳、模型调用与 Turn 结束的状态必须分开记录。

**设计分析：** 把这些情况显式写入生命周期，比只在“成功调用模型”时才建 Turn 更有利于解释拒绝和取消，但也要求指标区分 Turn 数与 model request 数。

## 4. 核心源码 C：失败时补结果，并保留恢复失败的原始原因

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L307-L390 -->
```ts
        } catch (error: unknown) {
          try {
            for (const event of toolRecovery.results()) {
              this.session.append('tool/result', event.data, {
                surfaceOp: 'append',
                ...event.sourceEventSeqs === undefined ? {} : { sourceEventSeqs: event.sourceEventSeqs },
              })
            }
          } catch (recoveryError: unknown) {
            throw new AggregateError([error, recoveryError], 'Step failed and its pending tool results could not be recorded', { cause: error })
          }
          throw error
        } finally {
          stopRecovery()
          this.session.append('step/end', { turn, step })
        }
```

工具恢复观察器在 Step 开始后登记，收集本步调用与结果事实。失败时补的是保守结果记录，不是在这里重新调用工具 body；日志修复与副作用重演必须区分。

恢复本身出错时使用 AggregateError，同时保留原失败和补记录失败，避免只剩“写日志失败”掩盖原问题。finally 解绑观察器并写 Step 结束；后面还有 Turn 结束的独立处理。

此处 `session.append` 仍是 Session 层提交，不自动证明 stable storage 已确认，见 [07](07-persistence-reliability.md)。

## 5. 把执行链画出来

next-turn/next-step 输入 → preStep → zero-step/reject 或 step/start → 模型与工具 → 保守结果补齐 → step/end → 仍有欠账则继续 → turn/end。

内部还存在 maintenance，公开 status 与完整内部 Phase 不能机械等同；只看 idle 不一定能证明所有维护操作已经静止。

## 6. 实验与验收

mock adapter 下分别触发 followup、steer、inject；记录是否产生新请求以及落在哪个 Step。再令 preStep 返回空输入，核对只有 Turn 边界。最后让一个工具结果记录失败，观察原错误与恢复错误是否都保留。

验收应能解释三种输入方式、零 Step Turn、取消检查的位置和 repair 不重演工具。原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
