# Codex 04｜模型通信：连接复用与增量请求

第一次问模型“检查 A 文件”，模型返回了一个工具调用。文件读完后，再请求模型继续。如果每次都发完整历史，大量旧内容会重复传输；如果只发最新工具结果，服务端又必须知道它接着哪段历史。

**Codex 可以复用连接，并在确认旧内容仍然匹配时只发送新增部分；连接、历史续接和本轮路由信息各有自己的寿命。**

在执行链上，`run_turn` 建立 `ModelClientSession`，后续采样请求通过它读取模型响应流。更外层的 `ModelClient` 属于会话，持有 provider、连接缓存和传输降级状态。注意：`ModelClientSession` 虽然带着 Session 这个名字，却只服务一个 Turn；跨多轮保留状态的是外层 `ModelClient`。

<!-- decision: C04-D1 | 同一个连接还能用，为什么新一轮要重建客户端对象？ -->
## 连接复用与轮次路由状态

服务端可能返回 `x-codex-turn-state`，让同一 Turn 的后续请求带着它，保持路由一致。重试和继续生成仍属于本轮，所以应沿用；新一轮任务则不能携带上一轮的令牌。

创建新 `ModelClientSession` 时，代码接回缓存的 WebSocket 状态，却新建一个空的 `turn_state`：

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L669-L681 -->
```rust
    pub fn new_session(&self) -> ModelClientSession {
        let auth_owner_generation = self.auth_owner_generation();
        // 笔记：新一轮先领取可复用的连接与续接状态，重新建对象不意味着重新建连接。
        let mut websocket_session = self.take_cached_websocket_session();
        // 笔记：认证归属改变会使旧缓存失效，不能把上一身份的连接状态直接带入。
        if websocket_session.auth_owner_generation != auth_owner_generation {
            // Drop the old owner's cache before this turn can establish fresh routing state.
            websocket_session.reset(Some("other"));
            websocket_session.auth_owner_generation = auth_owner_generation;
        }
        ModelClientSession {
            client: self.clone(),
            websocket_session,
            // 笔记：每轮单独创建路由令牌容器；它与可跨轮缓存的 WebSocket 状态寿命不同。
            turn_state: Arc::new(OnceLock::new()),
        }
```

这里有个很容易读错的地方：**每轮新建对象，不等于每轮重新连接。** 旧对象释放时，会把 WebSocket 状态存回外层客户端；新对象可以再次取出。上游甚至专门测试了跨 Turn 复用连接和 `previous_response_id`。因此不能把“本轮路由令牌不跨轮”推广成“历史续接也不能跨轮”。[查看缓存归还](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L1412-L1417)。

身份换人则不同。认证归属变化会清掉旧连接与续接状态，轮内变化也会重置路由令牌，避免把旧归属的缓存带进新请求。[查看轮内身份变化处理](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L1660-L1688)。

<!-- decision: C04-D2 | 历史变长了，为什么仍可能发送完整请求？ -->
## 增量请求的历史匹配条件

服务端已知的基线包含两部分：上一请求的输入，加上它自己刚生成的输出。后续输入必须从这整段内容继续，不能只比较上一请求有多少条消息。

代码逐条核对这个前缀：

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L1486-L1500 -->
```rust
        // 笔记：服务端基线包含上一请求输入以及它刚生成的输出，不能只比较用户输入。
        let response_items = &last_response.items_added;
        let previous_items = previous_request.input.iter().chain(response_items);
        let mut current_items = request.input.iter();
        // 笔记：逐项检查旧基线是否仍是当前请求的前缀，后面的剩余项才可能作为增量。
        for previous in previous_items {
            let Some(current) = current_items.next() else {
                // 笔记：当前输入变短说明前缀缺失，调用者需改走完整请求路径。
                return Err(NonIncrementalReason::InputShortened {
                    previous: previous.item_type(),
                });
            };
            // 笔记：消息实质内容变化也会拒绝续接；仅追加尾部无法修正服务端已有内容。
            if !response_items_equal_ignoring_internal_metadata(previous, current) {
                return Err(NonIncrementalReason::InputMismatch {
                    previous: previous.item_type(),
                    current: current.item_type(),
                });
            }
```

前缀短了或不匹配就不能续接；核对结束后，剩余条目才是可发送的增量。在此之前还会比较模型、工具定义等相关请求属性。不是所有字段都必须完全相等：内部展示元数据有特定忽略规则，但旧工具结果的实质元数据若改变，不能只靠追加尾部补上。[查看属性与条目比较](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L380-L470)。

例如历史压缩后，把旧消息换成了摘要。即使又追加许多内容、总条数反而增加，原前缀也已改变。此时发送完整输入，才能让服务端看到客户端实际打算使用的上下文。[查看完整与增量分支](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L2049-L2115)。

这项优化省的是重复发送机会，代价是保存基线、检查失效和处理断连；不能直接推出节省多少模型费用。当前实现一旦切换到 HTTP 降级，后续 Turn 也沿用到会话结束。对短任务或不支持续接的 provider，每次发送完整请求更容易实现和排查。

## 自测

Turn B 复用了 Turn A 的连接和响应 ID，是否必然违反“每轮新建客户端”的规则？

<details>
<summary>参考答案</summary>

不违反。新对象可以接回连接与合法的续接基线；必须重新开始的是本轮路由令牌。能否发送增量，还要检查认证归属、请求属性和历史前缀。

</details>

证据与局限：已读[跨 Turn 续接测试](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/client_websockets.rs#L1355-L1453)及[工具结果变化使续接失效的测试](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client_tests.rs#L824-L960)，本轮未执行，也未测量连接复用的性能收益。
