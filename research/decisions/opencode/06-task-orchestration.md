# OpenCode 06｜子 Agent 编排：输入提交与后台托管

你让子 Agent 检查登录流程，它还没结束，又补了一句：“顺便检查退出登录。”假如系统只看到它已经在运行，就直接等待原任务，看起来一切正常，补充要求却可能根本没送进去。

**提交新输入和等待任务，是两个操作；转到后台，还要有人接手结果通知。**

OpenCode 中，子 Agent 是一段独立的子会话。`subagent` 工具检查父子关系、权限与递归深度，再调用 Session 接收输入。Job 负责跟踪运行和等待，`SubagentJob` 把两者连接起来。

<!-- decision: O06-D1 | 为什么要先送入消息，再启动或加入任务？ -->
## 输入接纳与 Job 复用

`Job.start` 遇到同 ID 的运行中任务，会直接返回已有任务信息，跳过新传入的 `run`。如果把“发送补充要求”写在 `run` 里面，就会漏掉这条要求。

因此工具先调用 `sessions.prompt`，后调用 `subagents.start`。源码甚至把这个陷阱写进了注释：

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L203-L213 -->
```ts
              // Standard prompt admission outside the job: Job.start joining a running child skips
              // its run effect, and the default wake starts an idle child or steers a running one.
              // 笔记：先独立接纳输入，再启动或加入 Job，避免复用运行中的 Job 时漏掉新要求。
              yield* sessions
                .prompt({
                  sessionID: child.id,
                  text:
                    existing === undefined
                      ? ["You are a subagent spawned by another session.", input.prompt].join("\n")
                      : input.prompt,
                  // 笔记：新建后台子会话只保存输入，交给随后建立的 Job 启动；旧子会话仍正常唤醒。
                  ...(background && existing === undefined ? { resume: false } : {}),
                })
```

`prompt` 内部会先把输入接纳到持久收件箱，再决定是否唤醒执行。已有子会话的补充要求走正常唤醒路径，可以引导正在运行的任务；新建后台子会话则传 `resume: false`，先收下消息，让随后建立的 Job 接手启动。

这里有三个不同承诺：**收件箱承诺收到了；执行器负责处理；Job 让调用者知道运行结果。** 一个任务没有重复启动，不能说明一条新消息已经被收到。

继续旧会话时，工具还会检查它的 `parentID`。拿到别人的子会话 ID，并不等于可以接管它。新建子会话则从新上下文开始，所以任务中必须带上需要的约束。

<!-- decision: O06-D2 | 转到后台以后，谁负责收尾？ -->
## 前台等待与后台结果托管

前台默认阻塞等待；等待被打断，就同时请求中断子会话并取消 Job。如果运行中途转成后台，等待者也会收到这个变化，转交通知：

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L234-L244 -->
```ts
              const result = yield* jobs.block({ id: child.id, sessionID: context.sessionID }).pipe(
                // 笔记：前台等待被取消时，同时中断子会话执行和 Job，防止只停止等待却留下任务。
                Effect.onInterrupt(() =>
                  Effect.all([sessions.interrupt(child.id), jobs.cancel(child.id)], {
                    discard: true,
                  }),
                ),
              )
              if (result?.type === "backgrounded") {
                // 笔记：运行中改为后台后，先托管完成通知，再把控制权交还父会话。
                yield* subagents.notify(recovery, result.info.started_at)
                return backgroundResult(child.id)
              }
```

后台模式一开始就返回 `running`。但它没有把工作丢在原工具调用里：`SubagentJob` 把 Job 和完成观察者放在全局服务的生命周期下。因此启动插件被卸载、父会话所在的项目实例被重建后，观察者仍可以等待并回报。实现见[全局观察者](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/subagent-job.ts#L20-L41)。

结果交付还有一个持久标记。Job 转后台时保存通知 ID 和恢复信息；完成后用同一个 ID 向父会话送入一条系统消息，接纳成功才删除标记。上游测试专门模拟“消息已接纳、标记尚未删除”时重启，检查通知没有再次进入父会话。

这解释了为什么后台不只是少写一个 `await`：它增加了独立生命周期、结果保存、通知去重和重启恢复。小型串行任务，直接等返回值更容易理解；工作确实独立、父任务还能继续做别的事时，再选择后台。

**小自测：** 子任务已在运行，为什么再次 `Job.start` 不能代替发送补充要求？收到 `completed`，能否直接判定代码修复正确？

<details>
<summary>展开答案</summary>

已有 Job 会跳过新的 `run`，所以消息必须先单独接纳。`completed` 表示运行正常返回，补丁是否正确还要靠测试或其他任务验收。

</details>

> 证据边界：已读接纳、Job、后台交付及重启重放测试，未运行。通知去重有对应实现和测试场景；任务质量需要另行验证。
