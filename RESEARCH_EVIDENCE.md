# 源码复核与关键结论修正

[总目录](README.md) · [逐篇阅读记录](research/reread/README.md)

这次重读的重点是把片段放回调用链。下面列出最影响理解的修正；具体文件、行号及相关测试在各批研究记录中。它们来自固定版本的静态阅读，上游测试未在本轮运行。

| 原解释容易造成的印象 | 重新核对后的解释 | 去哪里读 |
|---|---|---|
| Codex 新输入总要等到完整 Step 结束 | 常规队列有接纳边界；InstantInterrupt 路径还会监听并抢占，具体取决于配置与路径 | [Codex 01](codex/01-agent-loop.md) |
| StepContext 冻结了请求所需的一切 | 设置和工具路由共享请求视图；环境访问仍会结合所属 Turn 的当前授权 | [Codex 01](codex/01-agent-loop.md) |
| 每 Turn 新建客户端 Session，所以连接和续接基线也不跨 Turn | 连接状态可以取自缓存并在释放时归还；本轮路由令牌与跨轮连接复用要分开 | [Codex 04](codex/04-llm-streaming.md) |
| TurnStartAdmission 是容量或配额准入 | 当前宿主实现用于平稳关闭：停止接受新工作，并等已获得许可的提交结束 | [Codex 05](codex/05-extension-architecture.md) |
| 恢复会继续原来那个异步执行位置 | 恢复清单经过资格检查后，开启新的 continuation turn；JSONL 历史与 SQLite 查询投影职责不同 | [Codex 07](codex/07-persistence-reliability.md) |
| OpenCode 文档中的重试数字可直接作为当前实现 | 同一固定版本的说明和实现存在差异；默认预算及 hook 覆盖以 retry 实现和 Runner 为准 | [OpenCode 04](opencode/04-llm-streaming.md) |
| 工具文档说明的截断顺序和 metadata 上限都已实现 | 实际要追工具 hook、Step 中的截断和成功事件发布，不能只照文档描述推断 | [OpenCode 03](opencode/03-tools-sandbox.md) |
| 所有插件更新失败都会保留旧代际 | 模块加载、setup、贡献重放和明确 blocked 的处理不同；贡献重放失败会隔离插件 | [OpenCode 05](opencode/05-extension-architecture.md) |
| OpenCode 发布 durable 事件，默认就保存完整事件日志 | Bus 的事务更新会话投影和 claim；完整事件载荷由 `events.persist` 控制，默认未开启 | [OpenCode 架构](opencode/00-architecture.md)、[OpenCode 07](opencode/07-persistence-reliability.md) |
| DSH inject 永远不会在运行中影响任务 | 它不会独立唤醒空闲 Agent；正在运行的 Turn 可在下一 Step 边界消化它 | [DSH 01](dsh/01-agent-loop.md) |
| 本仓库教学模型已验证 Surface 替换和过期回调拒绝 | 现有小测试只覆盖计数/身份条件；行为证据另有上游测试源码，但本轮未运行 | [DSH 02](dsh/02-context-session.md)、[DSH 06](dsh/06-task-orchestration.md) |
| committed end 说明流已经保存到磁盘 | 它说明会话接纳了结算事件；后续还有保存和 flush 的保证 | [DSH 04](dsh/04-llm-streaming.md)、[DSH 07](dsh/07-persistence-reliability.md) |
| 持久化 ADR 提到的跨进程写锁仍只是计划 | 当前 JSONL 后端已有内核写锁；新建空会话的延迟落盘又带来首次写入时的检查边界 | [DSH 07](dsh/07-persistence-reliability.md) |
| 遥测协调器默认 live，实际默认 OTel 就一直上传 | 实际 OTel 装配使用 on-demand：新提交的显式反馈授权采集相应前缀 | [DSH 08](dsh/08-observability-evaluation.md) |
| DSH 的某个 profile 具备持久化，所以所有入口都有同样保证 | profile/bundles 选择服务组合；`sdk-minimal` 不继承 `base`，存储、检查点、遥测等要按实际装配核对 | [DSH 架构](dsh/00-architecture.md) |

## 如何复核一个结论

先打开对应主笔记，找出代码里的判断；再打开它末尾的重读记录，沿调用方与下游实现核对。若正文说“为什么这样设计”，还要看依据是作者明示理由，还是在给定条件下的分析。

源码逐行匹配可以发现摘录被改写，却发现不了“把关闭许可解释成容量配额”这样的语义错误。因此，本轮同时保留了代码核验和人工调用链复核。
