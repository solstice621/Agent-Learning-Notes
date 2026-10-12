# Codex 07｜任务恢复：关闭交接与恢复条件

Codex 正在修改代码，后台服务需要升级重启。重启后重新打开对话，并不代表原来的程序能从暂停处接着跑：工具可能已改完文件，返回结果却还没写进历史。

**这条恢复路径保存对话和继续工作的条件，再启动新的一轮。** 它不会保存 Rust 异步任务的执行位置。本篇讨论的是 app-server 受管理的关闭与恢复流程，突然断电不一定有机会走完这套交接。

<!-- decision: C07-D1 | 为什么“交给记录器”与“确认保存”要分开？ -->
## 输入落盘与恢复清单

整体链路是：Session 产生历史记录，ThreadStore 提供存储接口，本地实现交给 RolloutRecorder 写 JSONL 文件。为了给不同后端留余地，接口允许部分检查点在排队后返回，但 `Standard` 要等持久化操作完成。

所以，不能只根据 `persist_thread()` 的名字判断返回意味着什么。`SubagentSpawn`、`TurnStart` 等上下文允许后台处理，后续确认保存或关闭操作必须收住这些写入。当前本地后端的普通追加还会等待 recorder 的 flush，并不是“所有输入都只排队”。

看关闭流程最关键的顺序：先取出可恢复的中断信息，接着等待标准保存；失败就跳过，成功才放进清单。

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/request_processors/daemon_snapshot.rs#L30-L40 -->
```rust
                // 笔记：先取得候选中断信息；还不能据此承诺重启后可以继续。
                let interrupted = thread.interrupted_turn().await;
                if let Err(err) = self
                    .thread_store
                    // 笔记：Standard 要等待保存完成，关闭清单不能领先于输入历史。
                    .persist_thread(thread_id, PersistContext::Standard)
                    .await
                {
                    warn!(%thread_id, %err, "skipping daemon restore for thread that could not be persisted");
                    // 笔记：保存失败就放弃把此项列入恢复清单，避免新服务接到缺失输入的任务。
                    continue;
                }
                // 笔记：只有保存成功才登记已加载任务；是否继续还要检查中断信息和恢复资格。
                snapshot.loaded.insert(thread_id.to_string());
                if let Some((turn_id, options, environment)) = interrupted {
```

否则清单可能说“请继续这轮”，历史里却没有这轮的完整输入。

本地实现还明确规定：**JSONL 是历史的依据，SQLite 历史表是可重建的查询视图。** 先完成文件写入，再更新视图；更新视图失败可以落后，不能让它领先于实际历史。这比试图让两份数据处处同时成功更容易恢复。

每条记录都同步确认，实现直观但可能增加等待；全部后台写，调用方又容易误判保存状态。这里选择按用途给出不同承诺，代价是调用方必须读懂接口条件。

<!-- decision: C07-D2 | 有历史，为什么有些任务仍不自动继续？ -->
## 续跑前的环境检查与资格判断

采集阶段只接受输入已记录、尚未取消的普通任务，并限制为受支持的单一本地环境。新服务加载历史后，还会检查旧轮是否已经完成或被后来的工作替代。

接下来是环境和权限检查。下面这段明确要求恢复后的选择与保存时一致：

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/request_processors/daemon_continuation.rs#L74-L87 -->
```rust
        let config = thread.config_snapshot().await;
        // 笔记：该自动续跑路径只接受单一环境；能加载历史不代表每种环境都能自动恢复执行。
        let [environment] = config.environment_selections() else {
            return;
        };
        // 笔记：环境身份、配置来源和保存的环境内容都要一致，变化时直接退出续跑路径。
        if environment.environment_id != codex_exec_server::LOCAL_ENVIRONMENT_ID
            || environment.config != EnvironmentConfigState::FromThread
            || saved.local_environment.as_ref() != Some(&ThreadEnvironment::from(environment))
        {
            return;
        }
        // Recovery must not override a stricter saved or newly configured policy.
        // 笔记：新旧权限必须一致；恢复流程不能替用户放宽更严格的权限。
        if previous_context.permission_profile() != config.permission_profile {
            return;
        }
```

通过检查后，系统在历史中将旧轮标为中断，再启动新轮，并提示模型先检查当前状态，避免重复已经完成的动作。这样就解释了为什么“恢复会话”和“自动继续执行”可以得到不同结果：历史能看，不代表现在还能按原条件行动。

再设想一个工具已经提交了修改，进程却在记录结果前退出。重跑可能重复操作，不重跑又可能漏做。仅凭聊天历史无法消除这个歧义；需要查验文件或外部状态，必要时使用工具自身的幂等机制。

## 自测

恢复清单已保存，但旧进程在退出宽限期内完成了任务。新进程应立即再跑一次吗？

<details>
<summary>参考答案与证据</summary>

不应。它重新读取历史，发现旧轮已有完成记录就跳过继续。清单只是候选，不是无条件重试命令。

已重读[本地写入与查询投影](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/local/live_writer.rs#L327-L383)、[继续任务完整分支](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/request_processors/daemon_continuation.rs#L40-L120)。上游[管理重启测试](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/tests/suite/v2/daemon_update_recovery.rs#L462-L738)覆盖取消、已完成、环境变化等情况；本轮只阅读，未实际重启验证。底层所读路径使用文件 `flush()`，本文不把它扩写为断电后的硬件持久性保证。

</details>
