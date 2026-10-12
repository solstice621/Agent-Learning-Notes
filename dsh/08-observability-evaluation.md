# DSH 08｜Telemetry：复制、脱敏、交接与错误隔离

[总目录](../README.md) · P2（学习顺序） · 对照：[Codex](../codex/08-observability-evaluation.md) / [OpenCode](../opencode/08-observability-evaluation.md)

**固定源码：** `deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。本篇直接阅读 `session-telemetry/src/coordinator.ts`。没有启动真实遥测后端，没有发送任何日志或个人数据。

## 1. 核心问题

遥测收到日志事实以后，谁负责脱敏、谁负责队列、游标表示已交接还是已送达？失败的观察者会不会阻止后续观察者或主 Agent？

Session ledger、进程本地 live stream 和 telemetry export 不是同一可靠性层。以下源码把 capture 与 backend handoff 分开。

## 2. 核心源码 A：按交接游标读取，而不是无限重放

源码：[`session-telemetry/src/coordinator.ts`，L140–L270](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/coordinator.ts#L140-L270)。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/coordinator.ts#L140-L270 -->
```ts
  captureSession(session: Session, throughSeq?: SessionSeqType): void {
    const start = session.firstLifecycleSeq
    const cursor = handoffCursor.get(session)
      ?? (this.options.includeHistory === true || start === 0 ? -1 : SessionSeq(start - 1))
    // Containment is PER EVENT: one rejected record is withheld fail-closed
    // while the rest of the historical replay proceeds.
    // oxlint-disable-next-line typescript/no-deprecated -- Existing Session history read; migration deferred.
    for (const event of session.snapshotEvents(SessionLogOffset(cursor + 1))) {
      if (throughSeq !== undefined && event.seq > throughSeq) break
      this.contain(() => {
        this.captureEvent(session, event)
      })
    }
  }
```

### 逐段讲解

优先使用同一个 Session 对象的 handoff cursor；没有游标时根据 includeHistory 与本生命周期边界决定起点。读的是 cursor+1 后缀，不是每次热重载都无条件从头重复。

throughSeq 是包含该位置的上限，超过才 break。它用于限制捕获前缀，不是 delivery receipt 或采集授权本身。

contain 按 event 包裹，一个事件被拒绝不阻断后面的扫描。**注意：** 如果后续更大 seq 成功交接，游标前进不表示中间被拒绝事件以后一定补发；这不是无损传输协议。

## 3. 核心源码 B：脱敏与 backend emit，游标只能证明 handoff

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/coordinator.ts#L140-L270 -->
```ts
  private redact(record: SessionTelemetryRecord): SessionTelemetryRecord {
    return this.ctx.waterfall('session-telemetry/record', record, () => record)
  }

  /** Hand one redacted record to the backend, then advance its ledger cursor. */
  private deliver(session: Session, pending: PendingRecord): void {
    this.backend.emit(pending.record)
    if (pending.seq !== undefined) handoffCursor.set(session, pending.seq)
  }
```

### 逐段讲解

redact 的最内层 next 原样返回 record，所以没有部署规则就不是“自动脱敏”。source 的捕获函数对 envelope/data 复制，脱敏针对导出副本，不改 canonical Session log。

emit 返回后推进游标；接口契约要求 emit 非阻塞入队，不能把它理解成网络接收端已持久化。这也解释 handoffCursor 为什么叫 handoff 而不是 delivered。

pending.seq 可缺失：ops 信号没有 ledger 的 event.seq 身份。计数、去重和账单不能把 ops 与 ledger 当同一种精确事件账本。

**文档/源码注意：** captureEvent 附近还有关于 canonical 对象可变性的注释，而当前 Session.append 实际执行快照与 deepFreeze，见 [02](02-context-session.md)。本篇依据实际复制/冻结调用解释边界，不据旧措辞声称日志可任意修改。

## 4. 核心源码 C：观察失败不能冲出捕获边界

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/coordinator.ts#L140-L270 -->
```ts
  private contain(step: () => void): void {
    try {
      step()
    } catch (error) {
      this.ctx.logger.warn(`telemetry: capture step failed: ${String(error)}`)
    }
  }
```

这里隔离同步 capture step 的异常，避免失败后端/规则把异常传播到主 Loop 或后续订阅者。它不是“所有异步 Promise 拒绝都会自动被捕获”：callback 类型是 void，后端必须遵守对应接口。

同文件 teardown 会 await backend.shutdown，并将失败记录为 warning，区别于非阻塞 emit。采集实时路径和停机排空的时延要求不同。

## 5. 质量、隐私与评估

[SessionTelemetry 接口源码](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/index.ts) 区分 sharing mode、capture mode 和 includeHistory；这些开关不是送达保证。完整 Prompt、工具结果和路径都可能敏感，不能把 trace 当可直接公开的调试文本。

评估时分开记录模型尝试、工具执行、结果提交、遥测丢失，不因某条遥测缺失就断言工具未执行。缺失 usage 不填成 0；失败尝试的成本不能忽略。

## 6. 实验与验收

用本地 fake sink：第一条 emit 抛错、第二条成功，观察主 Loop 与游标；装一条抛错的 redaction 规则，确认该记录不交接而后续事件仍处理。再分别在同 Session 对象重采集和新对象重放时观察去重行为。

不启用真实外发；只保存合成记录。验收是一张事实源、授权、脱敏、handoff、delivery、durability 的分层表，明确每层能证明什么。

原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
