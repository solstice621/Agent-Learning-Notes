# DSH 02｜上下文管理：事件日志与模型视图

[总目录](../README.md) · [先读导览](../START_HERE.md) · [项目架构](00-architecture.md) · [问题索引](../DESIGN_INDEX.md)

代码中 `// 笔记：` 为新增中文注释，其余保留上游原文。

Agent 读了几十个文件，下一次请求装不下全部内容，于是把前半段历史换成摘要。后来它漏掉一个要求：我们需要查清，是原文没有写，还是摘要漏掉了。

**要点：保存“发生过什么”，和决定“下一次给模型看什么”，可以用两份不同的视图。**

DSH 的 `Session` 保留只追加的事件日志；`Surface` 列出当前对模型有效的消息位置；`deriveMessages()` 再把这些位置变成真正的消息数组。默认循环构造每次请求时调用它，而不是直接把全部日志发给模型。

<!-- decision: D02-D1 | 为什么日志和当前上下文要分开？ -->
## Session 日志与 Surface 上下文视图

假设事件 0、1、2 分别产生消息 A、B、C，当前 Surface 是 `[0, 1, 2]`。追加事件 3，把 A、B 总结成 S 后，日志里四个事件都在，Surface 变成 `[3, 2]`，下一请求看到 S、C。

处理替换时，代码改的是 Surface 的位置列表：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/surface.ts#L567-L576 -->
```ts
  // 笔记：nodes 保存模型阅读顺序；seq 只是原事件的位置，不是排序依据。
  if (plan?.kind === 'append') {
    state.nodes.push(plan.seq)
  } else if (plan?.kind === 'replace') {
    // 笔记：把原来的连续范围换成一个新节点，旧事件仍在 Session 日志中。
    state.nodes.splice(plan.startIdx, plan.endIdx - plan.startIdx + 1, plan.seq)
    state.replaceGeneration += 1
    // 笔记：已有内容改变，通知消息缓存失效；普通尾部追加不用走这一步。
    state.contentGeneration += 1
  } else if (plan?.kind === 'project') {
    for (const [seq, message] of plan.messages) state.projectedMessages.set(seq, message)
    state.projections.add(plan.projection)
    // 笔记：已有内容改变，通知消息缓存失效；普通尾部追加不用走这一步。
    state.contentGeneration += 1
```

这里的 `contentGeneration` 可以理解为“旧内容改过几次”。普通追加只增加尾部节点；替换或修改已有内容时，版本号递增，提醒消息缓存重新计算。

这个例子还有个容易踩的坑：`[3, 2]` 是正确顺序。摘要的日志编号较新，却放在被替换内容原来的位置。继续压缩时，要沿当前 Surface 找范围，不能拿事件编号的大小代替消息顺序。

为什么不直接修改 `messages`？直接改最简单，但旧内容和替换过程会消失。保留日志便于回看、恢复和追查摘要问题。为免调用者事后篡改原对象，`append` 会先复制、校验并冻结数据。代价则是旧数据仍占空间，读取时还需要一层重建逻辑。

<!-- decision: D02-D2 | 有了增量缓存，读取历史为什么仍有成本？ -->
## 增量投影缓存与消息复制成本

如果只追加 D，已有 A、B、C 的消息对象可以复用，只转换新节点；如果发生上面的摘要替换，版本号变化就清空缓存重建。处理新增节点后，函数这样返回：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/index.ts#L993-L1004 -->
```ts
    // 笔记：缓存仍有效时，只转换上次读取之后新增加的 Surface 节点。
    for (const seq of nodes.slice(this.derivedNodes)) {
      // Surface sequences are built from this.log — seq is always a valid
      // index by construction. The non-null assertion expresses that invariant.
      // oxlint-disable-next-line typescript/no-non-null-assertion
      const msg = this.deriveEventMessage(this.log[seq]!)
      // A surface node is one of the five message-producing types, but an
      // empty-content assistant/message (a max-tokens step that hosts only
      // usage) derives to null and must not enter the transcript.
      // 笔记：只带用量的空回复不进入模型历史，跳过 null。
      if (msg) this.derived.push(msg)
    }
    this.derivedNodes = nodes.length
    // 笔记：返回新数组以隔离调用方，但会复制全部引用，因此读取仍有 O(N) 成本。
    return [...this.derived]
```

`return [...this.derived]` 是关键：每次给调用者一张新列表，里面共享已经冻结的消息对象。你上次拿到的列表，不会因为 Agent 又说了一句话而突然变长；也不用每次深拷贝所有正文。

但新列表仍要复制所有消息引用。若当前有 N 条消息，返回列表就有 N 次引用复制。假设每新增一条都读取完整历史，总复制量是 1＋2＋…＋N。这说明缓存省下的是旧消息的转换工作，不能据此把整个读取过程说成“只花新增部分的时间”。模型请求还要序列化，是否值得优化，要实际测量。

如果只关心当前状态，简单消息数组配合快照更容易维护。确实需要压缩后追溯、分叉与重放时，日志和 Surface 的分工才更有价值。

<details>
<summary>源码与核对范围</summary>

已静态核对[Session 的定位](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/session.md#L1-L5)、[追加与冻结](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/index.ts#L798-L826)、[请求消费方](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L684-L703)。上游[缓存测试](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/tests/derived-cache.spec.ts#L66-L96)确实检查“替换后重建等于从头推导”和“旧数组不变”；[Surface 测试](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/tests/surface.spec.ts#L329-L356)覆盖替换后的非递增编号。本轮未运行上游测试。旧文误称本仓库独立机制实验已覆盖 replacement 失效，这里更正：该实验只对比投影与引用复制成本。Session 的内存追加也不等于磁盘写入完成。

</details>

**小自测：** 新摘要编号是 9，替换掉当前第一条消息后，Surface 能否以 `[9, 4, 7]` 开头？还能用编号递增来排序吗？

<details>
<summary>参考答案</summary>

可以。Surface 保存的是模型阅读顺序，9 占据被替换消息的位置。按编号排序会把摘要移到后面，改变真实上下文。

</details>

---

固定源码：`deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`｜研究日期：2026-10-12。

[源码重读记录](../research/reread/dsh-01-04.md) · [研究方法与验证边界](../RESEARCH_METHOD.md) · [源码归属与许可](../THIRD_PARTY_NOTICES.md)
