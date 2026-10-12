# 版本差异与证据边界

[总目录](README.md)

本版沿用上一版的三个官方固定提交，但将笔记改为核心源码节选和逐段讲解。以下修正或限制应与正文一起阅读，不把旧学习计划的路径或描述当作永远有效。

## OpenCode：当前 Core 与旧 Processor 路径

上一轮读取 `packages/opencode/src/session/processor.ts` 在本次固定提交返回 404。当前笔记直接使用 `packages/core/src/session/execution.ts`、`runner/llm.ts`、`runner/step.ts`，对应 Execution → Runner → logical Step → physical Attempt。见 [01](opencode/01-agent-loop.md)。这不证明所有发行版都使用当前提交。

## OpenCode：文档重试数字与实际代码

`specs/v2/session.md` 的描述写最多 4 次重试；当前 `runner/retry.ts` 使用 `Schedule.recurs(10)`，timeout 另有默认上限 3，而且 hook 在默认 decision 后还可修改行为。见 [04](opencode/04-llm-streaming.md)。基础 backoff 上限、provider Retry-After 上限、插件最终 delay 与总任务时间是不同概念，不能混算。

## OpenCode：历史 ADR 不是当前 API

Catalog/config 生命周期文档明确标为 Historical decision record，被否决的 A 方案和选定 B 的历史接口草图只用于学习取舍。本版插件章节展示实际 Supervisor 的旧 generation 保留、重复 ID、hold 与 finalizer，而不是复制历史接口当运行源码。见 [05](opencode/05-extension-architecture.md)。

## Codex：持久化策略要读实际接口

扩展注册表位于 `codex-rs/ext/extension-api/`，不是省略 ext 的路径。本版新增 `thread-store/src/store.rs`：PersistContext 明确区分可后台排队与必须完成的持久化请求，flush/shutdown/discard 的职责不同。ThreadPreparation 还需考虑未激活 preparation，不能仅凭 bool 推导物理文件已创建。见 [05](codex/05-extension-architecture.md)、[07](codex/07-persistence-reliability.md)。

## Codex：恢复资格是局部路径承诺

`daemon_recovery.rs` 捕获普通、未取消、有 RecordedTurnInput、单一本地且 FromThread 配置环境的活动 Turn；marker 仅证明进入记录流程，调用方还需 flush。不能说“所有任务都可以无条件恢复”，也不能从这一局部分支反推出所有恢复方式都不支持远程。见 [07](codex/07-persistence-reliability.md)。

## DSH：补齐 checkpoint-policy 的实际实现

上一版没有完整追踪 checkpoint-policy，保留了刷盘时机的证据缺口。本版直接展示该插件：关联到活 Session 的模型 stream 在 next 之前 flush；顶层且有 Agent 的工具在 body 前 flush 并复查取消；pre-step 也 flush 前一批结果。无 Session、无 Agent 或嵌套调用有明确跳过分支。保证以插件挂载和匹配调用路径为前提，不推断全部 profile 都启用，也不称为每个 Turn 末尾强制 fsync。见 [07](dsh/07-persistence-reliability.md)。

## DSH：注释中的可变性与当前实现

telemetry coordinator 的 captureEvent 附近有 canonical event mutable 的注释，而当前 Session.append 真实代码会 snapshot/deepFreeze，并校验后 commit。本版依据实际调用解释“捕获副本与规范日志分开”，保留注释差异，不据该旧措辞宣称用户可以改写历史。见 [02](dsh/02-context-session.md)、[08](dsh/08-observability-evaluation.md)。

## 三个项目共同的限制

事件日志不等于外部副作用 exactly-once；进程内 claim/对象身份不等于分布式 lease/fencing；工具许可和可见性不等于 OS 沙箱；沙箱文件政策不自动包含网络隔离；trace/telemetry 交接不等于业务稳定提交或远端送达。

代码块逐字匹配只验证引用完整性，不验证所有讲解、执行分支、性能或安全保证。本版没有运行上游 Agent 测试，也没有测量哪一个 Agent 更快、更安全或模型得分更高。所有待运行实验必须保留 NOT RUN，直到有明确命令和证据。
