# OpenCode 04｜LLM / Retry：预算、延迟和插件覆盖

[总目录](../README.md) · P0 · 对照：[Codex](../codex/04-llm-streaming.md) / [DSH](../dsh/04-llm-streaming.md)

**固定源码：** `anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。本篇将 retry 的实际代码作为默认策略依据；未运行真实 provider 或时间测试。

## 1. 先处理文档与源码差异

同一提交的 [Session 文档](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/session.md) 写最多 4 次重试，而下面 `retry.ts` 使用 `Schedule.recurs(10)`。此外 timeout 另有限额，hook 可以改变决策。笔记保留这个差异，不把二者混成一个所谓当前默认值。

## 2. 核心源码 A：基础 backoff 与 provider 延迟分开

源码：[`session/runner/retry.ts`，L25–L109](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/retry.ts#L25-L109)。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/retry.ts#L25-L109 -->
```ts
const schedule = Schedule.max([
  Schedule.min([Schedule.exponential("2 seconds"), Schedule.spaced("10 seconds")]),
  Schedule.recurs(10),
]).pipe(
  Schedule.jittered,
  Schedule.setInputType<Input>(),
  Schedule.modifyDelay(({ input, duration: delay }) => {
    const minimum = retryAfter(input)
    const duration = minimum === undefined ? delay : Duration.max(delay, Duration.millis(minimum))
    return Effect.succeed(Duration.millis(Math.ceil(Duration.toMillis(duration))))
  }),
)
```

### 逐段讲解

按这段源码及其上方说明，基础指数间隔从 2 秒开始并受 10 秒间隔上限约束，次数另由 recurs 限定；jitter 使等待不完全同步。不要孤立按 JavaScript 的 Math.min/max 猜 Effect Schedule 的组合语义，应结合这里的代码注释与库版本。

`modifyDelay` 又把 provider 的最短等待与基础等待取更大值。因此“基础间隔最多 10 秒”不等于最终每次等待最多 10 秒。Retry-After 上界在独立函数中处理。

**设计分析：** 分离次数、基础节奏和 provider 反馈，能够避免瞬时错误引发请求风暴，也能限制无界等待。它仍不是端到端任务 deadline，因为单次请求本身也可能很慢。

## 3. 核心源码 B：只接受有界的 provider Retry-After

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/retry.ts#L25-L109 -->
```ts
const RETRY_AFTER_MAX = Duration.toMillis("15 minutes")

const retryAfter = (input: Input) => {
  if (input.cause.reason._tag === "RateLimit" || input.cause.reason._tag === "ProviderInternal")
    return input.cause.reason.retryAfterMs === undefined
      ? undefined
      : Math.min(input.cause.reason.retryAfterMs, RETRY_AFTER_MAX)
  return undefined
}
```

这里只对特定错误类型提取 provider 延迟。字段不存在就交回 undefined，让基础计划决定。上限约束的是这条 provider 输入路径，不是后面任意插件产生的 delay；不要把它误写成绝对全局最大值。

这个分支也说明失败分类属于协议的一部分。把所有异常变成字符串，会丢失可用来制定恢复策略的信息。

## 4. 核心源码 C：默认预算之后还有 hook 和数值规范化

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/retry.ts#L25-L109 -->
```ts
        attempt++
        if (isTimeout(input.cause)) timeouts++
        const delay = Math.ceil(Duration.toMillis(duration))
        const event: PluginHooks.Domains["session"]["retry"] = {
          sessionID,
          agent: input.agent,
          model: input.model,
          error: input.error,
          attempt,
          decision: input.retry && timeouts <= MAX_TIMEOUT_RETRIES ? { retry: true, delay } : { retry: false },
        }
        yield* input.hook(event)
        if (!event.decision.retry) return event.decision
        const normalized =
          Number.isFinite(event.decision.delay) && event.decision.delay >= 0 ? Math.ceil(event.decision.delay) : delay
        return { retry: true as const, attempt, delay: normalized }
```

### 逐段讲解

attempt 与 timeouts 是两种计数。文件里的 MAX_TIMEOUT_RETRIES 为 3，表达 timeout 的额外默认约束，而不是把所有错误统一压成三次。

先构建默认 decision，再 await hook，然后读取可能改变后的 decision。因此准确描述必须是“默认策略 + 当前插件覆盖”，不能只看常量就承诺实际行为。

最终 delay 检查有限且非负，非法值回退到原 delay。这个检查没有在本段重新施加 15 分钟全局上限；若要对插件也限制，必须有额外策略，不能自行补上不存在的代码。

## 5. 与流式输出的联系

[03](03-tools-sandbox.md) 展示 provider stream 读到结束并启动工具 Fiber；[01](01-agent-loop.md) 展示 Step 内部多次 attempt 的边界。可重试传输失败与已有 durable output 后的继续不是一回事：不能删除已经展示/记录的部分回答，把有副作用的调用当作没发生。

本篇精读 retry 决策代码；完整的 Retry/Continue/RecoverFull 分派应继续读 `runner/step.ts` 和 `runner/llm.ts`，不从 backoff 函数推导 exactly-once。

## 6. 实验与验收

使用 mock clock 记录基础间隔、jitter、provider Retry-After、timeout 计数，再装一个覆盖 decision 的 hook。分别输入合法、负数、NaN 和超长 delay，记录最终返回而不是只看配置值。

再用 mock stream 在输出前与部分输出后失败，记录 logical Step、assistantMessageID、physical attempts 与工具效果次数。验收矩阵应区分“失败可重试吗”与“重试会重复什么”。

所有实验尚未运行；原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
