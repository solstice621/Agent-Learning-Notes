# Codex 04｜为什么连接复用、请求续接与身份归属必须分开？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 朴素方案能解决什么，又留下什么？

每一步新建 HTTP 请求并发送全部历史，容易理解、容易抓包、对本地连接状态依赖少。它并不天然错误。长任务反复发送增长历史时，可能有请求大小和连接成本问题，但本轮没有量化它们，也不把连接复用等同于 token 费用下降。

另一极端是保留一个全局 WebSocket，永远带上上一 response ID。这看似省事，却把三个对象混在一起：可用连接、同一业务 Turn、与当前输入相容的服务端状态。源码用 ModelClient、ModelClientSession、WebsocketSession 等不同生命周期表达这些差异。[F1]

## 2. 决策 C04-D1：为什么 sticky routing 放在 Turn，而不是全 Session？

源码注释明确要求一个 Turn 使用新的 ModelClientSession：`x-codex-turn-state` 在同一 Turn 的重试、追加和继续之间复用，不能跨不同 Turn 重放；认证所有权变化时也要清理。[F1] 这是**作者在代码中写出的协议理由**，不是“OnceLock 性能更好”这种猜测。

**推导的故障过程：** Turn A 获得路由 token=a；用户开始新的 Turn B，却复用了旧 token。传输可能没有报错，但请求被归入了旧协议上下文。也就是说，TCP 活着只证明通道存在，不证明业务身份正确。

| 状态作用域候选 | 合理用途 | 不适合放进去的状态 |
|---|---|---|
| 每个物理请求 | 请求计时、重试 attempt | 应跨尝试稳定的 Turn 路由 |
| 每个 Turn | 本轮路由与多次采样关系 | 后续所有会话的永久认证缓存 |
| Session | provider、一定范围的 fallback 状态 | 上一 Turn 专属 token |
| 全进程连接池 | 可共享的连接资源 | 未区分用户/认证归属的续接身份 |

`OnceLock` 的意义是表达“在适当边界确定后保持稳定”；并不是任何共享状态都该一次写入。对必须更新的凭证或撤销策略，错误使用永久缓存反而危险。

## 3. 决策 C04-D2：为什么输入变长还不一定可以增量发送？

WebsocketSession 记录上一请求、上一响应、认证代际和连接 key；NonIncrementalReason 区分缺少历史、请求属性改变、输入缩短或内容不匹配。[F1] **推导：** 增量续接需要当前请求是协议意义上的合法扩展，而不是 `len(new) > len(old)`。

举例：旧请求为 `[system=S1, user=U]`，新请求长度增加了，但 system 变成 S2，或工具 schema 改变，或历史被压缩替换。只发“新增尾部”可能让服务端继续使用 S1 和旧工具，形成一个客户端并未打算发出的混合请求。

候选方案是：永远 full request；只按长度判断；比较完整前缀及相关请求属性后才续接。最后一项保留优化机会，但需要维护基线、失效原因和 fallback。改变认证归属还必须阻止旧用户/路由状态泄入新请求，不能只更新 header 然后沿用 response ID。

Session 级 HTTP fallback 避免每轮都重复尝试已经失败的 WebSocket。[F1] **分析代价：** 暂时故障可能让后续健康时段仍走 fallback；是否需要受控探测恢复，应由真实失败频率、连接开销和协议安全性决定。这里只讨论选择条件，不声称当前代码具备自动探测策略。

## 4. 重试预算为什么需要属于不同层？

一次流读取失败，不说明模型没有产出，也不说明工具没有开始。客户端重连、模型继续生成、重新执行外部工具是三种不同动作。若所有层都独立“最多重试三次”，总尝试次数可能乘法放大；需要记录 logical step、physical attempt、tool invocation 的身份与预算。

这是跨层设计建议，不是对 Codex 默认重试数字的断言。即使 full request 重发，返回响应也可能与前一次不同；把 token 消耗、已发表输出和已产生副作用一并计入恢复判断，才不会将普通 HTTP 重试错误套入 Agent 控制流。

## 5. 验证和停止优化的条件

**上游实验待运行：** 固定 mock provider，分别改变历史前缀、模型参数、工具定义、认证归属；记录 full/incremental 分支及原因。再在建立连接前、部分文本后、tool-call 后断流，检查是否重复执行工具。比较时保持任务与输出固定，不用模型随机性解释一切。

