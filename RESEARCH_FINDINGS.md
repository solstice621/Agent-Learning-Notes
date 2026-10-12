# 横向研究结论：八个主题，八种不能混淆的边界

[总目录](README.md) · [48 项决策](DESIGN_INDEX.md)

本文件归纳各篇论证，具体官方证据随链接进入主笔记。比较的是已读契约和设计问题，不是产品排名；不同工作负载没有一个天然最优的实现。

## 1. 执行循环：输入存在、唤醒发生、任务开始是三件事

[Codex 01](codex/01-agent-loop.md) 的输入边界、[OpenCode 01](opencode/01-agent-loop.md) 的 durable input/doorbell、[DSH 01](dsh/01-agent-loop.md) 的 followup/steer/inject，都使数据与调度可分。要问的不是有没有 while，而是谁能消费、何时消费、重复唤醒是否丢消息、取消后新工作归谁。

迁移建议：不可变批量输入可以简化交互队列；交互式长任务则必须明确 steer/queue/cancel。不要为离线评测复制不需要的 UI 交互复杂度。

## 2. Context：历史事实、当前视图与本次请求不等价

[Codex 02](codex/02-context-session.md) 讨论有损摘要与确定性重建，[OpenCode 02](opencode/02-context-session.md) 讨论输入提升前的前提和续接失效，[DSH 02](dsh/02-context-session.md) 讨论日志/Surface/派生缓存。共同问题是变化如何可解释，差异是选择在哪个层维护事实与视图。

新的严格表述：增量投影只减少一部分计算；返回完整数组、完整序列化和网络传输仍可能按当前历史大小付费。压缩节省必须按完整任务与信息损失评估，而不是只看缩短 token 数。

## 3. Tools：许可、并发、安全边界与结果提交是四个轴

[Codex 03](codex/03-tools-sandbox.md) 的执行门与取消结算、[OpenCode 03](opencode/03-tools-sandbox.md) 的请求工具捕获、[DSH 03](dsh/03-tools-sandbox.md) 的动态分类/顺序提交，分别控制不同风险。

不能用“有沙箱”回答同文件并发是否正确，不能用“已批准”回答能否安全并行，不能用“模型顺序提交”证明外部副作用有序。资源预算也要分 in-flight、未提交结果和字节，不是一个并发数解决全部问题。

## 4. Streaming：逻辑工作与物理尝试必须有身份

[Codex 04](codex/04-llm-streaming.md) 的连接与续接、[OpenCode 04](opencode/04-llm-streaming.md) 的 Retry/Continue、[DSH 04](dsh/04-llm-streaming.md) 的 Attempt settlement，限制了哪里可以重做、什么已经发表、什么只属于失败证据。

连接存活不证明语义可续接；失败响应不证明没有效果；保存 live delta 不证明稳定存储；默认重试预算不必是不可放宽的硬守卫。这些边界关系到有效 rollout、重复行动和成本归因。

## 5. Plugins：可替换性需要版本、authority 与资源寿命

[Codex 05](codex/05-extension-architecture.md) 的类型化贡献、[OpenCode 05](opencode/05-extension-architecture.md) 的域内重放与代际、[DSH 05](dsh/05-extension-architecture.md) 的能力世界与迟到资源，都不是“注册 callback”可以概括。

普通坏更新保留旧版与政策明确禁止不同；旧 disposer 不能删除新对象；运行中的旧请求捕获了能力也不代表撤权可以忽略。固定不可变 Worker 镜像可能比动态热重载更简单，应按需求选。

## 6. Orchestration：身份、目标、授权、驻留、运行和交付分开

[Codex 06](codex/06-task-orchestration.md) 的元数据/驻留、[OpenCode 06](opencode/06-task-orchestration.md) 的 prompt/job/notification、[DSH 06](dsh/06-task-orchestration.md) 的 goal/armed/revision，分别避免不同类型的半启动或过期工作。

知道 child ID 不等于有权控制；递归深度/round 数不是总配额；完成通知不等于任务质量已验证。批量短评测可用简单 Job，长协作才可能值得长期子会话。

## 7. Reliability：持久意图不等于外部效果 exactly-once

[Codex 07](codex/07-persistence-reliability.md)、[OpenCode 07](opencode/07-persistence-reliability.md)、[DSH 07](dsh/07-persistence-reliability.md) 都需要明确 ACK/fence/ownership。用户停止与执行载体故障不同，read-only 观察与有权 repair 不同。

同一条已记录 tool/call 可以对应效果尚未发生或已发生但结果未存两个世界。要区分它们需额外协议，不是日志重放。恢复设计应列出每个故障窗口，不只声称支持 resume。

## 8. Observability：原始证据、live feed 与可靠账本不同

[Codex 08](codex/08-observability-evaluation.md) 离线解释原始 trace，[OpenCode 08](opencode/08-observability-evaluation.md) 限制慢观察者影响，[DSH 08](dsh/08-observability-evaluation.md) 说明遥测副本和 handoff 游标。它们都需要明确允许丢失的范围。

原始 runtime value 不能冒充模型真实输入；best-effort 游标不是送达回执；客户端掉线不必等于任务失败。训练样本、计费、审计和诊断可复用某些事实，但应有不同采集、确认和去重契约。

## 9. 下一步基础设施设计应从哪些问题开始？

将一个单机 Agent 扩为大量并发实例之前，先定义不可变任务输入、执行 owner/epoch、环境生命周期、总资源预算、工具副作用策略和结果验收。再决定是否需要队列、租约、Kubernetes、远程 sandbox、持久化工作流。

这是基于本轮研究的迁移建议，不是三个仓库已经实现的集群架构。当前没有万级并发测量，没有多节点 fencing 验证，也没有性能胜者。

最有价值的综合作业仍是：让同一工具在“效果发生、结果未记录”的窗口失败，分别列出系统知道什么、不知道什么、谁有权重试。它能同时检验 Loop、工具、存储、权限和观测，而不是只检验术语记忆。
