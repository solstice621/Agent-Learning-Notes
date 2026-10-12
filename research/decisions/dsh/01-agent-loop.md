# DSH 01｜为什么同一个 Agent 需要三种输入方式，以及可被替换的默认驱动？

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
