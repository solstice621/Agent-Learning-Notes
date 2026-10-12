# OpenCode 05–08：重新阅读记录

研究基线：`anomalyco/opencode`，固定提交 `60a212c0769acd96b446acbadeb790486830f91d`。本轮直接阅读所提供的固定版本源码目录，先确认服务分层和启动入口，再追踪每篇的问题。没有把上游 AGENTS 文件当作本次任务指令，也没有把历史设计文档当作当前接口。

## 先看的架构与入口

- [specs/v2/README.md:1–38](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/README.md#L1-L38)：Protocol 负责 HTTP 契约，Schema 负责持久事件形状，Core 负责运行和持久化；Catalog 文档明确归于历史记录。
- [packages/server/src/process.ts:47–139](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/process.ts#L47-L139)：ServerProcess 构建路由与应用作用域；只有存在 managed lifecycle 时安装自动恢复。
- [packages/core/src/instance.ts:59–95](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/instance.ts#L59-L95)：插件、工具、模型及权限等位于 Location/项目实例服务图。
- [packages/server/src/handlers.ts:47–65](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/handlers.ts#L47-L65) 与 [packages/server/src/handlers/event.ts:8–35](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/handlers/event.ts#L8-L35)：EventFeed 在 Server handler 图里提供，HTTP 请求负责连接通知、心跳和文本字节流。

## 05：插件卸载、重放与坏更新

保留问题：`O05-D1`（为什么重算而不做逆向修改）、`O05-D2`（什么失败可以保留旧版本，什么变化必须撤下）。

实际追踪：

- 入口/调度：[packages/core/src/plugin/supervisor.ts:19–122](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/supervisor.ts#L19-L122)，重读配置操作、blocked/pending/error 分支、重复 ID；[packages/core/src/plugin/supervisor.ts:124–247](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/supervisor.ts#L124-L247)，读取 registry 激活、异步更新检查代际、hold/observed、触发合并。
- 上游加载与策略：[packages/core/src/plugin/module.ts:18–63](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/module.ts#L18-L63)、[packages/core/src/plugin/module.ts:98–150](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/module.ts#L98-L150)，确认 blocked 来自 `integration.use` 对 `plugin:目标` 的 deny，发生在实际导入之前。
- 下游注册：[packages/core/src/plugin.ts:17–175](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin.ts#L17-L175)，检查插件作用域、失败分组、未变前缀保留、变化后缀重启、初始化失败时尝试加载旧版本。
- 下游重建：[packages/core/src/state.ts:160–250](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/state.ts#L160-L250)，确认每次创建新值、按序重放、删除注册使状态失效、作用域 finalizer 撤销登记；[packages/core/src/state.ts:54–110](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/state.ts#L54-L110)，确认分组失败移除贡献与 batch 仅合并通知。
- 具体使用方：[packages/core/src/command.ts:53–89](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/command.ts#L53-L89)，命令集合直接由 State 派生，查找/执行读取当前集合。
- 测试实际断言：[packages/core/test/state.test.ts:337–369](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/state.test.ts#L337-L369) 验证删除不同位置的非交换修改后重新计算；[packages/core/test/plugin.test.ts:108–136](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/plugin.test.ts#L108-L136) 验证卸载移除命令并清理；[packages/core/test/plugin.test.ts:350–386](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/plugin.test.ts#L350-L386) 验证重放失败不恢复旧版本；[packages/core/test/plugin/supervisor-reload.test.ts:251–289](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/plugin/supervisor-reload.test.ts#L251-L289) 验证导入失败保留 v1；[packages/core/test/plugin/supervisor-reload.test.ts:343–395](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/plugin/supervisor-reload.test.ts#L343-L395) 验证禁止时不导入、运行中策略变化撤销命令、解除禁止后恢复。
- 历史来源：[specs/v2/catalog-config-plugin-lifecycle.md:1–40](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/catalog-config-plugin-lifecycle.md#L1-L40)，只用作选项背景，重写以当前 State 实现为准。

确认与修正：旧文把“普通更新失败保留旧 generation”写得过宽。实际至少分四类：导入失败保留；普通 setup 失败尝试重新加载旧插件；transform 重放失败撤下整组贡献，不恢复旧代际；政策 blocked 不保留旧版。当前重放由通用 State 承担，不能只用历史 Catalog 草图解释。重载也不是全部重来：保留未变前缀、重启变化后缀。监督器的异步更新检查用 `current !== generation` 拒绝旧检查结果，但这只是更新元数据的代际保护，并不能据此宣称所有活动工具调用都会被等待或取消。

正文取舍：用 A/B 覆盖的例子带出重算，把 hold、pending queue、重复 ID 等竞争细节留在研究记录。代码取 `state.ts:172–184`、`supervisor.ts:79–90`。

未运行：上游插件、State 测试；动态热更新进程；执行中的工具被策略禁用后的外部效果实验。未声称策略禁用能撤销已经发生的副作用。

## 06：新消息接纳与任务的前后台生命周期

保留问题：`O06-D1`（为什么接纳 prompt 放在 Job.run 外）、`O06-D2`（前后台改变谁等待、谁继续管理和交付结果）。

实际追踪：

- 工具入口：[packages/core/src/tool/plugin/subagent.ts:100–267](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L100-L267)，完整阅读父会话、深度、权限、已有子会话归属、模型/agent 切换、建 child、prompt、start、前后台与失败返回。
- Session 路由：[packages/core/src/session.ts:410–420](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session.ts#L410-L420) 与 [packages/core/src/session.ts:452–461](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session.ts#L452-L461)，确认转交会话实例；[packages/core/src/session/session.ts:145–177](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/session.ts#L145-L177)，接纳先完成、之后才 wake；[packages/core/src/session/prompt.ts:29–90](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/prompt.ts#L29-L90)，插件稳定后准备 prompt、默认 steer、构造用户 inbox 项。
- Job 下游：[packages/core/src/job.ts:170–295](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/job.ts#L170-L295)，运行中同 ID 直接返回已有信息、跳过新 run；结果与 background marker 的持久化；[packages/core/src/job.ts:328–385](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/job.ts#L328-L385)，前台等待竞速 done/backgrounded，转后台创建 notification ID 并先落盘。
- 生命周期：[packages/core/src/session/subagent-job.ts:20–76](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/subagent-job.ts#L20-L76)，Job 与完成观察者挂全局 Scope，捕获全局 Context，按 childID 与 startedAt 防止同一代重复观察。
- 交付：[packages/core/src/session/subagent-completion.ts:21–46](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/subagent-completion.ts#L21-L46) 与 [packages/core/src/session/session.ts:273–313](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/session.ts#L273-L313)，通知携带固定 ID 经 synthetic admission 进入父会话，接纳成功才删除后台标记。
- 实际测试：[packages/core/test/tool-subagent.test.ts:523–574](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/tool-subagent.test.ts#L523-L574) 先放一个永不结束的 Job，再调用工具，断言追加要求确实进 inbox；[packages/core/test/tool-subagent.test.ts:210–283](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/tool-subagent.test.ts#L210-L283) 把已接纳通知的持久标记重新放回，执行恢复后断言没有重复入箱；[packages/core/test/subagent-lifetime.test.ts:55–145](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/subagent-lifetime.test.ts#L55-L145) 让 child 移动到另一个位置，反复销毁父 Location，最终确认只交付一次通知且后台标记清空。

确认与修正：旧文指出通知后端未完整审计，本次已追到 marker 写入、合成输入接纳、ack 清除与对应故障窗口测试。可以明确说“所测接纳/重放场景去重”，仍不扩大为任意外部效果 exactly-once。前后台的真实管理者都是全局 Job 服务；差别是前台等待被中断会主动取消 child/job，后台由全局观察者交付，而非简单把后台任务挂到父工具的异步回调。`completed` 是 Job 正常返回文本，不是产物验收。

正文取舍：突出“先收件、再启动或加入、最后交付”；代码取 `subagent.ts:203–213`、`subagent.ts:234–244`。

未运行：上游 SubagentTool、生命周期与恢复测试；真实模型多 Agent 实验；通知接纳冲突与每个父取消竞争的完整覆盖。

## 07：执行前记账与中断原因

保留问题：`O07-D1`（为什么不能依赖 shutdown hook）、`O07-D2`（用户停止为何释放，shutdown 为何保留）。

实际追踪：

- 启动入口：[packages/server/src/process.ts:96–111](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/process.ts#L96-L111)、[packages/server/src/process.ts:235–242](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/process.ts#L235-L242)，managed server 启动时 fork 恢复扫描。
- 事件定义：[packages/schema/src/session-event.ts:239–258](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/schema/src/session-event.ts#L239-L258)，开始和各终态确属 durable 事件。
- 执行层：[packages/core/src/session/execution.ts:48–174](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L48-L174)，terminal reason 分类、claim/release commit hook、started、settled、interrupt continuation。
- 调度顺序：[packages/core/src/session/run-coordinator.ts:87–195](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/run-coordinator.ts#L87-L195)，started 在 loop 之前，清理中收到的 wake 启动后继执行，awaitSettlement 与 awaitIdle 的范围不同。
- 真实事务：[packages/core/src/bus.ts:314–326](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/bus.ts#L314-L326) 与 [packages/core/src/bus.ts:395–435](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/bus.ts#L395-L435)，commit callback 与事件投影在同一 db.transaction 内；完整事件载荷是否另存事件表取决于 persist。并非只引用执行层注释。
- 存储：[packages/core/src/session/store.ts:195–251](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/store.ts#L195-L251)，claim 实际写 `time_suspended`；release 清标记并重置计数；根扫描排除 child，恢复计数先持久增加。
- 恢复器：[packages/core/src/session/execution/restart.ts:15–99](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution/restart.ts#L15-L99)、[packages/core/src/session/execution/restart.ts:138–231](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution/restart.ts#L138-L231)，默认 10 次预算、超限终态化、顶层与后台 child 分路径、保留 claim 直到终态；注释明确 at-least-once 与单 managed server 前提。
- 实际测试：[packages/core/test/session-execution.test.ts:35–143](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-execution.test.ts#L35-L143) 验证运行期间 claim 已存在、成功清理、scope teardown 保留、用户中断清理；[packages/core/test/session-execution.test.ts:291–340](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-execution.test.ts#L291-L340) 验证恢复预算和先计数后执行；[packages/core/test/session-run-coordinator.test.ts:317–354](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-run-coordinator.test.ts#L317-L354) 验证清理期间新唤醒；[packages/core/test/session-run-coordinator.test.ts:602–637](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-run-coordinator.test.ts#L602-L637) 验证停止应答先于清理完成。

确认与修正：旧文“同事务只来自注释与回调契约”的边界可以收窄，现已读到 Bus 真实事务实现。新增 managed server 恢复入口限制、顶层与 child 区别、10 次恢复预算。claim 是进程恢复意图，不是多主租约；恢复源码明确不保证外部副作用一次。停止原因含 inactivity，正文避免把所有非 shutdown 都写成用户主动点击。

正文取舍：用“未结账标记”解释字段与事务，再用两种中断解释释放规则。代码取 `execution.ts:76–86`、`execution.ts:128–136`。

未运行：上游数据库断言测试、真实 SIGKILL/重启、数据库驱动断电与存储耐久设置验证、外部副作用窗口实验。

## 08：共享编码、单连接积压与评估范围

保留问题：`O08-D1`（为什么独立队列而不是现成共享 PubSub）、`O08-D2`（为什么显式断流而不是静默丢弃）。

实际追踪：

- 入口：[packages/server/src/handlers.ts:47–65](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/handlers.ts#L47-L65)、[packages/server/src/handlers/event.ts:8–35](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/handlers/event.ts#L8-L35)，Feed 服务范围、先注册队列再发 connected、连接本地心跳、HTTP 字节编码。
- 完整 Feed：[packages/server/src/event-feed.ts:8–89](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/event-feed.ts#L8-L89)，全局 Bus 监听、公开过滤、零订阅跳过编码、编码一次、独立 Queue.dropping、非阻塞 offer、溢出失败、全当前连接编码失败、作用域关闭注销。
- 公开协议：[packages/protocol/src/groups/event.ts:38–68](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/protocol/src/groups/event.ts#L38-L68)，明确 volatile 与断线丢事件；`isOpenCodeEvent` 是类型清单/前缀筛选，不是运行完整 Schema 编码。
- 决策记录：[specs/v2/event-stream-architecture.md:25–166](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/event-stream-architecture.md#L25-L166)，读共享 PubSub 选项、容量性质、生命周期、坏事件处理；[specs/v2/event-stream-architecture.md:199–225](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/event-stream-architecture.md#L199-L225)，微基准测编码边界而非完整网络栈，基准脚本未提交。
- 实际测试：[packages/server/test/event-feed.test.ts:41–114](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/test/event-feed.test.ts#L41-L114) 验证两个订阅者只编码一次、容量 1 的慢订阅者失败而快者完整收到三事件；[packages/server/test/event-feed.test.ts:137–175](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/test/event-feed.test.ts#L137-L175) 验证内部事件不占容量、坏编码断开旧订阅者但新订阅者可收好事件。

确认与修正：历史文档图包含 Schema encode，当前源码 `frame` 为 JSON.stringify/SSE 包装，不能照抄旧流程。队列溢出只影响一个订阅者；编码失败清空并失败全部当前队列，两者范围必须区分。4,096 是事件数阈值且沿用旧值，不能算作完整内存上限。队列存同一编码字符串引用，剩余 per-connection offer/socket 成本仍在。EventFeed 验证进度传输机制，不能代替任务质量评估；正文以“补丁执行正常但测试失败”明确区分。

正文取舍：用三个终端快慢不同开场，只讲一个正常路径和两个失败范围；代码取 `event-feed.ts:48–54`、`event-feed.ts:63–68`。

未运行：EventFeed 上游测试、真实 HTTP 慢客户端与网络缓冲测试、未提交微基准；未新增或宣称已有完整 Agent 任务评分集。

## 本轮本地检查

正文保留 8 个隐藏 decision 索引，每篇 2 段固定 SHA 的连续原文源码；所有片段已逐字与本地固定版本文件匹配，包含原缩进和注释。计数字数不含代码，以汉字数量衡量：

| 篇目 | 汉字数 | 原文代码段 |
|---|---:|---:|
| 05-extension-architecture | 938 | 2 |
| 06-task-orchestration | 918 | 2 |
| 07-persistence-reliability | 1035 | 2 |
| 08-observability-evaluation | 1097 | 2 |

上游测试执行状态统一为“未运行”；阅读测试断言与运行测试是两类证据。
