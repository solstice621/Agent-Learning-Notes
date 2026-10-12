# OpenCode 06｜为什么委派中的 Prompt、Job 和结果通知必须分开？

## 1. 一个 child ID 不代表完整的任务协议

最简单的 subagent 函数创建模型请求并 await 结果。可继续子会话、后台执行、父子权限、任务取消以及并发提交出现后，spawn 的返回值需要表达的不只是一个字符串。

实际 subagent 工具会查找父会话、计算深度、验证目标 agent、检查权限和 parentID、选择模型，然后提交 prompt、创建恢复描述，最后选择前台阻塞或后台交付。[F1] 这里没有理由把所有动作揉成一个不透明的 task()。

## 2. 决策 O06-D1：为什么 prompt admission 放在 Job.run 外面？

源码注释明确指出：Job.start 加入已经运行的 child 时，可能跳过其 run effect，因此标准 prompt admission 必须放在 job 之外。[F1] 这是当前实现的直接理由。

**反事实时间线：** child 正在处理 A；父提交 B；如果 B 的 `sessions.prompt` 写在“仅新 Job 才执行”的闭包里，Job.start 发现旧 Job 已存在并加入它，就可能永远没有把 B 记录进去。调用者以为加入了新工作，实际上只是等旧结果。

| 候选语义 | 合理用途 | 要清楚说明的限制 |
|---|---|---|
| 每次调用新建 child | 完全独立任务 | 丢失连续上下文、产生更多 Session |
| 已有 child 就只 join | 只允许等待已提交任务 | 不能同时承诺接纳新 prompt |
| 先持久接纳，再启动/加入 Job | 支持继续已有任务 | 要有输入 ID、顺序和 busy/steer 规则 |
| 将输入与执行做一个事务式外部工作流 | 严格交付要求 | 更多存储协议与运行时依赖 |

新后台 child 可以先用 resume:false 接纳，再由 SubagentJob 管理启动；已有 child 的继续仍走相应接纳路径。[F1] “启动幂等”与“新输入去重”必须分别定义，否则接口很容易看似 idempotent 实则吞消息。

## 3. 决策 O06-D2：为什么 foreground/background 改变的是所有权，不只是 await？

前台等待通过 jobs.block；中断等待时源码会中断 child 并取消 job。后台路径返回 running，后续交由通知机制，失败中保留 sessionID 以支持定位/继续。[F1]

**推导：** 后台化把“调用者不再阻塞”与“谁继续负责取消、结果保存、通知和清理”分开。如果只是漏写 await，异步异常、资源泄漏和父任务退出后的行为都没有所有者。

父子归属检查也是能力限制：知道某个 Session ID 不应该等于有权继续它；工具验证 existing.parentID 属于当前 Session。[F1] 深度限制阻止无限递归，但不是总并发、token 或资源预算；一层就能创建很多 child。不能把 recursion limit 当作完整配额系统。

对 fresh child，传入任务必要上下文与复制父全部历史也不同。前者降低无关输入，但可能遗漏约束；后者提供更多历史，却带来成本与不该继承的状态。必须用任务信息需求选择，而不是以“更自治”评价。

## 4. 通知成功不代表任务正确

后台 completion 表明运行或交付达到某个编排终态，不证明补丁通过测试、答案有依据或用户目标达成。若把自然语言“完成了”当 reward，会把空结果或错误补丁误计成功。

**设计推导：** 应分别保存 execution outcome、result delivery、task verification。恢复与父取消竞争还可能导致重复通知或无人消费；需要相应去重与可靠交付规则，但本文没有完整审计 SubagentJob 后端，因此不宣称它提供 exactly-once 通知。

对于批量独立评测，普通 Job 结果存储可比长期 child Session 简单；对于多轮协作，保留 child identity/context 才是必要成本。foreground 与 background 应根据独立性和生命周期，而不只根据任务长短选择。

## 5. 验证和读后问题

**上游实验待运行：** child 运行 A 时再提交 B，断言 B 已实际 admission；使用另一个父尝试继续该 child，确认拒绝；前台等待被中断、后台结果完成与父关闭竞争时，分别核查资源、通知和持久结果。

测量应包含 task 排队、模型、工具、结果通知四段，不只看 spawn 返回很快。一个立即返回 running 的接口可能把全部延迟转移到用户不可见处。

应能说明：哪个操作承诺接纳输入，哪个只启动/加入执行，哪个负责交付结果，哪个负责验证目标。这些契约比“多 Agent 能并行”更接近基础设施设计。

[F1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L1-L310
