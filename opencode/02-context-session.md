# OpenCode 02｜Context：先建立执行前提，再提升输入

[总目录](../README.md) · P0 · 对照：[Codex](../codex/02-context-session.md) / [DSH](../dsh/02-context-session.md)

**固定源码：** `anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。本篇采用 Runner 的实际调用点；文档描述的指令 blob/epoch 等语义单独作为扩展阅读，不伪装成已经审计全部 projector。未运行实验。

## 1. 本篇研究问题

如何避免已经接受了用户任务，却在执行前提不满足时把它从 pending 输入中消耗掉？如何把当前 agent、model、tools、instructions 和 history 组合成真正发送的请求？

## 2. 核心源码 A：初始指令失败时保留 pending 输入

源码：[`session/runner/llm.ts`，L165–L282](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L165-L282)。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L165-L282 -->
```ts
    const prepareContext = Effect.fn("SessionRunner.prepareContext")(function* (sessionID: SessionSchema.ID) {
      const selected = yield* context.select(sessionID)
      // A blocked initial instruction baseline must leave admitted input pending.
      yield* InstructionState.prepare(db, bus, selected.instructions, sessionID)
      return selected
    })
```

### 逐段讲解

select 先决定当前 Session 所需的上下文来源，InstructionState.prepare 再建立初始指令基线。`yield*` 失败会停止这条 Effect 路径，因此不能把它放在不等待的后台 Promise 中后继续执行。

注释表达的是明确的 admission 约束：输入已被系统接纳，但在初始指令阻塞时应仍 pending。**接纳成功与模型可见是不同承诺。** 这段还没有展示数据库如何存指令，只能证明准备步骤发生在调用者可以继续之前。

## 3. 核心源码 B：准备完成之后才 promote

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L165-L282 -->
```ts
                  const selected = yield* prepareContext(sessionID)
                  const promoted = yield* SessionInbox.promote(
                    db,
                    bus,
                    sessionID,
                    entering && !continuing ? promotable : "steer",
                  )
                  // A control admitted during context preparation owns this boundary.
                  if (promoted === undefined) return undefined
                  if (promoted > 0 && !selected.session.parentID && SessionTitle.isUntitled(selected.session))
                    yield* FiberMap.run(titles, sessionID, title.generate(sessionID), {
                      onlyIfMissing: true,
                    })
                  if (promoted > 0) step = 1
                  return { _tag: "Ready" as const, context: yield* context.load(selected) }
```

### 逐段讲解

prepare 可能等待 I/O，期间还可能到达新的控制项。因此 promote 返回 undefined 的情况不是“没有用户文本”这么简单：注释说明控制项可能获得这个边界，当前路径需要退出再评估。

`entering && !continuing` 参与选择可提升的输入类别；继续中的路径只使用 steer。不能把 queue 和 steer 都作为随时插入的普通数组元素。

真正提升新输入后重置 step 预算。标题生成由 FiberMap 管理，使用 onlyIfMissing，避免每次输入都重复创建同一标题任务；它不是上下文正确性的必要前置条件。

最后 `context.load(selected)` 发生在 promote 之后，因而读取的是这次边界已提升后的模型上下文，而不是在等待期间抓到的一份永远不变的旧 messages。

## 4. 核心源码 C：请求由明确的当前视图构建

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L165-L282 -->
```ts
        const transcript = SessionModelRequest.baseTranscript({
          agent: loaded.agent.info,
          model: loaded.model,
          tools: loaded.tools,
          initial: loaded.initial,
          messages: loaded.messages,
        })
```

`initial` 与 messages 分开，agent/model/tools 又是独立输入。不能用一个聊天 transcript 文本完全代替此结构。这里也不应根据函数名编造 provider 的实际序列化；需进一步跟踪 `context.request.primary` 和 adapter。

**设计分析：** 将来源与转换边界显式表达，才能解释为什么模型在重试或压缩后看到不同内容。持久化历史完整不意味着每次请求都发送完整历史，也不保证压缩摘要保真。

## 5. 与压缩和 provider 状态的联系

同文件 `runStep` 在构建 baseTranscript 前运行 compaction，成功后重新开始准备；重试会刷新上下文但不再 promote 输入，见 [01](01-agent-loop.md)。

[Session 契约](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/session.md) 描述 durable transcript 与活动摘要、指令 epoch、provider continuation 的区别。这里把这些标为文档契约，不从几个调用点宣称整个数据库与序列化实现已验证。

## 6. 失败实验

让初始指令来源失败：确认任务仍 pending；恢复后只提升一次。让一个控制项在 prepare 等待时到达：记录 promote 返回与下一边界，验证不能越过控制项。

另保存压缩前 durable log、压缩后 active history 和实际 provider request 三份对照，分别标出指令、摘要和工具结果。不要拿 UI 消息集合证明模型见过同样内容。

## 7. 验收

能解释 prepare/promote/load 为什么是这个顺序、undefined 与 promoted=0 为什么不能随便合并、模型请求为什么不是完整数据库的直接 dump。

所有实验仍为待运行；原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
