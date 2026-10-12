# OpenCode 02｜为什么准备上下文必须早于消费输入，压缩又必须影响续接？

## 1. 问题不只是 messages 太长

模型请求由用户输入、指令基线、当前工具、历史消息和 provider 状态共同形成。数据库里有一条 prompt，并不表示形成这个请求的所有前提都已准备好；服务器缓存了一条 response ID，也不表示当前历史仍能续接它。

Runner 调用 prepareContext，再 promote inbox，然后 load；prepareContext 先 select，再 InstructionState.prepare。源码注释明确：初始指令基线阻塞时，已接纳输入应留在 pending。[F1] 本篇从这条具体约束推导顺序，而不是将 prepare/load 看作任意代码拆分。

## 2. 决策 O02-D1：为什么“取出消息再准备指令”不是等价重排？

**反事实时间线：** t0 用户输入已 durable；t1 从 inbox 删除/提升；t2 读取所需指令失败；t3 服务重启。若没有记录已经进入哪个逻辑步骤，恢复者可能不知道它是未执行、已部分执行还是应该重入队。

把可能失败的指令准备放在消费前，不能消除所有失败，但减少一类半接纳状态。源码在 promote 与 context.load 之间仍处理控制项争抢边界，因此不是“先检查一次配置就从此不会变化”。[F1]

| 方案 | 得到什么 | 代价 |
|---|---|---|
| 输入先消费，错误时再入队 | 正常路径看似直接 | 需要补偿、去重和已完成阶段记录 |
| 指令失败时用空默认值继续 | 可用性高 | 实际违反任务指令；难复现模型行为 |
| 准备前提后再提升输入 | 失败时保留明确 pending 状态 | 输入可能等待，必须暴露阻塞原因 |
| 接纳时冻结所有环境内容 | 精确记录提交时环境 | 准备成本进入入口；环境可能很快过时 |

**设计判断：** 是否允许缺失指令降级是业务语义，不应该由通用异常处理器决定。尤其安全或项目约束来源不可读时，用空字符串继续未必是“更可靠”。本文不假定所有 instruction source 都是安全规则。

## 3. 决策 O02-D2：为什么压缩不只是数据库删除旧消息？

当前 Runner 将 auto compaction 放在逻辑 Step 策略里，成功后重新准备请求；Attempt 仅在合适的 overflow 边界请求恢复，尤其关注 durable output 是否开始。[F1][F2] Session 文档区分完整持久历史与当前活动上下文、指令和 provider 续接语义。[D1]

**推导：** 上下文压缩改变的是“下一请求依赖什么”，而不是宣布旧事实从未发生。若只删数据库旧消息，却继续带旧 provider continuation，客户端认为已经缩小历史，服务端可能仍接着旧内容。若将所有历史重新发出，又抵消压缩并可能改变缓存前缀。

必须分别决定 transcript view、provider-native state 和 instruction baseline 何时失效。状态持久不代表适用于当前模型；一个 provider 私有 replay blob 也不应被随意搬给另一个 provider。

一个值得注意的优化是最终允许 Step 保留工具定义但设置 toolChoice=none，代码注释说明为了保留缓存前缀；工具执行侧也需要拒绝越过最大步骤的调用。[F1][F2] **分析：** 缓存友好表示与实际执行权可以分开；“声明仍在”不等于“仍允许调用”。

## 4. 保真度、缓存与安全不是同一个优化目标

少发 token 不一定让任务更便宜：摘要请求、缓存失效和丢约束后的返工都要计入。保留全部历史也不保证更正确，陈旧指令和不再成立的环境事实可能误导模型。

建议比较固定窗口、结果裁剪、摘要＋近期历史与当前分层方案；每一种都用同一任务评估约束保留、工具配对、总请求量与最终正确性。本文没有实测这些方案谁更优。

**反例：** 一个只做单轮分类的服务没必要引入复杂持久 Session、指令 delta 与 compaction epoch。抽象的收益依赖长交互、恢复与动态环境需求；不应从大型 Agent 反向制造不存在的需求。

## 5. 验证方案与学习结果

**上游实验待运行：** 初始指令准备故障后检查输入仍 pending；压缩前后分别捕获 durable history、active context、实际请求；改变 provider/工具/指令时检查续接失效与缓存行为。故障点要明确落在 outputStarted 前还是后，否则重试结论不可比。

针对 final Step，令 mock 模型仍发 tool-call，检查执行层拒绝而不是只靠 Prompt 自律。对输入重新接纳、指令快照和输出提交都保留独立 ID。

应能回答：哪些事实需要在接纳前准备，哪些只在请求时绑定，哪些历史变化要求续接失效？这比知道 context.load 的参数列表更接近可复用的 Context Engineering。

[F1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L140-L280
[F2]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L1-L290
[D1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/session.md
