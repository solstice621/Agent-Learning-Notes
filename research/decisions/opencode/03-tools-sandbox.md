# OpenCode 03｜工具执行：实现快照与结果表示

模型刚拿到 `read(path)` 的说明，插件就更新了：同名工具现在接受另一套参数。几秒后，模型按旧说明发来调用。如果这时查最新注册表，它选的能力和真正执行的能力就对不上了。

**一次请求把工具说明与执行实现一起保存下来；工具结果再按程序、模型和界面的需要分别表达。**

在 OpenCode 中，工具注册表属于当前工作环境。Runner 准备上下文时取一份工具集合，模型请求保存这份集合的执行入口，随后 Attempt 用它处理模型返回的调用。

<!-- decision: O03-D1 | 工具更新了，正在等待的调用该执行哪个版本？ -->
## 请求内的工具实现快照

`snapshot` 从当前注册表中挑出可见工具，放入自己的 `active` 集合。后面生成说明和执行函数都使用这一份集合。

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool.ts#L225-L235 -->
```ts
      snapshot: Effect.fn("Tool.snapshot")((permissions) =>
        Effect.sync(() => {
          // 笔记：捕获当前注册表版本，后面的工具说明与执行闭包都基于这次读取。
          const data = state.get()
          const active = new Map<string, Tool.Info>()
          const rules = permissions ?? []
          for (const [name, tool] of data.tools) {
            // 笔记：只排除对所有资源禁用的工具；具体文件等资源的权限仍需执行时检查。
            if (whollyDisabled(tool.options?.permission ?? name, rules)) continue
            active.set(name, tool)
          }
          // 笔记：直接暴露给模型的工具和由 Code Mode 调用的工具，来自同一个 active 集合。
          const direct = new Map(Array.from(active).filter(([, tool]) => tool.options?.codemode === false))
          const codeModeTools = new Map(Array.from(active).filter(([, tool]) => tool.options?.codemode !== false))
```

模型返回调用后，[执行入口](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool.ts#L271-L283)从捕获的 `direct` 集合取工具。重新加载插件会影响后续请求，已经发出的请求仍使用旧实现。[上游测试](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/tool-registry.test.ts#L199-L221)直接替换了工具函数并重载，检查旧快照始终返回旧结果。

这样不必让模型猜工具是否换版，但旧请求也会暂时保留旧工具。只有几个静态函数的小脚本，用固定字典就够；动态注册才让请求级捕获有明显价值。

**捕获实现并不等于提前批准操作。** 例如写文件工具在真正修改文件前调用 `permission.assert`；[权限服务](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/permission.ts#L158-L175)会读取会话和 Agent 当前规则。注册表也不自动替任意插件插入权限检查：可信工具要正确发起检查，工具集合本身不能当成操作系统沙箱。

<!-- decision: O03-D2 | 一个工具结果，为什么需要三种表示？ -->
## 工具结果面向程序、模型与界面的表示

假设模型生成一段 JavaScript，让代码调用搜索工具，再筛选返回的一千条记录。这种由代码串起工具调用的方式叫 Code Mode。代码需要数组继续计算，模型需要可读结果，界面可能只需“匹配数量”和状态。因此结果可以有三个部分：

- `output`：经过工具输出编码或校验的机器值，供程序继续计算。
- `content`：给模型看的内容，写入会话历史。
- `metadata`：界面等消费者使用的附加信息。

这不是要求每个工具写三份数据。没有声明结构化输出时，可以只给 `content`；有 `output` 却没有 `content` 时，运行时也能把它转换为文本。

持久化成功结果时，可以看到保存的是 `content` 和可选 `metadata`，没有独立的 `output` 字段：

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/publish-llm-event.ts#L586-L595 -->
```ts
    // 笔记：写入成功事件的是模型可读的 content；机器值 output 不会被自动复制进历史。
    const content = result.content
    if (!isReadonlyArrayNonEmpty(content)) return yield* Effect.die(new Error(`Tool execution has no content: ${id}`))
    yield* bus.publish(SessionEvent.Tool.Success, {
      sessionID: input.sessionID,
      assistantMessageID,
      id,
      content,
      // 笔记：附加展示信息按需保存，让界面取得结构化信息，而不必解析模型文本。
      ...(result.metadata === undefined ? {} : { metadata: result.metadata }),
      executed: tool.providerExecuted,
    })
```

顺着一次调用看：先记录完整调用，再启动本地工具；参数通过校验后进入实现；返回值经处理、必要时缩短给模型的文本，最后发布上面的成功事件。原始机器值可在 Code Mode 内参与计算，最终展示内容由外层结果决定。

分开表示能减少无用上下文，代价是开发者必须保证它们说的是同一件事。若模型摘要写“全部成功”，结构化数据却含失败项，下一轮推理仍会出错。

**想一想：** 将一千条记录放入 `output`，只把匹配数量放入 `content`，下一次模型会自动读到整份数组吗？

<details>
<summary>参考答案</summary>

不会。独立 `output` 不会自动写入成功事件。程序可以主动选择要返回的内容；模型看到的是最终持久化的 `content`。两者不能相互替代。

</details>

本篇核对了注册表、工具运行时、Code Mode、权限、结果发布和相关测试；本轮未运行上游测试。文档与实现的差异另记在本轮研究记录中。
