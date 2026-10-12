# OpenCode 08｜事件推送：订阅者队列与积压隔离

[总目录](../README.md) · [先读导览](../START_HERE.md) · [项目架构](00-architecture.md) · [问题索引](../DESIGN_INDEX.md)

代码中 `// 笔记：` 为新增中文注释，其余保留上游原文。

你开了三个终端看同一台 Agent 服务。其中一个网络卡住，另两个还在正常接收工具进度。此时最糟糕的结果，是服务为了等那个慢窗口，把所有进度发布都停下来。

**OpenCode 把一条事件只编码一次，再分别放进每个连接自己的队列；谁积压过多，就断开谁。**

Core 的 Bus 负责发布事件和更新数据库投影，完整事件日志是否保留取决于配置；Server 的 `EventFeed` 负责把公开事件转成实时推送。HTTP 处理器再加上连接通知和心跳，送到各个客户端。

<!-- decision: O08-D1 | 既然大家看同一条消息，为什么还要各自排队？ -->
## 事件编码复用与独立订阅队列

有十个窗口，不必把同一事件做十次 JSON 编码。Feed 先过滤内部事件；没有订阅者时直接返回；否则只在遍历连接之前编码一次：

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/event-feed.ts#L48-L54 -->
```ts
  const publish = Effect.fnUntraced(function* (event: Event.Payload) {
    // 笔记：先过滤内部事件，只有公开协议允许的事件才进入客户端推送。
    if (!isOpenCodeEvent(event)) return
    if (subscribers.size === 0) return
    // 笔记：在遍历订阅者之前只编码一次；无人订阅时连这次编码也省略。
    const encoded = yield* Effect.try({
      try: () => render(event),
      catch: (cause) => new EncodingError({ eventID: event.id, eventType: event.type, cause }),
    }).pipe(
```

随后各队列保存同一个不可变字符串的引用。大家共用已经生成的内容，却分别记录自己还有多少条没消费。

为什么不直接换成一个共享发布队列？因为所需规则很具体：快连接继续，慢连接单独失败。普通共享有界队列可能让最慢订阅者反过来阻塞发布者；滑动队列又可能悄悄跳过旧消息。要在共享结构里实现单独淘汰，还需维护游标、清理和失败通知。

当前方案接受每个连接各占一些队列槽位，换来较简单的隔离逻辑。编码省掉了重复工作，但遍历连接、向网络写数据仍随连接数增长。

<!-- decision: O08-D2 | 为什么宁可断开，也不偷偷丢一条？ -->
## 慢订阅者断开与丢失提示

队列放不进去时，代码没有等待空间，也没有当作成功：

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/event-feed.ts#L63-L68 -->
```ts
    // 笔记：编码失败已在前面的分支通知所有当前订阅者，这里不再投递坏事件。
    if (encoded === undefined) return
    for (const subscriber of subscribers) {
      // 笔记：非阻塞地投递到每个连接自己的队列，快连接不会等待慢连接腾出空间。
      if (Queue.offerUnsafe(subscriber, encoded)) continue
      // 笔记：入队失败就移除并报错该订阅者，让积压暴露出来，而不是悄悄漏掉状态变化。
      subscribers.delete(subscriber)
      Queue.failCauseUnsafe(subscriber, Cause.fail(new SubscriberOverflowError({ capacity })))
    }
```

它先移除这个订阅者，再让队列报溢出错误；其他连接仍收到这条事件。默认上限是 4,096 条，限制的是事件数。一条事件可能很大，HTTP 和系统网络缓冲也在队列之外，所以它不是整个服务的内存上限。

为什么不跳过一条继续？如果丢的是“工具执行结束”，界面可能永远显示运行中。断开能暴露状态已不完整，让客户端重新同步。这里提供实时消息；断线期间错过的事件，不会因为重新连上就自动补齐。

还有一种失败范围更大：同一条公开事件编码失败。所有当前连接都会缺这条事件，因此 Feed 会让**全部当前订阅者**失败，跳过坏事件，继续接受新连接。相关分支见[失败处理](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/event-feed.ts#L41-L63)。这和只影响一个慢连接的队列溢出不同。

## 运行观测与任务质量评估

这些机制帮助我们观察进度、发现断流。判断 Agent 质量，还得检查实际产物：一次补丁任务可以顺利结束、所有事件正常送达，测试却仍然失败。

因此评估至少分开看两件事：传输是否正常，任务是否通过验收。文档中的编码微基准只比较编码开销；它没有测完整网络链路，也没有证明 Agent 解题更快、更准。这里只把它当作优化编码的依据。

若只是显示可被新值覆盖的温度，滑动队列就很简单；若要保留工具状态变化的顺序，显式报错更稳妥；若要求离线期间也不漏消息，需要另加持久记录与重放协议。

**小自测：** 慢连接溢出和事件编码失败，各影响哪些连接？收到“执行成功”事件，能否给代码任务判满分？

<details>
<summary>展开答案</summary>

前者只影响慢连接，后者影响所有当前连接。执行成功只说明流程正常结束，代码仍需测试和任务要求验收。

</details>

> 证据边界：已读 Feed、HTTP 入口、公开协议与快慢订阅者测试，未运行测试或基准。当前源码使用公开事件过滤与 JSON/SSE 编码，按实现解释，未照搬历史文档中的编码步骤。

---

固定源码：`anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`｜研究日期：2026-10-12。

[源码重读记录](../research/reread/opencode-05-08.md) · [研究方法与验证边界](../RESEARCH_METHOD.md) · [源码归属与许可](../THIRD_PARTY_NOTICES.md)
