# OpenCode 03｜Tools：完整调用、Fiber 执行与结果结算

[总目录](../README.md) · P0 · 对照：[Codex](../codex/03-tools-sandbox.md) / [DSH](../dsh/03-tools-sandbox.md)

**固定源码：** `anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。采用 Step 工具执行路径原文；未审计 OS 沙箱后端，不把应用权限称作进程隔离。实验未运行。

## 1. 本篇的关键边界

模型输出一段工具参数，不等于系统已经执行；工具 body 完成，也不等于结果已经进入 durable history。要看调用身份、记录顺序、取消通道和后置处理。

## 2. 核心源码 A：用 prepared 工具执行器，并保留调用身份

源码：[`session/runner/step.ts`，L86–L150](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L86-L150)。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L86-L150 -->
```ts
    const executeTool = (call: ToolCall) => {
      if (input.prepared.request.toolChoice?.type === "none")
        return new Tool.Error({ message: "Tools are disabled after the maximum agent steps" })
      return input.prepared.executeTool({
        sessionID: input.sessionID,
        agent: input.agent,
        messageID: input.assistantMessageID,
        call,
        progress: (update) => publisher.progress(call.id, update),
      })
    }
```

### 逐段讲解

执行入口绑定 `input.prepared`，不是在响应回来后随意从全局查一个同名函数。[工具契约](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/tools.md) 对 request-scoped tool snapshot 有进一步规定；这里看到实际消费者使用 prepared executor。

达到最大步骤后的 toolChoice=none 在本地有错误分支，因此不只依赖模型听从提示。这个条件是步数相关限制，不能代替用户权限与 OS 隔离政策。

Session、Agent、assistant message 与 call 一起传递，把工具结果归到正确的 assistant 请求。call ID 不能脱离所属消息/步骤被当作任意全局唯一键。

## 3. 核心源码 B：发布调用事实之后才运行 body

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L86-L150 -->
```ts
          yield* publisher.publish(event)
          if (event.type !== "tool-call" || event.providerExecuted) return
          toolRuns.push({
            call: event,
            fiber: yield* Effect.uninterruptibleMask((restore) =>
              restore(executeTool(event)).pipe(
                Effect.flatMap(toolOutput.truncate),
                Effect.flatMap((outcome) => publisher.toolExecution(event.id, event.name, outcome)),
                Effect.catchTag("Tool.Error", (error) =>
                  publisher.failTool(event.id, toSessionError(error), error.metadata).pipe(Effect.asVoid),
                ),
              ),
            ).pipe(Effect.forkScoped),
          })
```

### 逐段讲解

先等待 publish，再判断是否启动本地工具。`providerExecuted` 的调用不能在本地执行第二遍；只有完整 `tool-call` 事件进入这一分支，增量参数片段不触发 body。

`restore(executeTool(event))` 把工作本身置于可中断区域，而截断和 terminal publication 位于受保护处理链。`forkScoped` 把异步任务的寿命绑定 Scope，避免只留一个不受管理的 Promise。

`toolOutput.truncate` 在发布结果之前运行；如果把它放在 UI 渲染后，不能限制真正送给模型的内容。完整保留、媒体和 metadata 的规则要进一步读 ToolOutput 与 registry，不能把这一个函数当作总内存上限。

catchTag 只翻译特定 Tool.Error，没有使用 catch-all 把 interruption 和 defect 都变成模型可见字符串。**分析：** 可预期工具失败、用户取消和运行时错误应该保留不同控制语义。

## 4. 核心源码 C：停止所有已启动的工具

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L86-L150 -->
```ts
    const toolRuns: Array<{
      readonly call: ToolCall
      readonly fiber: Fiber.Fiber<void, Permission.DeclinedError | QuestionTool.CancelledError>
    }> = []
    const interruptTools = Effect.suspend(() => Fiber.interruptAll(toolRuns.map((run) => run.fiber)))
```

记录的是 invocation 与 Fiber 的对应关系，不只有工具名称。`Effect.suspend` 延迟读取 toolRuns，使执行取消效果时使用那时已经登记的任务，而不是构造之初的空数组。

类型中保留权限拒绝和问题交互取消。取消请求不是事务回滚；工具可能已经产生外部效果，但结果尚未发布。

## 5. 不应混淆的权限与输出层次

工具是否可见、是否被允许调用、输入是否合法、返回值是否合规、进程是否被隔离，是不同边界。可信工具自行捕获 Permission 服务并提出权限请求，并不意味着同一进程中的任意插件代码都被限制。

工具契约还区分 ephemeral machine `output`、模型可见 durable `content` 与 UI `metadata`。本篇展示的是 Step 调用与结算，未把契约示意代码冒充 registry 真实实现。

## 6. 实验与验收

在调用事实发布前后各设置一个闸门，确认工具 body 只能在后者完成后运行；构造 providerExecuted 调用验证本地不重复执行；取消时检查 Fiber、进度和终态，不只看返回错误字符串。

另令工具产生超大合成输出，比较生产端截断、registry/model-content 裁剪、UI 展示三个阶段。只在临时目录测试，不把泄露权限当成故障实验。

应能解释 prepared executor、发布顺序、suspend 的时机和 interruption 不被吞掉的价值。源码许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