**选型：** 短任务、低调用频次、多个不相容 provider 时，full request 可能更合算；长任务高延迟连接才值得支付续接状态管理成本。没有证据时，不把复杂连接缓存当作基础必需品。

读完应能解释：连接复用优化传输，合法续接维护语义，认证归属维护身份；它们可能相互关联，但任何一个成立都不能自动证明另外两个。

[F1]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L150-L410

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：Turn 内的路由状态

源码：[`client.rs`，L259–L365](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L259-L365)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L259-L365 -->
```rust
pub struct ModelClientSession {
    client: ModelClient,
    websocket_session: WebsocketSession,
    /// Turn state for sticky routing.
    ///
    /// This is an `OnceLock` that stores the turn state value received from the server
    /// on turn start via the `x-codex-turn-state` response header. Once set, this value
    /// should be sent back to the server in the `x-codex-turn-state` request header for
    /// all subsequent requests within the same turn to maintain sticky routing.
    ///
    /// This is a contract between the client and server: we receive it at turn start,
    /// keep sending it unchanged between turn requests (e.g., for retries, incremental
    /// appends, or continuation requests), and must not send it between different turns.
    /// An auth ownership change clears it so the new owner gets fresh routing state.
    turn_state: Arc<OnceLock<String>>,
}
```

#### 逐段讲解

`turn_state` 不是用户聊天 ID，而是服务端为这个 Turn 返回的路由状态。注释规定它在同一 Turn 的重试、增量追加与继续请求之间保持不变，不能带入不同 Turn。

`OnceLock` 表达初始化后的共享读取，`Arc` 管理共享所有权。但源码还明确认证归属改变时会清理；因此不能把类型解释成“永远不可重置的全局常量”。

与 [01](01-agent-loop.md) 的 `&mut client_session` 联系起来：Loop 在同一 Turn 多次采样时复用这个对象，是为了维持传输契约，不是为了共享无限长度 messages。

**设计反例：** 把客户端做成全局单例并复用所有 turn state，可能把后续任务带到不属于它的续接状态；反过来每次工具回合都新建，则可能丢掉应保持的路由信息。具体失效表现需要 mock 或抓取实验，本文没有实测。

### 3. 核心源码 B：连接活着不等于语义仍可续接

同一文件与定位范围。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L259-L365 -->
```rust
#[derive(Debug, Default)]
struct WebsocketSession {
    connection: Option<ApiWebSocketConnection>,
    responses_headers: ApiHeaderMap,
    /// Owner of the cached state, including before a connection is opened.
    auth_owner_generation: Option<u64>,
    connection_key: Option<ResponsesConnectionKey>,
    last_request: Option<ResponsesApiRequest>,
    last_response_rx: Option<oneshot::Receiver<LastResponse>>,
    last_response_from_untraced_warmup: bool,
    connection_reused: StdMutex<bool>,
    continuation_reset_reason: Option<&'static str>,
}
```

连接、认证代际、上一请求、上一响应被分别保存。`last_response_rx` 是异步接收上一响应状态的通道，说明某些状态不是发出请求时立即可得；从 Option 也能看出它可能不存在。

**分析：** 一个 TCP/WebSocket 连接仍可用，只能证明传输通道可能可复用；要发送增量 payload，还需要兼容的上次请求和回应。这与缓存命中又是不同概念。

这里不猜 `ResponsesConnectionKey` 的所有字段，也不根据结构体宣称已验证认证切换的全部清理路径；下一步应沿字段写入点阅读。

### 4. 核心源码 C：把续接失败解释为受控原因

同一文件与定位范围。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L259-L365 -->
```rust
enum NonIncrementalReason {
    NoPreviousRequest,
    NoPreviousResponse,
    NoPreviousResponseId,
    RequestPropertyChanged {
        reason: &'static str,
    },
    InputShortened {
        previous: &'static str,
    },
    InputMismatch {
        previous: &'static str,
        current: &'static str,
    },
}
```

这些分支表明消息数量增加不是增量续接的充分条件：上一响应缺失、请求属性改变、输入前缀不匹配都需要区别处理。枚举本身不包含整个匹配算法，不能把它当成完整判定函数。

`&'static str` 的受控标签避免把 Prompt 文本和不受限标识直接放入指标维度。敏感原始证据应走受控诊断路径，见 [08](08-observability-evaluation.md)。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/codex/04-llm-streaming.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
