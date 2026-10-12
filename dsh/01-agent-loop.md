# DSH 01｜为什么同一个 Agent 需要三种输入方式，以及可被替换的默认驱动？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 从一个统一 send(message) API 开始

若所有输入都是用户请求，一个立即唤醒的 send 足够。实际运行时还会注入文件变化、工具结果相关背景、目标续跑和用户纠正。这些消息是否应该立即消耗模型请求、能否加入当前工作，不是同一个问题。

默认 ReactLoopAgent 将 followup 路由到 next-turn 并唤醒，steer 路由到 next-step 并唤醒，inject 放 next-step 但不唤醒；取消后的 waking input 会进入下一 Turn。[F1] 本篇以这些代码事实讨论产品语义，而不是把三个方法仅当别名。

## 2. 决策 D01-D1：为什么把“有信息”与“应该开始工作”分开？

**反事实：** 文件观察器每次变化都立刻 send 并调用模型；一次构建产生几十次变化，就可能造成无意续跑与额外成本。另一个极端是所有输入都静默注入，真正用户请求也可能永远不启动。

| 输入策略 | 合理场景 | 失败模式 |
|---|---|---|
| 每条输入立刻启动/重启 | 简单请求应答 | 背景信息变成工作指令，重复启动 |
| 全部排到下一 Turn | 原子短任务 | 长任务无法及时接受纠正 |
| 全部只注入不唤醒 | 背景状态更新 | 没有独立启动来源时任务不推进 |
| 信息落点与 wake 分离 | 同时支持背景、纠正和后续任务 | 需要清楚的队列与取消竞争规则 |

**推导：** 输入 API 不只是数据通道，也是调度授权。inject 不唤醒的价值，是让“这条信息可供下一请求使用”不自动等价于“现在有权开始一个新动作”。这不能阻止恶意插件直接发 followup；可信插件边界仍需另设政策。

内部 maintenance 状态对外可显示 idle。[F1] 因此 UI idle 不是“没有任何活动资源”的证明。若另一个插件要开始维护或关闭环境，应使用正确生命周期契约，而不是只检查展示状态。

## 3. 决策 D01-D2：为什么默认 Loop 可替换，但输入与事件语义不能随意变？

官方架构区分公开 Agent 接口/registry 与默认 agent-loop，实现以公开事件和 Session 事实与其他插件协作。[D1] **设计推导：** 要替换的是策略实现，不是让每个消费者猜测新的 Turn 语义。一个 Goal Driver、UI 或 telemetry 若依赖公开 lifecycle，可以不直接导入 ReactLoopAgent 私有方法；代价是公共契约必须足够稳定和精确。

默认 turn() 在 claim/pre-step 前记录 turn/start；输入被 reject 或首个 enter 为空时，可以有零个 Step 的 Turn。Step 出错时尝试补齐工具结果，finally 关闭 Step，Turn 也记录结束原因。[F1] 如果只允许“发过模型请求才算 Turn”，被拒绝的接纳和取消就会从生命周期观察中消失；如果失败时不闭合，恢复无法区分意外中断与已正常结算的失败。

**反事实：** 一个替换 Loop 把 `turn/end` 当“最终回答文本已生成”，却不等工具结果；消费者可能据此保存检查点或续跑，产生重叠执行。可替换性需要测试公共契约，而不是编译通过就足够。

## 4. 先 prepare 路由再提交输入的意义

默认 step() 先准备真实 model call，再决定 system prompt 更新和用户消息提交；firstAttempt 防止同 Step retry 重复提交已接纳输入。[F1] 若在可取消的异步 prepare 前就写入所有 user/system 内容，准备失败后日志会暗示这些内容已参与执行，实际却没有发请求。

**推导边界：** 日志可以记录“接纳但未发送”，但必须有明确事件词汇。当前代码选择某种提交边界，并不能证明所有 claim 都 durable 或所有取消都归还输入；要分别阅读 inbox/persistence 与 profile 装配。

## 5. 代价、验证与更简单的选择

插件化增加 lifecycle ordering、异步取消、迟到资源和事件语义维护。单一不可定制 Agent 完全可以用直接函数依赖，先不做可替换 Loop；只有模型策略、宿主产品或研究执行器确实要独立变化时，稳定公共边界才值得成本。

**上游实验待运行：** followup/steer/inject 各一次，检查模型调用数与输入进入的 Step；pre-step reject/empty 时确认零 Step Turn；在 prepareCall await 期间取消，检查未发送输入没有被误归入已执行历史；让替换驱动运行相同契约测试。

读完应能分别说清信息接纳、工作授权、模型请求与生命周期观察，而不是把它们都叫一轮对话。能解释为什么某个边界必要，也应能说明何时一个普通 send＋循环已足够。

[F1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L140-L530
[D1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/architecture.md

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：输入目的地与是否唤醒是两个维度

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

#### 逐段讲解

followup 指向下一 Turn 并唤醒；steer 指向下一 Step 并唤醒；inject 指向下一 Step 但不主动唤醒。三个函数不是命名不同的同义接口。

**推导实例：** 一个文件变化通知可能只想补充下一请求的上下文，不需要立即单独花一次模型请求；inject 正好表达这种意图。但具体后续何时启动取决于其他 waking input，不能承诺注入会立即得到回答。

同文件 send 在取消后的活动尚未收敛时，会把新 waking input 导向 next-turn，避免加入已经 abort 的执行。这说明 inbox 目标还需结合生命周期解释。

### 3. 核心源码 B：Turn 可以没有任何模型请求

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

#### 逐段讲解

Turn 在此前已经打开，但 preStep 仍可拒绝或把输入改为空。拒绝记录 blocked；首个接受结果为空则 completed，不写 step/start，也不调用模型。**一组 Turn 边界里没有 Step 不一定表示日志损坏。**

`await preStep` 后再检查取消，防止等待期间已经收到停止却仍继续开 Step。用户输入接纳、模型调用与 Turn 结束的状态必须分开记录。

**设计分析：** 把这些情况显式写入生命周期，比只在“成功调用模型”时才建 Turn 更有利于解释拒绝和取消，但也要求指标区分 Turn 数与 model request 数。

### 4. 核心源码 C：失败时补结果，并保留恢复失败的原始原因

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



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/dsh/01-agent-loop.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
