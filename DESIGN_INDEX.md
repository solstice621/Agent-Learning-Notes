# 48 个问题索引

[总目录](README.md) · [先读导览](START_HERE.md)

每篇围绕两个具体问题展开；点击项目与专题，进入例子、解释和相邻的源码。编号只用于定位。

| 项目 / 专题 | 问题一 | 问题二 |
|---|---|---|
| [codex 01](codex/01-agent-loop.md) | `C01-D1` 新消息到了，为什么不立刻塞进正在执行的请求？ | `C01-D2` 工具配置变了，为什么当前请求还保留旧版本？ |
| [codex 02](codex/02-context-session.md) | `C02-D1` 为什么拿到摘要以后，还要重新拼装上下文？ | `C02-D2` 为什么内存和存档必须保存同一份新历史？ |
| [codex 03](codex/03-tools-sandbox.md) | `C03-D1` 取消后继续等待，是不是没有真正停止？ | `C03-D2` 获得批准的工具，为什么还不能随便并行？ |
| [codex 04](codex/04-llm-streaming.md) | `C04-D1` 同一个连接还能用，为什么新一轮要重建客户端对象？ | `C04-D2` 历史变长了，为什么仍可能发送完整请求？ |
| [codex 05](codex/05-extension-architecture.md) | `C05-D1` 不同功能为什么不共用一个万能回调？ | `C05-D2` 服务准备退出时，为什么先关入口再取输入？ |
| [codex 06](codex/06-task-orchestration.md) | `C06-D1` 为什么保留子任务，却不让它一直占着内存？ | `C06-D2` 为什么父任务编号相同，还要重新检查归属？ |
| [codex 07](codex/07-persistence-reliability.md) | `C07-D1` 为什么“交给记录器”与“确认保存”要分开？ | `C07-D2` 有历史，为什么有些任务仍不自动继续？ |
| [codex 08](codex/08-observability-evaluation.md) | `C08-D1` 为什么先记事件，稍后再整理关系？ | `C08-D2` 调试记录写失败时，任务应不应该跟着失败？ |
| [opencode 01](opencode/01-agent-loop.md) | `O01-D1` 忙的时候收到新消息，怎样保证稍后还会处理？ | `O01-D2` 请求失败时，究竟重做哪一段？ |
| [opencode 02](opencode/02-context-session.md) | `O02-D1` 项目指令还没准备好，要先取走用户消息吗？ | `O02-D2` 历史太长时，为什么不能直接删掉旧消息？ |
| [opencode 03](opencode/03-tools-sandbox.md) | `O03-D1` 工具更新了，正在等待的调用该执行哪个版本？ | `O03-D2` 一个工具结果，为什么需要三种表示？ |
| [opencode 04](opencode/04-llm-streaming.md) | `O04-D1` 断线前已经有内容，接下来应重试还是续写？ | `O04-D2` 设置重试次数，为什么还不能算出最长等待时间？ |
| [opencode 05](opencode/05-extension-architecture.md) | `O05-D1` 卸载后怎样保住其他插件的修改？ | `O05-D2` 新插件坏了，什么时候还能继续用旧版？ |
| [opencode 06](opencode/06-task-orchestration.md) | `O06-D1` 为什么要先送入消息，再启动或加入任务？ | `O06-D2` 转到后台以后，谁负责收尾？ |
| [opencode 07](opencode/07-persistence-reliability.md) | `O07-D1` 为什么必须先记下来，再开始做？ | `O07-D2` 用户按停止，和服务被关闭，为什么不能一样处理？ |
| [opencode 08](opencode/08-observability-evaluation.md) | `O08-D1` 既然大家看同一条消息，为什么还要各自排队？ | `O08-D2` 为什么宁可断开，也不偷偷丢一条？ |
| [dsh 01](dsh/01-agent-loop.md) | `D01-D1` 新信息是否应该立刻叫醒 Agent？ | `D01-D2` 更换循环实现时，哪些行为必须保持一致？ |
| [dsh 02](dsh/02-context-session.md) | `D02-D1` 为什么日志和当前上下文要分开？ | `D02-D2` 有了增量缓存，读取历史为什么仍有成本？ |
| [dsh 03](dsh/03-tools-sandbox.md) | `D03-D1` 为什么并行执行，却按模型顺序提交结果？ | `D03-D2` 最多同时跑两个工具，为什么仍会积压很多结果？ |
| [dsh 04](dsh/04-llm-streaming.md) | `D04-D1` 为什么整次尝试结束后才统一记日志？ | `D04-D2` 组装请求时看的模型能力，怎样与实际调用保持一致？ |
| [dsh 05](dsh/05-extension-architecture.md) | `D05-D1` 为什么换一个工具，还没有换好整个执行环境？ | `D05-D2` 已经取消创建，为什么还要处理迟到的资源？ |
| [dsh 06](dsh/06-task-orchestration.md) | `D06-D1` 目标还是 active，为什么不能继续执行？ | `D06-D2` 刚恢复的任务，为什么不能再被旧回调暂停？ |
| [dsh 07](dsh/07-persistence-reliability.md) | `D07-D1` 为什么写日志要先拿句柄，不能随时 append(id)？ | `D07-D2` 为什么工具动手前还要等待一次保存？ |
| [dsh 08](dsh/08-observability-evaluation.md) | `D08-D1` 为什么只改导出的副本，不直接把原日志脱敏？ | `D08-D2` 游标已经到 6，为什么第 5 条仍可能没送到？ |
