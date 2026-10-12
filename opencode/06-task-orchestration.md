# OpenCode 06｜Subagent：输入接纳与 Job 执行分离

[总目录](../README.md) · P1 · 对照：[Codex](../codex/06-task-orchestration.md) / [DSH](../dsh/06-task-orchestration.md)

**固定源码：** `anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。研究当前 `tool/plugin/subagent.ts`，不沿旧版 task.ts 推测。下列为真实代码节选；未执行后台任务。

## 1. 本篇问题

为什么把新输入放在 Job 的 run callback 里可能丢任务？为什么继续子会话不等于创建一个新 Agent？前台等待被取消以后，谁负责子任务和 Job？

## 2. 核心源码 A：先决定模型与子会话身份

源码：[`tool/plugin/subagent.ts`，L166–L269](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L166-L269)。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L166-L269 -->
```ts
              const model = override ?? agent.model ?? parent.model
              const child =
                existing ??
                (yield* sessions
                  .create({
                    parentID: context.sessionID,
                    title: input.description,
                    agent: Agent.ID.make(input.agent),
                    model,
                  })
                  .pipe(
                    Effect.mapError(
                      (error) => new ToolFailure({ message: `Parent session not found: ${context.sessionID}`, error }),
                    ),
                  ))
```

### 逐段讲解

模型优先级由空值合并运算符明确表达：显式覆盖、Agent 配置、父模型。前面 resolveModel 的校验不可省略，不能把任意字符串当可用 provider/model。

`existing ?? create` 保留了继续已有 Session 的语义；新建时才建立 parentID 与标题。前面的实现还检查 existing 的父关系，因此知道一个 sessionID 不应直接获得任意子会话控制权。

**注意：** 新建 child 并不在这段复制父历史。要区分 fresh context、fork 和 resume，不能统一叫“继承父 Agent”。具体失败消息映射也不证明底层错误必然是父缺失，原 error 仍作为数据保留。

## 3. 核心源码 B：Prompt 不能藏在可能被跳过的 Job.run 里

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L166-L269 -->
```ts
              // Standard prompt admission outside the job: Job.start joining a running child skips
              // its run effect, and the default wake starts an idle child or steers a running one.
              yield* sessions
                .prompt({
                  sessionID: child.id,
                  text:
                    existing === undefined
                      ? ["You are a subagent spawned by another session.", input.prompt].join("\n")
                      : input.prompt,
                  ...(background && existing === undefined ? { resume: false } : {}),
                })
                .pipe(
                  Effect.mapError(
                    (error) => new ToolFailure({ message: `Failed to prompt subagent: ${child.id}`, error }),
                  ),
                )
```

### 逐段讲解

注释直接给出设计原因：加入正在运行的 child job 可能不再执行该 job 的 run effect。如果输入只在 run 内提交，那么“加入已有执行”会导致本次新 Prompt 没有接纳。故这里先走普通 Session.prompt。

新建 child 增加委派上下文，继续已有 child 不重复增加。新建且 background 时设置 resume:false，先接纳输入，后续由 SubagentJob 控制启动；其他情况由正常 wake 处理。

**核心抽象：** durable admission、execution ownership、delivery 是三项独立责任。不是有一个 Future 就同时完成了任务记录、运行和通知。

## 4. 核心源码 C：前台等待取消会传播给两层对象

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L166-L269 -->
```ts
              const result = yield* jobs.block({ id: child.id, sessionID: context.sessionID }).pipe(
                Effect.onInterrupt(() =>
                  Effect.all([sessions.interrupt(child.id), jobs.cancel(child.id)], {
                    discard: true,
                  }),
                ),
              )
              if (result?.type === "backgrounded") {
                yield* subagents.notify(recovery, result.info.started_at)
                return backgroundResult(child.id)
              }
```

取消的是前台阻塞等待，但 cleanup 同时请求中断 child Session 与取消 Job，避免只有父调用退出、子工作继续失去管理。Effect.all 在这里协调两项清理；不应进一步推断所有底层副作用都被回滚。

等待结果还可能是 backgrounded，此时进入通知路径，而不是把它当完成文本。源码后续区分 error、cancelled、completed，并保留 child ID。`completed` 只表示这段编排结束，不证明代码补丁或业务结果正确。

## 5. 实验与验收

让 child 长时间停在 mock 工具，再提交第二条 Prompt，验证新输入确实被接纳而非因加入旧 Job 丢失。分别测试前台等待取消、显式 child 取消、转后台以及父已经停止时的完成通知。

对每个场景列出 parent Session、child Session、Job 和通知的状态，不把它们压成同一个 running 标志。未知的 Job 内部恢复行为必须继续读实现；本篇未完整审计它。

能解释为什么 Prompt 在 Job 之外、为什么已有 sessionID 意味着继续而非复制上下文、为什么通知与正确性不同。源码许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
