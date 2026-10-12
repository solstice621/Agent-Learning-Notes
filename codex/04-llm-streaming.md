# Codex 04｜LLM / Streaming：会话、连接和增量续接

[总目录](../README.md) · P0 · 前置：[01](01-agent-loop.md) · 对照：[OpenCode](../opencode/04-llm-streaming.md) / [DSH](../dsh/04-llm-streaming.md)

**固定源码：** `openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。本文以真实结构体说明状态作用域；不冒充对全部网络协议的审计，未调用真实 API。

## 1. 首先区分四个对象

产品 Session、一个 Turn 的 ModelClientSession、底层 WebSocket 连接和 provider 的上一响应身份并不等价。理解这些状态的归属，比背诵某个模型的 API 参数更重要。

源文件 `core/src/client.rs` 的文档注释指出：ModelClient 共享 Session 级状态；ModelClientSession 属于一个 Turn，维护本 Turn 的粘性路由。下面直接看它们如何被表达。

## 2. 核心源码 A：Turn 内的路由状态

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

### 逐段讲解

`turn_state` 不是用户聊天 ID，而是服务端为这个 Turn 返回的路由状态。注释规定它在同一 Turn 的重试、增量追加与继续请求之间保持不变，不能带入不同 Turn。

`OnceLock` 表达初始化后的共享读取，`Arc` 管理共享所有权。但源码还明确认证归属改变时会清理；因此不能把类型解释成“永远不可重置的全局常量”。

与 [01](01-agent-loop.md) 的 `&mut client_session` 联系起来：Loop 在同一 Turn 多次采样时复用这个对象，是为了维持传输契约，不是为了共享无限长度 messages。

**设计反例：** 把客户端做成全局单例并复用所有 turn state，可能把后续任务带到不属于它的续接状态；反过来每次工具回合都新建，则可能丢掉应保持的路由信息。具体失效表现需要 mock 或抓取实验，本文没有实测。

## 3. 核心源码 B：连接活着不等于语义仍可续接

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

## 4. 核心源码 C：把续接失败解释为受控原因

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

## 5. 实验与验收

mock provider 分别在连接前、任何输出前、部分文本后、完整工具调用后断开。记录实际 physical request 数、完整/增量请求、Turn ID、重试等待和工具实际执行次数。

另测试输入缩短、工具声明变化、认证归属变化。不要预设所有变化都触发同一种 fallback；沿实际分支记录。传输重试不能自动授权重做有副作用的工具。

验收是一张“状态—作用域—初始化—失效条件”表。能解释连接池、Turn 路由状态与业务历史为什么不应共享一个未经区分的 Session 概念。

**范围：** 只做静态源码阅读，未做网络压测或性能结论。原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
