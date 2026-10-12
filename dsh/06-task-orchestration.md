# DSH 06｜目标编排：自动续跑与版本校验

[总目录](../README.md) · [先读导览](../START_HERE.md) · [项目架构](00-architecture.md) · [问题索引](../DESIGN_INDEX.md)

代码中 `// 笔记：` 为新增中文注释，其余保留上游原文。

你让 Agent 持续修复测试。它刚跑完一轮，目标仍未完成，但这时保存会话失败了。如果程序只是“没完成就再发一次消息”，它仍会继续改文件，而上一轮记录可能没有保存下来。

**目标是否完成，与现在能否自动继续，是两个问题。** DSH 的 `goal` 保存目标状态；`goal-round-driver` 在 Agent 空闲后安排下一轮；命令和工具只是修改目标的入口。自动 Round 会把续跑消息送入现有会话；消息被接纳后进入 Turn，一个 Turn 可以包含多次模型请求和工具调用。

<!-- decision: D06-D1 | 目标还是 active，为什么不能继续执行？ -->
## 目标状态与自动续跑条件

`phase` 表示目标处于进行、暂停、受阻或完成；`activation` 表示本次运行是否被允许自动续跑。只有 `active` 加 `armed` 才能[安排下一轮](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L164-L179)。

模型或存储失败后，任务可以保持 `active`，同时撤销续跑许可。下面是驱动器等待保存完成的地方：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L142-L154 -->
```ts
    if (state.needsCheckpoint) {
      state.needsCheckpoint = false
      try {
        // 笔记：续跑前先保存上一轮事实；异步等待期间用户仍可能改变目标。
        await ctx.sessions.flush(agent.session)
      } catch (error: unknown) {
        ctx.logger.warn(`goal-round-driver: durability checkpoint failed for agent "${agent.id}": ${renderThrown(error)}`)
        // 笔记：保存失败只撤销自动执行许可，不把尚未完成的目标伪装成 completed。
        disarm(state)
        return
      }
      // A mutation or ordinary prompt may have arrived while the checkpoint
      // was settling. Give it its own checkpoint / turn before reserving.
      // 笔记：await 之后重新检查条件，不能沿用等待前的判断。
      if (!readyAfterCheckpoint(state)) return
    }
```

`flush` 失败就 `disarm` 并返回，不再排下一轮；保存成功后仍要重新检查，因为等待期间用户可能已经输入新要求。

这还有一个容易忽略的后果：目标历史会保存，续跑许可是进程内状态。[新 Agent 建立时会撤销许可](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal/src/index.ts#L248-L267)。因此，恢复一个未完成会话，并不自动恢复持续执行；需要显式 resume。这样不会把“磁盘上仍有任务”误读成“现在仍允许它运行”。

轮数上限只限制自动 Round 的数量，不能代替 token、费用或单次工具耗时限制。如果工作只是一个确定步骤的脚本，普通任务队列会更简单；这些状态主要服务于可暂停、可恢复的自主续跑。

<!-- decision: D06-D2 | 刚恢复的任务，为什么不能再被旧回调暂停？ -->
## 目标版本与过期回调校验

另一条时间线更隐蔽：用户暂停第 1 轮，又立刻恢复；旧轮的取消操作这时才结束。如果结束回调只看目标 ID，就可能再次暂停刚恢复的目标。

DSH 在暂停、恢复、编辑时推进 `revision`。旧轮保存的是旧版本号，结束时必须对上当前版本才有权改变它：

<!-- annotated-source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L264-L270 -->
```ts
        // Fence the pause to the exact dropped attempt's ref. A resume bumps
        // the revision, so a host pause followed by an immediate resume (before
        // the aborted turn converges to idle) must not re-pause the resumed goal.
        // 笔记：迟到的取消回调只有满足这一整组条件，才有权暂停当前目标。
        const pause = attempt !== undefined
          && (attempt.phase === 'queued' || attempt.phase === 'claimed' || attempt.cancelled)
          && goal !== undefined && goal.phase === 'active' && goal.activation === 'armed'
          // 笔记：同一目标 ID 还不够；resume 已推进版本时，旧回调必须失效。
          && attempt.goalId === goal.id && attempt.revision === goal.revision
```

这里最后一行是关键：ID 相同还不够，revision 也必须相同。它保证旧轮只处理自己那一版目标。

另外，[驱动器还比较 Agent 对象本身](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L96-L109)。同一个会话 ID 被关闭后重建，会得到一个新对象；旧对象的迟到事件不能管理新对象。版本号区分目标修改，对象身份区分运行实例，两者各挡一种过期工作。

用户输入也有优先权：用户排队提交新消息时，会让尚未执行的自动消息失效；驱动器保留其他已取出的输入，避免删除自动消息时顺手丢掉用户内容。

[上游测试](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/tests/goal-round-driver.spec.ts#L371-L387)实际模拟“暂停后立即恢复”，并检查第二轮确实运行；[另一个测试](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/tests/goal-round-driver.spec.ts#L569-L577)检查刷盘失败时请求数为零。本次仅阅读，未重跑。本仓库原有小实验只比较对象、元组是否不同，不能证明回调被正确拒绝。

## 自测

恢复会话后看见 `active + disarmed`，是状态矛盾吗？能否只凭会话 ID 接受旧事件？

<details>
<summary>展开答案</summary>

不矛盾：任务仍未完成，但目前没有自动续跑许可。旧事件还必须匹配当前 Agent 对象；涉及目标变更时也要匹配 revision。会话 ID 只说明属于哪段历史，不能说明属于哪次运行、哪版目标。

</details>

---

固定源码：`deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`｜研究日期：2026-10-12。

[源码重读记录](../research/reread/dsh-05-08.md) · [研究方法与验证边界](../RESEARCH_METHOD.md) · [源码归属与许可](../THIRD_PARTY_NOTICES.md)
