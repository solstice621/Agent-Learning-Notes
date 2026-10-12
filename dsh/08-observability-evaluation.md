# DSH 08｜可观测性：遥测副本与交付边界

[总目录](../README.md) · [先读导览](../START_HERE.md) · [项目架构](00-architecture.md) · [问题索引](../DESIGN_INDEX.md)

代码中 `// 笔记：` 为新增中文注释，其余保留上游原文。

一次运行产生了第 4、5、6 条事件。第 5 条在脱敏或交给导出后端时失败，第 6 条却成功了。稍后查看监控，你看到了 4 和 6，中间缺了 5。

**遥测是供观察的日志副本，它的交接进度不等于完整送达证明。** 在 DSH 中，会话日志保存运行事实；采集协调器复制这些事实，经过导出处理后交给后端；后端再负责排队与发送。

<!-- decision: D08-D1 | 为什么只改导出的副本，不直接把原日志脱敏？ -->
## 会话日志与导出副本

假设工具结果中有一段内部配置。后续模型请求还要用它，但外部监控只需要错误类型。如果为了监控直接改原日志，下一次重建模型上下文时，这段配置也会消失。

协调器在交给处理规则前，分别复制事件外壳和内容：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/coordinator.ts#L183-L194 -->
```ts
      // 笔记：脱敏处理的是外发记录；应保留原日志供上下文、恢复和追查使用。
      record: this.redact({
        // 笔记：来源外壳也复制，避免导出规则通过共享引用修改原事件。
        sourceEvent: { sessionId: session.id, envelope: structuredClone(envelope) },
        channel: 'ledger',
        time: event.time,
        severity: severityOf(event),
        attributes: identityOf(session, event),
        // The canonical event object is mutable and the backend serializes
        // later; append-time validation guarantees this clone cannot throw.
        // 笔记：正文单独深复制；后端异步序列化不会接触原始内容对象。
        body: structuredClone(data),
      }),
      seq: event.seq,
    })
```

`sourceEvent` 保存来源身份，`body` 是事件内容副本。处理规则只作用在这份外发记录上。[上游测试](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/tests/telemetry.spec.ts#L118-L143)甚至修改了交出去的对象，再检查原日志保持不变。

但“留了脱敏接口”还不等于“已经脱敏”：没有监听规则时，默认原样通过。要删哪些字段，仍由实际装配的规则决定。

还要看清实际入口。协调器支持实时采集，但此版本基础配置使用的 [OTel 后端](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry-otel/src/index.ts#L203-L242)选择按需采集：本会话新提交的显式反馈，才授权读取截至该反馈的日志前缀。不能看到协调器有实时订阅能力，就认为部署一直在上传会话。

<!-- decision: D08-D2 | 游标已经到 6，为什么第 5 条仍可能没送到？ -->
## 导出游标与逐条送达的差异

每条记录交接时，代码先调用后端，再更新游标：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/coordinator.ts#L209-L213 -->
```ts
  /** Hand one redacted record to the backend, then advance its ledger cursor. */
  private deliver(session: Session, pending: PendingRecord): void {
    // 笔记：emit 只把记录交给后端队列；成功返回不是远端送达确认。
    this.backend.emit(pending.record)
    // 笔记：游标跟随成功交接项前进，不能证明更早的每一项都已成功。
    if (pending.seq !== undefined) handoffCursor.set(session, pending.seq)
  }
```

`emit()` 的契约是快速放入后端队列。它返回时，网络发送可能还没开始。因此游标到 6，连第 6 条是否抵达服务端都不能证明。

再看第 5 条为什么会留下缺口：采集过程[逐条捕获异常并继续](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/coordinator.ts#L151-L163)。第 5 条失败后，第 6 条成功将游标推进到 6；下一次读取从游标加一开始，也就是从 7 开始。对同一个 Session 对象，这条路径不会自动回补 5。

这样做让一条坏记录不至于堵住后续观测，也让导出故障不影响 Agent 主任务。如果要求可靠账本，就要另加持久发送队列、逐项确认、缺口重试和去重。只在 `emit()` 外包一层重试，仍处理不了进程崩溃后的未送达记录。若只需要健康趋势，接受部分丢失通常更简单。

## 遥测数据的评测适用范围

`ledger` 是会话事件副本，`ops` 是错误、关闭等运行信号，实时文本片段则服务于界面显示。把三者一起数，可能重复计数；没有收到错误事件，也不能据此判断运行成功。答案质量还需要题目与评分标准，遥测主要帮助解释过程。

[上游测试](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/tests/telemetry.spec.ts#L340-L351)明确允许后端拒绝中间一条后仍收到后续记录。本次已读源码与测试，未重跑；“下次跳过缺口”是结合游标与回放起点得出的代码推论，测试本身没有执行第二次补采。

## 自测

后台说“已经处理到第 100 条”，能否据此把 0–100 全部作为评测样本？

<details>
<summary>展开答案</summary>

不能。先区分处理、入队与远端收到，再检查序号缺口和重复；还要确认哪些会话进入了采集范围。交接游标提供进度线索，完整性需要额外证据。

</details>

---

固定源码：`deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`｜研究日期：2026-10-12。

[源码重读记录](../research/reread/dsh-05-08.md) · [研究方法与验证边界](../RESEARCH_METHOD.md) · [源码归属与许可](../THIRD_PARTY_NOTICES.md)
