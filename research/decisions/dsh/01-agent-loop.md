# DSH 01｜执行循环：输入模式与驱动契约

Agent 正在读文件，你补充“先别改代码，只解释原因”。与此同时，文件监听器报告了一次变化。如果两条消息都立即启动模型，背景通知会变成新任务；如果都排到任务结束，你的纠正又来得太晚。

**要点：消息放在哪里，以及是否叫醒 Agent，是两个不同决定。**

先认清三个角色：`Agent` 是应用调用的公共接口；默认驱动 `ReactLoopAgent` 决定何时工作；`Session` 记录发生过什么。一次工作叫 **Turn**，其中每次模型请求及随后工具执行叫 **Step**。一次任务通常要走多个 Step。

<!-- decision: D01-D1 | 新信息是否应该立刻叫醒 Agent？ -->
## followup、steer 与 inject 的输入语义

默认驱动把区别写得很直白：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L163-L173 -->
```ts
  // 笔记：followup 等下一 Turn；true 表示这条消息有权唤醒驱动。
  followup(input: UserMessage): void {
    this.send(input, 'next-turn', true)
  }

  // 笔记：steer 在下一 Step 接入，当前已发出的请求或工具不会被撤回。
  steer(input: UserMessage): void {
    this.send(input, 'next-step', true)
  }

  // 笔记：inject 只排队；false 让空闲 Agent 不因背景信息而开工。
  inject(input: UserMessage): void {
    this.send(input, 'next-step', false)
  }
```

| 方法 | 放到哪里 | 用在什么场景 |
|---|---|---|
| `followup` | 下一 Turn，并唤醒 | “这件事结束后，再整理报告” |
| `steer` | 下一 Step，并唤醒 | “调整当前任务的做法” |
| `inject` | 下一 Step，不主动唤醒 | “这里有一条背景信息” |

回到读文件的例子：`steer` 先排队，当前工具完成后，下一次请求才带上你的纠正。它不会撤回已经发出的模型请求，也不会自动中断当前工具。需要停止执行，要调用取消。

`inject` 的“不唤醒”也有条件：空闲时只保存待处理信息；如果 Agent 正在工作，它仍会在后续 Step 读到这条信息。代码在领取输入时，先拿全部 next-step 消息；开启新 Turn 时，再取一条 next-turn 消息。因此两个队列决定的是接入时机，消息进入队列还不等于已经送给模型。[领取逻辑见这里](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/inbox.ts#L103-L113)。

<!-- decision: D01-D2 | 更换循环实现时，哪些行为必须保持一致？ -->
## Agent 接口与循环驱动的职责

命令行的一次性执行器通过 `agents.create()` 创建 Agent，调用 `followup()`，等 `whenIdle()`，还要确认子任务已稳定、等待 Session 保存，再读取结果。它不需要知道内部用了哪种循环。这让其他驱动可以替代默认实现，但替代者要保留公共方法和事件的含义。

最容易误解的是“开始过一轮”不等于“调用过模型”。默认驱动先记下 `turn/start`，再领取并检查输入。检查插件可以拒绝这次工作：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L318-L328 -->
```ts
        // 笔记：领取输入并等待拦截器决定；此时 Turn 已打开，Step 尚未开始。
        const decision = await this.preStep(target, { turn, step })
        if (decision.kind === 'reject') {
          // 笔记：拒绝留下 blocked 结束原因，不进入模型调用。
          turnEnds = { kind: 'blocked' }
          return false
        }
        if (turnEnds && decision.messages.length === 0) break
        // A removed waking message or an enter decision rewritten to empty
        // still owns the initial turn boundary, but it spends no model call.
        // 笔记：首批输入被清空也可正常结束，所以一个 Turn 可以有零个 Step。
        if (phase.step === 0 && decision.messages.length === 0) {
          turnEnds = { kind: 'completed' }
          return false
```

因此，拒绝时可以只有 `turn/start → turn/end`，中间零个 Step。这仍然是一条有意义的记录：有人要求开工，但系统没有接受。已经开启的 Step 会在 `finally` 中关闭，Turn 也会记录结束原因。应用据此区分完成、拒绝、取消和失败，而不用猜最后一段文字表示什么。

这套接口让界面、命令行和插件共用一种工作语义，代价是多了队列、取消竞争和事件顺序。只做短小的一问一答，一个 `send` 加简单循环就足够；需要边做边纠正、后台注入和不同执行策略时，再拆开这些决定。

<details>
<summary>源码与核对范围</summary>

已按固定版本静态核对[整体架构](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/architecture.md#L55-L110)、[命令行调用方](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/bundle/headless/src/index.ts#L347-L398)和[驱动收尾](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L331-L397)。上游测试分别检查[空闲 inject 不调用模型](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/tests/agent.spec.ts#L40-L51)、[纠正在下一请求生效](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/tests/loop.spec.ts#L1018-L1054)、[拒绝后零 Step](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/tests/interception.spec.ts#L250-L271)。本轮阅读了测试，未运行上游。取消后新来的唤醒消息另开 Turn，不能加入已取消的工作；展示状态 idle 也可能包含维护活动。

</details>

**小自测：** Agent 已经空闲，先 `inject` 一条通知，再 `steer` 一条要求，会发生什么？

<details>
<summary>参考答案</summary>

通知先留在 next-step 队列，不独立启动任务。steer 唤醒后，两条输入一起被领取；还要通过 pre-step 检查，才会进入实际请求。

</details>
