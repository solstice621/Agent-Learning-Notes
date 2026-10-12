# DSH：整体架构与源码注释复核

本轮针对“看不见整体架构、代码缺少讲解”重新沿调用方、驱动、服务实现和退出路径阅读源码，补写 [DSH 整体架构](../../dsh/00-architecture.md)，并为 `research/decisions/dsh/01` 至 `08` 的全部 16 个源码块增加中文注释。架构篇另有 2 个源码块。

固定仓库：`deepseek-ai/deepseek-harness`，提交 `d743267388641bc76f17c45ce8b4c231aed1d32c`。本轮是静态复核，未启动上游程序、调用真实模型或重跑上游测试。所有 `// 笔记：` 都是学习笔记新增的独立注释行；原始代码行保留不变，标记使用 `annotated-source`，剥除这些注释后应与所指固定版本逐行一致。

## 主调用链的证据

| 要证明的内容 | 本轮直接检查的源码 | 得到的结论 |
|---|---|---|
| 命令行选择运行形态 | [CLI 分派](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/apps/cli/src/bin.ts#L26-L48)、[profile 启动](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/apps/cli/src/profile-boot.ts#L265-L319) | `runCli → runProfile → boot`，配置树在统一启动器里装配；应用插件取得启动参数和退出能力。 |
| 配方如何变成插件树 | [模板](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/boot/app-boot/src/profile.ts#L178-L195)、[合成补丁](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/boot/app-boot/src/profile-context.ts#L63-L74)、[Loader 启动](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/boot/app-boot/src/index.ts#L975-L1016) | 先准备 profile 的补丁层，再挂插件并等待启动审查；遥测禁用补丁是普通层之后的附加处理。 |
| 公共 Agent 与默认循环的边界 | [Registry.create](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent/src/index.ts#L382-L415)、[setFactory](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L365-L388)、[ReactLoopAgent 实例化](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L601-L622) | 应用调用公共 Registry，默认 AgentLoop 注册工厂并实现驱动，不能把两包当成同一层。 |
| 输入如何变成实际工作 | [send、输入方法、唤醒](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L154-L234)、[kick、preStep、turn](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L252-L340) | 输入先进入 inbox；Turn 先打开，输入经 pre-step 检查后才有 Step，拒绝可产生零 Step 的 Turn。 |
| 模型究竟读哪份数据 | [输入接纳](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L400-L453)、[请求构造](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L669-L703) | 先准备绑定调用，再把提示和输入加入 Session，按 Surface 推导并冻结消息；不是从 inbox 直接拼一个临时请求。 |
| 工具结果为何进入下一次请求 | [提取并执行工具](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L529-L555)、[结果追加](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L270-L289) | 工具结果是带 Surface append 的 Session 事件；普通工具批次后 step 返回 null，驱动继续同一 Turn。 |
| 真实文件能力在哪里 | [注册表检查](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/tools/src/index.ts#L1499-L1543)、[read 执行](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/fs/tool-fs/src/read.ts#L137-L147) | 循环只调度工具，注册表控制执行边界，工具用 `ctx.fs` 读文件。 |
| 正常任务怎样结束 | [Turn 收尾](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L356-L397)、[headless 等待](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/bundle/headless/src/index.ts#L373-L403) | 模型无工具调用后仍要检查新输入和停止钩子；应用等空闲、子任务稳定和 flush，再汇总结果退出。 |

## 本轮补充或收紧的架构结论

1. **默认 base 不是全项目唯一装配。** `web/headless/sdk/acp` 模板叠加 base，`sdk-minimal` 独立装配。正文始终限定 headless + ReactLoopAgent，并明确用户补丁会改变实际能力。依据为模板源码，不由 README 名字推断。
2. **配置层次不等于激活次序。** [base 配置开头](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/bundle/base/cordis.patch.yml#L1-L13)明确按服务可用性激活；[AgentLoop inject](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L342-L342)与实际服务访问相互印证。后层补丁整行替换 config，并非深合并。
3. **默认拆卸的精确顺序以实现为准。** 公共 `AgentHandle` 注释概述退出契约，但 [teardown 实现](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L541-L590)的顺序是取消并等空闲 → `machine.scope.dispose()` → `handle.close()` → 移出 Agent/Session 注册表。本文据实现讲解，避免把概述文字当逐语句顺序。
4. **父 Agent idle 不等于整个命令行任务结束。** headless 还等可选的 `subagents.waitForChildren()`，检查父状态与日志序号稳定，随后才 flush。原 D01 的调用方描述补充这一边界。
5. **流、内存记录、磁盘记录各有完成时刻。** [AssistantStreamAttempt](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/assistant-stream.ts#L59-L96)直接证明先发 chunk、结算追加后发 committed end；[检查点策略](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-checkpoint-policy/src/index.ts#L52-L75)证明关键边界等待 flush。具体保存保证仍依所装配的存储实现。
6. **Goal 是现有循环的消息生产者。** [drive](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L137-L192)先检查、保存和保留本轮身份，再 `agent.followup(message)`；不能把 Goal Round 与 Step 混成同一层。
7. **遥测默认是反馈触发，不是聊天全量实时上传。** [OTel 的 on-demand coordinator 与反馈监听](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry-otel/src/index.ts#L219-L242)决定当前路径的实际行为；协调器具有实时采集能力，不代表它在当前配置下启用。

## 注释的教学覆盖

| 源稿 | 源码块 | 新注释解释的重点 |
|---|---:|---|
| D01 执行循环 | 2 | 排队位置与唤醒分开；拒绝或清空输入产生零 Step |
| D02 上下文管理 | 2 | Surface 顺序、版本失效、增量推导与全量引用复制 |
| D03 工具调度 | 2 | 有序提交阻塞点、后处理调用顺序、执行并发数与积压结果不同 |
| D04 模型通信 | 2 | Session 提交与磁盘保存不同；准备时绑定连接 |
| D05 扩展架构 | 2 | 文件服务分支与取消信号；迟到资源的清理责任 |
| D06 目标编排 | 2 | flush 后重新检查状态；ID 与 revision 联合挡过期回调 |
| D07 持久化 | 2 | 先拿写权、取消后关迟到句柄；执行前检查点与二次取消检查 |
| D08 可观测性 | 2 | 外发副本隔离；入队游标不能证明完整送达 |
| D00 整体架构 | 2 | headless 对子任务与保存的责任；默认驱动所需服务 |

复核保留原有 D01–D08 的 16 个 decision ID 和问题覆盖。架构篇的两个图用于解释一条普通成功路径与数据去向，不充当上游运行结果。第一轮教学复审提出把工具后处理“副作用有序”收紧为“调用逐项等待”，以及将检查点注释中的“刷盘”等待改为“保存检查点”等待，均已采纳。

本轮已将上述 18 段源码剥除独立的中文笔记注释，与本地固定提交对应行逐行比较，全部一致；已核对 16 个 decision ID 保留，两个新增文档的相对链接目标均存在。书籍构建、全仓测试与浏览器验证由整体验收统一执行。
