# Codex 08｜可观测性：执行追踪与诊断记录

[总目录](../README.md) · [先读导览](../START_HERE.md) · [项目架构](00-architecture.md) · [问题索引](../DESIGN_INDEX.md)

代码中 `// 笔记：` 为新增中文注释，其余保留上游原文。

用户要求修复一个 bug。终端显示测试完成，Codex 也给出最终回答，可那个 bug 仍能复现。只看聊天记录，很难分清：测试没测到问题，工具结果没传回模型，还是模型理解错了？

**先还原过程，才能定位失败；过程记录本身并不会替你判断任务是否成功。** Codex 的 Rollout Trace 为第一步服务：核心记录模型请求、工具执行、终端输出等证据，离线程序再把它们连起来。

<!-- decision: C08-D1 | 为什么先记事件，稍后再整理关系？ -->
## Rollout Trace 的事件关联

假设模型让 Code Mode 执行一段 JavaScript，代码里又调用了终端工具。这里至少有三件不同的东西：终端原始输出、返回给 JavaScript 的值、最终进入下一次模型请求的内容。

直接工具调用与 Code Mode 调用在代码里有不同的结果类型。因而，“工具已经返回”只说明运行时拿到结果；要判断结果是否进入模型上下文，还要找到后续请求中的对应内容。

运行时把较大的请求和结果放进独立 payload 文件，事件里只保存引用。顺序是先写内容，再生成可以引用它的位置：

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/writer.rs#L91-L105 -->
```rust
        // 笔记：同一 writer 锁内分配序号和路径，避免并发写入抢用同一 payload 身份。
        let mut inner = self.lock_inner();
        let ordinal = inner.next_payload_ordinal;
        inner.next_payload_ordinal += 1;
        let raw_payload_id = format!("raw_payload:{ordinal}");
        let relative_path = format!("{PAYLOADS_DIR_NAME}/{ordinal}.json");
        let absolute_path = inner.payloads_dir.join(format!("{ordinal}.json"));
        // Payload files are created before the event that references them. A
        // replay interrupted after an event is appended should never point at a
        // payload file that the writer planned but had not written yet.
        // 笔记：先真正写出内容再返回引用，后续事件才可以引用这个文件。
        write_json_file(&absolute_path, value)?;
        Ok(RawPayloadRef {
            // 笔记：返回的是位置与类型，事件不必再内嵌整个大 payload；这不是断电事务保证。
            raw_payload_id,
            kind,
            path: relative_path,
        })
```

这样能避免先记下引用、对应文件却还没开始写的窗口。随后 writer 在同一把锁内分配序号并追加事件；离线 reducer 按文件行序读取，再建立“这个结果来自那个工具”的关系。

为什么不边执行边做好整张图？因为工具可能已经开跑，记录完整模型响应的钩子还没执行。reducer 专门暂存这些还找不到来源的 Code Mode 事件，等证据齐了再关联。把这类整理移到事后，运行代码就无需为画图改变执行顺序。

代价是多占存储、还要运行一次整理程序。如果只需排查固定的一次函数调用，几条带编号的结构化日志可能已经够用。

<!-- decision: C08-D2 | 调试记录写失败时，任务应不应该跟着失败？ -->
## 诊断记录的尽力保存策略

初始化 trace 的代码直接表达了选择：未开启就禁用，创建失败也禁用，并留下 warning。

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/thread.rs#L106-L118 -->
```rust
    pub fn start_root_or_disabled(metadata: ThreadStartedTraceMetadata) -> Self {
        // 笔记：未配置 trace 目录就返回空实现，业务调用方仍可使用同一接口。
        let Some(root) = std::env::var_os(CODEX_ROLLOUT_TRACE_ROOT_ENV) else {
            return Self::disabled();
        };
        let root = PathBuf::from(root);
        // 笔记：开启了 trace 也可能初始化失败；这里将失败限制在诊断功能内。
        match start_root_in_root(root.as_path(), metadata) {
            Ok(context) => context,
            Err(err) => {
                // 笔记：只告警并禁用记录，所以没有 trace 不能证明该业务动作没有发生。
                warn!("failed to initialize rollout trace bundle: {err:#}");
                Self::disabled()
            }
        }
    }
```

后续写事件失败同样只告警。对调试功能，这避免“为了调查故障又引入一个让任务退出的故障”；相应地，**trace 中缺少某次调用，不能当作它没有发生的证明。** 会话恢复依赖另一条历史存储路径，不能把这份可缺失的诊断记录当账本。

回到开头的 bug，可以分三步归因：终端报依赖缺失，先查环境；结果存在但后续请求未包含预期内容，查结果传递；结果已进入请求却被回答误读，再查模型判断。若模型准确复述了“测试通过”，bug 仍在，则还要查测试是否覆盖需求。

最后一项需要独立的验收用例。Trace 回答“过程怎样发生”，任务评估回答“结果是否达标”，二者配合才有意义。

## 自测

日志里有 `ToolCallEnded`，足够证明模型收到完整输出，并且任务成功了吗？

<details>
<summary>参考答案与证据</summary>

不够。还要检查后续模型请求，以及独立的任务验收结果。请求记录也可能是逻辑请求表示，不宜当作服务端逐字节接收证明。

已重读[架构说明](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/README.md#L9-L102)、[工具结果的两种来源](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/tool_dispatch_trace.rs#L62-L109)、[延后关联](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/reducer/mod.rs#L113-L128)。上游[结果关联测试](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/reducer/conversation_tests.rs#L1208-L1301)检查工具与后续请求的对应关系；本轮只阅读，未运行。实现按文件顺序归约，不会自动替乱序文件排序；写文件先后也不等于断电事务保证。

</details>

---

固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`｜研究日期：2026-10-12。

[源码重读记录](../research/reread/codex-05-08.md) · [研究方法与验证边界](../RESEARCH_METHOD.md) · [源码归属与许可](../THIRD_PARTY_NOTICES.md)
