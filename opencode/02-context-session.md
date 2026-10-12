# OpenCode 02｜上下文管理：指令准备与历史裁剪

[总目录](../README.md) · [先读导览](../START_HERE.md) · [项目架构](00-architecture.md) · [问题索引](../DESIGN_INDEX.md)

代码中 `// 笔记：` 为新增中文注释，其余保留上游原文。

你提交“按项目规范修测试”，服务器成功保存了消息，但项目指令暂时读不到。此时直接向模型发送空白规则，看起来任务启动了，实际却换成了另一道题。

**收到输入、递送输入、组装模型请求，是三个步骤。OpenCode 先建立可用的初始指令，再让待处理输入进入会话历史。**

这段逻辑位于 Core 的 Runner。入口负责把消息存好；Runner 每次准备模型工作时，选择当前 Agent、工具和指令，然后加载模型与本轮需要的历史。

<!-- decision: O02-D1 | 项目指令还没准备好，要先取走用户消息吗？ -->
## 初始指令准备与输入递送顺序

下面按执行顺序读就够了：先 `prepareContext`，再 `promote`。前者会建立指令状态，后者把待处理消息正式放入模型可见历史。

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L165-L173 -->
```ts
                  // 笔记：先建立初始指令基线；这里失败时，下面的 promote 不会取走待处理输入。
                  const selected = yield* prepareContext(sessionID)
                  const promoted = yield* SessionInbox.promote(
                    db,
                    bus,
                    sessionID,
                    entering && !continuing ? promotable : "steer",
                  )
                  // A control admitted during context preparation owns this boundary.
                  // 笔记：准备期间若插入了移动、压缩等控制项，就交回步骤边界重新处理顺序。
                  if (promoted === undefined) return undefined
```

初始指令不可用时，第一行就失败，后面的输入递送不会发生。用户消息仍留在队列中；指令恢复后可继续处理。[上游测试](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-runner.test.ts#L1260-L1286)还检查了这个场景没有发出模型请求。

这比“先取走，失败后再塞回去”少一套补偿逻辑。不过它只把初始指令这个前提放到了递送之前；后续加载模型等操作仍可能失败，并不意味着整段执行变成一个事务。

还有一个容易漏掉的细节：**首次读不到规则和后来暂时读不到，处理不同。** 已经存有指令时，[指令差异计算](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/instructions/index.ts#L142-L158)会保留旧值；首次没有基线时才阻塞。这个选择保住了连续工作能力，代价是短暂沿用旧规则，而不是默默使用空规则。

<!-- decision: O02-D2 | 历史太长时，为什么不能直接删掉旧消息？ -->
## 完整历史与模型上下文视图

修测试进行了几十轮后，模型未必还需要每段旧日志。OpenCode 的压缩会保存摘要与近期内容；支持原生压缩的模型也可以返回专用的替代窗口。这里的“窗口”是替代旧历史、交给下一请求的一组内容。完整会话记录和本次送给模型的内容因此分开了。

读取本轮历史时，代码先找可用的压缩点，再只取这个位置之后的记录：

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/history.ts#L83-L95 -->
```ts
  // 笔记：先选出当前边界可用的压缩点，把它作为本次模型历史的起点。
  const compaction = yield* latestCompaction(db, sessionID, boundary)
  const rows = yield* db
    .select()
    .from(SessionMessageTable)
    .where(
      and(
        eq(SessionMessageTable.session_id, sessionID),
        // 笔记：只限制本次读取的序号范围，不删除数据库中的旧消息。
        compaction ? gte(SessionMessageTable.seq, compaction.seq) : undefined,
      ),
    )
    .orderBy(asc(SessionMessageTable.seq))
    .all()
    .pipe(Effect.orDie)
```

注意这里是查询条件 `gte`，没有删除旧记录。摘要作为新的起点，后续消息继续接在后面。Runner 看到压缩成功，就重新加载上下文，再发请求；否则刚做好的摘要根本不会进入这次调用。

压缩也改变了模型应当接着什么内容工作。普通文本摘要与服务商提供的专用压缩内容不是同一种表示：前者用文字概括旧历史，后者可能依赖特定模型、协议和部署来源，换模型后不能直接照搬。

[源码说明](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/provider-context.ts#L38-L54)还把这种持久窗口与传输续接状态分开：压缩结果是请求材料，而 response ID 相当于告诉服务商“接着上次”。后者能否复用，还要[检查新请求是否仍是上次内容的追加](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/ai/src/protocols/open-responses-continuation.ts#L96-L108)。

简单的固定窗口更容易实现，但可能剪掉任务约束或工具调用的前半段；摘要能保留更多语义，却需要额外请求，也可能遗漏信息。选择依据应是任务需要记住什么，而不只是少发多少 token。

**自检：** 压缩完成后，用户还能查看旧工具结果吗？下一次模型请求必须重新发送所有旧结果吗？

<details>
<summary>参考答案</summary>

完整历史仍保留，所以可以继续查看。模型请求通常从适用的压缩点重建；若原生窗口与新模型不兼容，则需要重新选择可用历史，不能直接照搬该窗口。

</details>

本篇核对了指令准备、历史查询、压缩实现与相关测试；本轮未运行上游测试，也未测量摘要质量或 token 节省。

---

固定源码：`anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`｜研究日期：2026-10-12。

[源码重读记录](../research/reread/opencode-01-04.md) · [研究方法与验证边界](../RESEARCH_METHOD.md) · [源码归属与许可](../THIRD_PARTY_NOTICES.md)
