# 48 项设计决策索引

[总目录](README.md) · [证据与方法](RESEARCH_METHOD.md)

24 篇主笔记各研究两项决策；编号不是产品能力评分。表中问题均链接到包含源码和论证的主笔记。

| 项目 / 专题 | 决策一 | 决策二 |
|---|---|---|
| [codex 01](codex/01-agent-loop.md) | `C01-D1` 输入到达为什么不立即改变当前推理？ | `C01-D2` 为什么按请求捕获 StepContext，而不是处处读取最新配置？ |
| [codex 02](codex/02-context-session.md) | `C02-D1` 为什么不把所有东西都交给摘要模型？ | `C02-D2` 为什么 live 与 persisted history 要共用稳定身份？ |
| [codex 03](codex/03-tools-sandbox.md) | `C03-D1` 为什么一部分任务取消后仍然等待？ | `C03-D2` 为什么把批准、并发和隔离分开？ |
| [codex 04](codex/04-llm-streaming.md) | `C04-D1` 为什么 sticky routing 放在 Turn，而不是全 Session？ | `C04-D2` 为什么输入变长还不一定可以增量发送？ |
| [codex 05](codex/05-extension-architecture.md) | `C05-D1` 为什么在编译期划分贡献能力？ | `C05-D2` 为什么容量准入要先于输入消费？ |
| [codex 06](codex/06-task-orchestration.md) | `C06-D1` 为什么“知道任务存在”不必“让它一直驻留”？ | `C06-D2` 为什么 parentID 相同还不够？ |
| [codex 07](codex/07-persistence-reliability.md) | `C07-D1` 为什么不每个事件同步刷盘，也不全部后台写？ | `C07-D2` 为什么恢复资格宁可保守，也不能对所有任务统一 resume？ |
| [codex 08](codex/08-observability-evaluation.md) | `C08-D1` 为什么把解释移出热路径？ | `C08-D2` 为什么诊断记录不能同时充当可靠业务账本？ |
| [opencode 01](opencode/01-agent-loop.md) | `O01-D1` 为什么 durable input 与 wake 不是同一件事？ | `O01-D2` 为什么一个 Step 需要多个 Attempt，而不是重启整个 Turn？ |
| [opencode 02](opencode/02-context-session.md) | `O02-D1` 为什么“取出消息再准备指令”不是等价重排？ | `O02-D2` 为什么压缩不只是数据库删除旧消息？ |
| [opencode 03](opencode/03-tools-sandbox.md) | `O03-D1` 为什么不在 tool-call 到达时查最新注册表？ | `O03-D2` 为什么不能返回一个大 JSON 给所有消费者？ |
| [opencode 04](opencode/04-llm-streaming.md) | `O04-D1` 为什么 Retry 与 Continue 不是同一种循环？ | `O04-D2` 为什么默认退避策略不是不可更改的安全上限？ |
| [opencode 05](opencode/05-extension-architecture.md) | `O05-D1` 为什么重放贡献比让每个插件自己 undo 更可控？ | `O05-D2` 为什么普通更新失败保留旧 generation，而明确 blocked 不应如此？ |
| [opencode 06](opencode/06-task-orchestration.md) | `O06-D1` 为什么 prompt admission 放在 Job.run 外面？ | `O06-D2` 为什么 foreground/background 改变的是所有权，不只是 await？ |
| [opencode 07](opencode/07-persistence-reliability.md) | `O07-D1` 为什么不能只在 shutdown hook 保存任务？ | `O07-D2` 为什么 user interrupt 应释放，shutdown 却保留？ |
| [opencode 08](opencode/08-observability-evaluation.md) | `O08-D1` 为什么不使用一个共享的有界 PubSub？ | `O08-D2` 为什么宁可断开，也不默默跳过坏事件？ |
| [dsh 01](dsh/01-agent-loop.md) | `D01-D1` 为什么把“有信息”与“应该开始工作”分开？ | `D01-D2` 为什么默认 Loop 可替换，但输入与事件语义不能随意变？ |
| [dsh 02](dsh/02-context-session.md) | `D02-D1` 为什么事实日志与活动上下文分开？ | `D02-D2` 为什么增量投影仍然返回数组快照？ |
| [dsh 03](dsh/03-tools-sandbox.md) | `D03-D1` 为什么把并行范围限定在执行体，把后置行为顺序化？ | `D03-D2` 为什么 maxParallelToolCalls 不是完整的资源预算？ |
| [dsh 04](dsh/04-llm-streaming.md) | `D04-D1` 为什么把 timed stream 嵌入一次 Attempt 的 settlement？ | `D04-D2` 为什么能力查询与实际模型调用要绑定？ |
| [dsh 05](dsh/05-extension-architecture.md) | `D05-D1` 为什么替换一个工具不等于替换一种能力？ | `D05-D2` 为什么取消资源创建后，还要接收并清理迟到的结果？ |
| [dsh 06](dsh/06-task-orchestration.md) | `D06-D1` 为什么 active 不等于现在有权继续执行？ | `D06-D2` 为什么需要 revision 与精确 Agent 对象两种身份？ |
| [dsh 07](dsh/07-persistence-reliability.md) | `D07-D1` 为什么所有写入必须经过拥有生命周期的 Handle？ | `D07-D2` 为什么在模型/工具副作用边界前设置检查点？ |
| [dsh 08](dsh/08-observability-evaluation.md) | `D08-D1` 为什么克隆与脱敏发生在导出副本，而不是原始 Session？ | `D08-D2` 为什么 best-effort cursor 不能当连续确认水位？ |
