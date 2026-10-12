# 横向研究：同一个问题，三种实现边界

[总目录](README.md)

下面是基于各篇已引用源码的分析，不是产品排名或作者原话。每个链接都有核心代码块，可以直接对照具体分支，而不是仅比较抽象术语。

| 研究问题 | Codex | OpenCode | DSH |
|---|---|---|---|
| 谁推进任务？ | [Turn 与 StepContext](codex/01-agent-loop.md) | [Execution、Runner、Attempt 分层](opencode/01-agent-loop.md) | [默认 Loop 与公开输入通道](dsh/01-agent-loop.md) |
| 模型历史从哪来？ | [压缩后重建上下文与基线](codex/02-context-session.md) | [prepare → promote → load](opencode/02-context-session.md) | [规范事件 → Surface → 派生缓存](dsh/02-context-session.md) |
| 怎样执行工具？ | [审批与共享/独占执行门](codex/03-tools-sandbox.md) | [先发布调用，再启动 Fiber](opencode/03-tools-sandbox.md) | [滚动池、动态分类、顺序提交](dsh/03-tools-sandbox.md) |
| 怎样集成模型？ | [Turn 路由与连接续接状态](codex/04-llm-streaming.md) | [有限重试及 hook 覆盖](opencode/04-llm-streaming.md) | [prepared route 与 attempt settlement](dsh/04-llm-streaming.md) |
| 怎样替换能力？ | [类型化注册与宿主准入](codex/05-extension-architecture.md) | [generation 与失败旧版保留](opencode/05-extension-architecture.md) | [作用域收敛与迟到资源回收](dsh/05-extension-architecture.md) |
| 怎样编排长期工作？ | [身份与 runtime 驻留分离](codex/06-task-orchestration.md) | [Prompt 接纳与 Job 分离](opencode/06-task-orchestration.md) | [Goal 业务状态与自动授权分离](dsh/06-task-orchestration.md) |
| 怎么恢复？ | [后台提交许可、flush 与资格](codex/07-persistence-reliability.md) | [write-ahead claim 与停止原因](opencode/07-persistence-reliability.md) | [模型/工具副作用前检查点](dsh/07-persistence-reliability.md) |
| 怎么观测？ | [运行阶段事件与 mock 测试](codex/08-observability-evaluation.md) | [共享编码、独立队列故障域](opencode/08-observability-evaluation.md) | [ledger 捕获、脱敏与 handoff](dsh/08-observability-evaluation.md) |

## 贯穿问题一：接纳与执行不是同一个 ACK

Codex 的持久化上下文允许某些检查点后台排队；OpenCode 把输入接纳与运行唤醒分开；DSH 的 checkpoint policy 在特定模型/工具副作用前等待 flush。共同方法是逐个标注 ACK：收到输入、记录意图、获得运行权、效果发生、结果提交、通知送达，各自能证明什么。

这不是说三者具有完全相同的持久性协议，而是建议用同一张故障时间线检查不同实现。来源见三篇 07。

## 贯穿问题二：请求视图与动态能力

Codex 向采样和工具链传递 StepContext；OpenCode 使用 prepared executor 并有请求级工具契约；DSH 工具调度还会在启动未运行调用前重新判定并发模式。比较时要分别研究工具实现身份、策略权限与调度分类，不能把它们合称为“快照好还是动态好”。来源见三篇 01/03。

## 贯穿问题三：取消是一段流程

Codex 在取消后对需要完成结算的 handler 继续 join；OpenCode 保护终态发布但允许 work interruption；DSH 停止补池并等待已启动工作，还处理取消后迟到的创建结果。取消请求、工作停止、资源释放与日志结算是不同时间点。来源见三篇 03/05/07。

## 贯穿问题四：记录存在不表示模型见过

运行时结果、模型可见内容、UI 元数据和遥测记录有不同用途。训练/评测轨迹必须真实反映实际请求，而不是从某个内部对象猜测模型看见什么。DSH 的 deriveMessages 与 Codex 的 for_prompt 是明确转换点，OpenCode 的 prepared request 也不能被 UI transcript 代替。来源见三篇 02/04/08。

## 从 Harness 向 Infra 迁移

本轮先掌握单任务语义，再研究多任务环境分配、配额、远程执行、租约和轨迹生产。局部锁、对象身份与持久 claim 不自动解决集群接管；本套没有万级性能或多租户安全测试结论。

最有价值的综合练习是：工具已经产生一次可计数的测试效果、但结果还未提交时中断，分别记录三套系统能恢复什么、会拒绝什么、什么仍未知。不要以最终一句“完成了”作为验收。
