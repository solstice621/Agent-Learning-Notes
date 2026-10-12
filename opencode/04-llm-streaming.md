# OpenCode 04｜为什么重试必须看“已经提交了什么”，而不只看错误码？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 相同网络错误可能意味着不同业务状态

连接在任何输出前断开，与输出文本、工具调用之后断开，都可能被上层看到为 transport failure。对普通只读请求，重发或许问题不大；Agent 可能已经把一部分回答持久化、启动工具，甚至向外界产生效果。

SessionStep.attempt 根据 outputStarted、provider 错误、工具终态等选择 Retry、Continue、RecoverFull、Compacted 或 Completed；重试政策本身在独立 retry.ts。[F1][F2] 因此本篇研究的是重做边界，而不是某组延迟参数。

## 2. 决策 O04-D1：为什么 Retry 与 Continue 不是同一种循环？

**反事实：** 第一次响应已经运行“写测试文件”，随后流中断。若上层把这次尝试全部丢掉，再用原始 prompt 重发，模型可能再次执行同一动作。若保留所有半成品又把未完成参数当可执行调用，会出现另一种错误。

| 失败位置 | 应询问的事实 | 不能盲目采取的动作 |
|---|---|---|
| 尚无 durable output | 是否有服务端续接状态、是否已经生成未知效果 | 无限制重复整个输入接纳 |
| 有已保存文本 | 是否允许从已有内容继续 | 把前缀当作从未发表 |
| 已有本地 tool-call | handler 是否启动、结果是否结算 | 仅依据 transport error 重跑工具 |
| provider-hosted 调用缺结果 | 服务端是否执行未知 | 本地自动补执行 |

表是研究决策框架，不是所有分支的实际保证。源码明确处理不完整工具参数、缺失 hosted result、未知 finish reason，并保护末尾结算。[F1] “工具输入不完整未执行”与“结果未知”应区分：前者能说明当前本地 handler 没有被调用，后者不能证明外部效果不存在。

为什么要读完整 stream 而不在 finish 处停止？源码注释说明后续请求可能还需复用响应状态。[F1] 提前停止会把语义终止与传输收尾混在一起；但无限等待一个坏 provider 同样不可接受，因此超时与取消要由相应层落实。

## 3. 决策 O04-D2：为什么默认退避策略不是不可更改的安全上限？

retry.ts 的默认 schedule 有次数限制、指数间隔、jitter、Retry-After 上限以及超时单独计数；之后会调用插件 retry hook，再读取最终 decision。[F2] 文档旧描述与实现数字不同，研究以固定源码为准。

**本轮重点推导：** 设定默认 `timeouts <= MAX_TIMEOUT_RETRIES` 后仍允许 hook 改 decision，说明这个 timeout 限制属于默认政策，不是能约束任意可信插件的硬安全边界。不能把注释中的默认总等待估算，写成整个任务的最长执行时间。schedule 本身耗尽与 hook 能改变的本次 decision 也应区分，不能反过来说“插件可以突破任何上限”。

| 政策结构 | 适用目标 | 风险 |
|---|---|---|
| 全部硬编码 | 简单且统一 | provider 差异难适配 |
| 全由插件决定 | 可按服务调优 | 行为不可预测、成本失控 |
| 默认政策＋扩展决定 | 通用与特殊情况兼容 | 必须说明哪些上限只是建议 |
| 默认＋不可放宽的最终预算守卫 | 多租户成本与时限控制 | 需要额外统一预算、错误语义和所有权 |

最后一项是平台设计建议，不是断言当前系统缺陷或已存在该守卫。可信插件本来就有较大能力，不能把政策可覆盖本身描述为漏洞。

## 4. 重试的代价必须按全任务计算

每次等待前请求可能已经耗费数分钟；provider Retry-After、hook 修改与网络超时都会改变总时间。多个层次各自重试还可能放大物理请求量。因此应跟踪总 deadline、尝试数、已提交输出、工具 invocation 和累计成本，而不是仅数最后成功响应的 token。

jitter 的研究理由是减少相似任务同时重试的同步效应；但本篇没有压测服务端，也不声称当前默认参数最优。一次瞬时故障可能适合重试，持续权限拒绝或不兼容参数则应尽快显式失败。

## 5. 验证与反证

**上游实验待运行：** 用 mock clock 检查默认 schedule；安装一个修改 retry decision 的 hook，观察哪些预算仍然约束它；对 outputStarted 前后分别断流，核对 assistant ID、已保存结果和工具执行次数。不要用真实付费 API 制造大量失败来验证控制逻辑。

本仓库机制实验只展示“先设置默认拒绝、再允许 hook 覆盖”与“最终硬守卫”在一个抽象例子中不同，不使用 Effect，也不验证 OpenCode 所有 schedule 语义。

应能说明何时是安全重试、何时只能继续、何时必须报未知结果，以及哪些默认限制适合产品体验、哪些约束需要位于不可绕过的运行时边界。

[F1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L145-L290
[F2]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/retry.ts#L1-L150

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：基础 backoff 与 provider 延迟分开

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

#### 逐段讲解

按这段源码及其上方说明，基础指数间隔从 2 秒开始并受 10 秒间隔上限约束，次数另由 recurs 限定；jitter 使等待不完全同步。不要孤立按 JavaScript 的 Math.min/max 猜 Effect Schedule 的组合语义，应结合这里的代码注释与库版本。

`modifyDelay` 又把 provider 的最短等待与基础等待取更大值。因此“基础间隔最多 10 秒”不等于最终每次等待最多 10 秒。Retry-After 上界在独立函数中处理。

**设计分析：** 分离次数、基础节奏和 provider 反馈，能够避免瞬时错误引发请求风暴，也能限制无界等待。它仍不是端到端任务 deadline，因为单次请求本身也可能很慢。

### 3. 核心源码 B：只接受有界的 provider Retry-After

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

### 4. 核心源码 C：默认预算之后还有 hook 和数值规范化

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

#### 逐段讲解

attempt 与 timeouts 是两种计数。文件里的 MAX_TIMEOUT_RETRIES 为 3，表达 timeout 的额外默认约束，而不是把所有错误统一压成三次。

先构建默认 decision，再 await hook，然后读取可能改变后的 decision。因此准确描述必须是“默认策略 + 当前插件覆盖”，不能只看常量就承诺实际行为。

最终 delay 检查有限且非负，非法值回退到原 delay。这个检查没有在本段重新施加 15 分钟全局上限；若要对插件也限制，必须有额外策略，不能自行补上不存在的代码。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/opencode/04-llm-streaming.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
