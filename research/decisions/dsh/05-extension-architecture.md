# DSH 05｜扩展架构：执行环境与资源清理

模型先用 `read` 查看远程工作区里的配置，再让 Bash 运行测试。如果 Bash 仍在本机执行，两次调用都可能成功，但它们处理的是两份不同的项目。路径都叫 `/workspace`，也不能说明文件相同。

**换能力时，要一起换清楚“在哪里执行”和“谁负责收尾”。** DSH 启动时按 profile 装配插件树；工具使用树上提供的服务。这里先看文件与进程，再看创建过程被取消后留下的资源。

<!-- decision: D05-D1 | 为什么换一个工具，还没有换好整个执行环境？ -->
## 文件系统与进程服务的一致性

`read` 负责参数、读取窗口和结果格式，具体读取交给 `ctx.fs`。下面这段里没有写死本地文件 API：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/fs/tool-fs/src/read.ts#L137-L147 -->
```ts
    async execute(args, exec) {
      // 笔记：工具解释参数；真实文件操作交给 ctx.fs 提供的执行环境。
      const input = parseReadArgs(args, caps.limit)
      // One stat: absence observation OR type check + size routing + present version.
      // A concurrent write can only make a later guarded mutation fail stale and require reread.
      const { target, info } = await resolveRegularReadTarget(ctx, exec, input.filePath)

      // Stream when the file is large OR size is unknown, so a size-less backend
      // never buffers an arbitrarily large file.
      // 笔记：大小未知也走流式读取；两条分支都把取消信号传到同一个文件服务。
      const chunks = info.size === undefined || info.size >= caps.streamMinSize
        ? await ctx.fs.streamText(target, exec.signal)
        : [await ctx.fs.readText(target, exec.signal)]
```

大文件走流式读取，小文件直接读；两条分支都经过同一个文件服务。另一方面，Bash 的本地实现最终调用 [`ctx.subprocess.spawn()`](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/shell/bash-local/src/index.ts#L251-L263)。因此，远程环境需要提供相配套的文件服务和进程服务，让“读到的代码”就是“执行的代码”。

这就是文档里 Definition、Provider、Consumer 的意思：**接口规定能做什么，实现决定在哪里做，工具把能力交给模型使用。** [`processPath()` 的接口](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/fs/fs/src/index.ts#L134-L142)还明确要求返回同一执行环境里的进程能打开的路径。

只改 `read` 的内部实现，其他文件工具仍可能读本地；只换文件服务，Bash 仍可能跑本地。服务分层让替换能覆盖多个消费者，但配套装配仍是部署者的责任。一个固定在本机运行的小程序，直接传入文件与进程对象就够了，不必先建设动态插件树。

<!-- decision: D05-D2 | 已经取消创建，为什么还要处理迟到的资源？ -->
## 取消创建后的资源清理

恢复一个 Agent 时，DSH 先向存储申请写入句柄。假设申请还没返回，用户就关闭了所属插件。系统应及时结束等待；但存储随后仍可能返回一个已经占有写权限的句柄。

如果只让等待者抛错，这个句柄就无人关闭。`raceAbortCall` 留下了一条收尾路径：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L189-L198 -->
```ts
  // 笔记：保存原始创建任务；取消等待并不保证这个任务本身也停止。
  const pending = Promise.resolve().then(operation)
  try {
    // 笔记：正常返回创建结果，取消则让当前调用方及时退出。
    return await raceAbort(pending, signal, id)
  } catch (error: unknown) {
    // oxlint-disable-next-line typescript/no-unnecessary-condition -- the signal can abort while the operation is awaited.
    if (signal.aborted && releaseAbandoned !== undefined) {
      // 笔记：若资源迟到，继续交给清理回调；这个清理不会被本次 catch 等待。
      void pending.then(releaseAbandoned, () => undefined)
    }
    throw error
  }
```

读法是：正常时返回资源；取消时先结束本次等待，同时继续关注原来的 Promise。它将来成功了，就把值交给 `releaseAbandoned`。在实际的[恢复调用处](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L875-L883)，这个函数会调用迟到句柄的 `close()`。

这里的两个动作各管一件事：取消让调用方及时退出，关闭让存储重新释放写权限。要求所有后台创建先结束才允许取消，会拖慢退出；彻底不管后台结果，则可能泄漏资源。

[上游测试](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/tests/config-session-id.spec.ts#L335-L366)专门先卸载 AgentLoop，再让模拟的 `open()` 返回，检查迟到句柄被关闭。本文已阅读该测试，未在本次重跑。清理被安排执行，也不等于清理已经成功；这条迟到回调不由前面的取消等待同步完成。

## 自测

把文件服务换成远程版后，Bash 还是本地版；随后取消了一个尚未返回的写句柄申请。这里有哪两个独立问题？

<details>
<summary>展开答案</summary>

第一个是执行环境不一致：模型读到的文件与命令使用的文件不同。第二个是资源所有权丢失：申请虽被取消，迟到句柄仍须有人关闭。统一接口解决调用方式，完整装配与生命周期处理才能分别解决这两个问题。

</details>
