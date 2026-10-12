# OpenCode 整体架构与代码注释复核

研究日期：2026-10-12。固定提交：`anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`，沿用 `source-lock.json`。本轮重新读取固定源码导出目录，贯通正常执行、状态投影、生命周期和界面事件消费；没有把设计规划视为已经实现的接口。

产物为 [00 整体架构](../../opencode/00-architecture.md)，以及 `research/decisions/opencode/01–08` 的注释版源稿。架构篇新增 2 段原码、5 条中文注释；8 篇专题的全部 17 段原码新增 39 条中文注释。只新增独立的 `// 笔记：` 行；原始英文注释和代码行保持不变。

## 版本边界

根 [package.json](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/package.json#L1-L17) 显示版本 `2.0.27`，开发入口指向 `packages/cli/src/index.ts`。本快照存在 `core`、`server`、`protocol`、`client`、`app` 等包，旧教程中的 `packages/opencode/src` 不存在。目录事实来自固定导出，不使用当前远端默认分支覆盖它。

当前能力注册以 [State](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/state.ts#L5-L24) 与 [Plugin activation Scope](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin.ts#L20-L77) 为准；Catalog 的历史设计只能解释背景。

## 正常请求链的核查点

| 交接 | 当前实现证据 | 本轮确认的责任 |
|---|---|---|
| HTTP → Session | [协议](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/protocol/src/groups/session.ts#L396-L415)、[Handler](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/handlers/session.ts#L307-L342)、[公开服务](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session.ts#L411-L416) | prompt 返回持久接纳条目，不等待整个模型任务完成 |
| Session → Inbox / wake | [会话操作](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/session.ts#L145-L175) | 先检查重复输入和准备，再接纳；`resume:false` 不唤醒 |
| Execution → Location Runner | [执行器](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L87-L117)、[Instance 图](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/instance.ts#L59-L114) | 协调器是全局服务，Runner 是 Location 能力；Moved / Reloaded 重新取得实例 |
| Context → Step | [选择与加载](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/context.ts#L121-L178)、[递送边界](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L163-L179) | 指令准备先于输入递送；工具快照、Agent、历史和模型成为请求材料 |
| Step → Attempt | [runStep](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L205-L295) | 外层拥有重试/压缩/续写策略；内层拥有单次流、工具和结算 |
| 模型调用 → 工具 | [Attempt](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L95-L157)、[工具快照](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool.ts#L225-L284) | 本地工具在完整调用记录发布后启动，使用请求捕获的执行器；hosted 工具不本地重复执行 |
| 工具结果 → 下一 Step | [Attempt 返回](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L277-L290)、[外层循环](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L188-L195) | 等待工具结算，返回 needsContinuation，随后重新加载历史 |
| 终态 → idle | [终态提交](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L119-L148)、[idle 投影](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/projector.ts#L412-L440) | 成功/失败/主动中断结束工作；shutdown 不写新 idle 边界 |
| Bus → DB / SSE / UI | [数据库事务](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/bus.ts#L395-L440)、[SSE](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/handlers/event.ts#L8-L35)、[Solid 投影](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/client/src/solid/data.ts#L910-L1055)、[App 消费](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/app/src/runtime/server/runtime.tsx#L174-L199) | 持久业务投影先提交，实时事件更新 UI；UI 不是执行者 |

## 关键术语与所有权

- Turn 用 [idle 消息](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/schema/src/session-message.ts#L284-L295) 划分，包含忙时 steer 的输入；shutdown 后恢复延续同一轮。它不等于一条用户消息。
- 进程内 Execution 是一个协调器拥有的忙碌期，覆盖合并后的 drain；[实现注释与状态](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/run-coordinator.ts#L32-L46)不构成多进程锁保证。
- Attempt 最终以 `Effect.scoped` 包裹，工具用 `forkScoped` 归属其中。取消需要处理中断和最终结算，不能把结果未知的工具伪装为正常完成。
- [SubagentJob](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/subagent-job.ts#L20-L76) 捕获全局 Context/Scope，Job 与通知观察者可跨插件/父 Location 生命周期；跨进程仍需 [Job 恢复记录](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/job.ts#L9-L37)，不能保留原 Fiber。
- 恢复安装受 [managed lifecycle 条件](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/process.ts#L96-L111)控制；没有把任意嵌入式 Core 调用都写成自动恢复服务。
- [写工具](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/write.ts#L64-L87)在真正修改前请求权限，[权限规则](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/permission.ts#L158-L188)执行时重新读取；注册快照不等于已批准所有操作，也不等于操作系统沙箱。

## 新发现与正文修正

旧 07 有“Bus 在事务内保存事件、更新投影”的笼统表述，容易误读成所有部署默认保留完整事件日志。本轮读到 [Bus 的 `persist ?? false`](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/bus.ts#L198-L204) 和 [Server 配置接入](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/routes.ts#L114-L121)：

- 投影器、claim 回调和序号在事务中执行。
- 额外向 EventTable 写完整载荷受 `persist` 条件控制。
- 业务历史/收件箱持久化和完整事件日志持久化是两个命题。

已修正 07 的事务解释、08 的 Bus 职责介绍，并在 00 单独解释这一差异。此说明也收窄前一轮 [05–08 研究记录](opencode-05-08.md)中“commit callback 与持久事件同事务”一句：可直接确认的是同事务执行投影与回调；全量事件载荷写入还取决于配置。

## 已完成的本地核验与边界

- 逐块移除新增 `// 笔记：` 行后，19/19 段代码与固定源码导出中标记行范围完全一致。
- 00 和 8 篇源稿合计 72 个固定 SHA 源码行链接，已检查本地对应文件存在，起止行没有越界。
- 8 篇保留 16 个原 decision ID；未更换原问题。新增架构作为前置课，不挤掉专题。
- Mermaid 是按实际模块交接整理的教学图，不声称列出所有基础依赖。
- 本轮未运行上游 Bun 测试、完整应用或崩溃实验；没有根据静态阅读宣称外部副作用 exactly-once、断线事件自动全量重放或多进程排他执行。
