# OpenCode 06｜为什么委派中的 Prompt、Job 和结果通知必须分开？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 一个 child ID 不代表完整的任务协议

最简单的 subagent 函数创建模型请求并 await 结果。可继续子会话、后台执行、父子权限、任务取消以及并发提交出现后，spawn 的返回值需要表达的不只是一个字符串。

实际 subagent 工具会查找父会话、计算深度、验证目标 agent、检查权限和 parentID、选择模型，然后提交 prompt、创建恢复描述，最后选择前台阻塞或后台交付。[F1] 这里没有理由把所有动作揉成一个不透明的 task()。

## 2. 决策 O06-D1：为什么 prompt admission 放在 Job.run 外面？

源码注释明确指出：Job.start 加入已经运行的 child 时，可能跳过其 run effect，因此标准 prompt admission 必须放在 job 之外。[F1] 这是当前实现的直接理由。

**反事实时间线：** child 正在处理 A；父提交 B；如果 B 的 `sessions.prompt` 写在“仅新 Job 才执行”的闭包里，Job.start 发现旧 Job 已存在并加入它，就可能永远没有把 B 记录进去。调用者以为加入了新工作，实际上只是等旧结果。

| 候选语义 | 合理用途 | 要清楚说明的限制 |
|---|---|---|
| 每次调用新建 child | 完全独立任务 | 丢失连续上下文、产生更多 Session |
| 已有 child 就只 join | 只允许等待已提交任务 | 不能同时承诺接纳新 prompt |
| 先持久接纳，再启动/加入 Job | 支持继续已有任务 | 要有输入 ID、顺序和 busy/steer 规则 |
| 将输入与执行做一个事务式外部工作流 | 严格交付要求 | 更多存储协议与运行时依赖 |

新后台 child 可以先用 resume:false 接纳，再由 SubagentJob 管理启动；已有 child 的继续仍走相应接纳路径。[F1] “启动幂等”与“新输入去重”必须分别定义，否则接口很容易看似 idempotent 实则吞消息。

## 3. 决策 O06-D2：为什么 foreground/background 改变的是所有权，不只是 await？

前台等待通过 jobs.block；中断等待时源码会中断 child 并取消 job。后台路径返回 running，后续交由通知机制，失败中保留 sessionID 以支持定位/继续。[F1]

**推导：** 后台化把“调用者不再阻塞”与“谁继续负责取消、结果保存、通知和清理”分开。如果只是漏写 await，异步异常、资源泄漏和父任务退出后的行为都没有所有者。

父子归属检查也是能力限制：知道某个 Session ID 不应该等于有权继续它；工具验证 existing.parentID 属于当前 Session。[F1] 深度限制阻止无限递归，但不是总并发、token 或资源预算；一层就能创建很多 child。不能把 recursion limit 当作完整配额系统。

对 fresh child，传入任务必要上下文与复制父全部历史也不同。前者降低无关输入，但可能遗漏约束；后者提供更多历史，却带来成本与不该继承的状态。必须用任务信息需求选择，而不是以“更自治”评价。

## 4. 通知成功不代表任务正确

后台 completion 表明运行或交付达到某个编排终态，不证明补丁通过测试、答案有依据或用户目标达成。若把自然语言“完成了”当 reward，会把空结果或错误补丁误计成功。

**设计推导：** 应分别保存 execution outcome、result delivery、task verification。恢复与父取消竞争还可能导致重复通知或无人消费；需要相应去重与可靠交付规则，但本文没有完整审计 SubagentJob 后端，因此不宣称它提供 exactly-once 通知。

对于批量独立评测，普通 Job 结果存储可比长期 child Session 简单；对于多轮协作，保留 child identity/context 才是必要成本。foreground 与 background 应根据独立性和生命周期，而不只根据任务长短选择。

## 5. 验证和读后问题

**上游实验待运行：** child 运行 A 时再提交 B，断言 B 已实际 admission；使用另一个父尝试继续该 child，确认拒绝；前台等待被中断、后台结果完成与父关闭竞争时，分别核查资源、通知和持久结果。

测量应包含 task 排队、模型、工具、结果通知四段，不只看 spawn 返回很快。一个立即返回 running 的接口可能把全部延迟转移到用户不可见处。

应能说明：哪个操作承诺接纳输入，哪个只启动/加入执行，哪个负责交付结果，哪个负责验证目标。这些契约比“多 Agent 能并行”更接近基础设施设计。

[F1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L1-L310

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：先决定模型与子会话身份

源码：[`tool/plugin/subagent.ts`，L166–L269](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L166-L269)。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L166-L269 -->
```ts
              const model = override ?? agent.model ?? parent.model
              const child =
                existing ??
                (yield* sessions
                  .create({
                    parentID: context.sessionID,
                    title: input.description,
                    agent: Agent.ID.make(input.agent),
                    model,
                  })
                  .pipe(
                    Effect.mapError(
                      (error) => new ToolFailure({ message: `Parent session not found: ${context.sessionID}`, error }),
                    ),
                  ))
```

#### 逐段讲解

模型优先级由空值合并运算符明确表达：显式覆盖、Agent 配置、父模型。前面 resolveModel 的校验不可省略，不能把任意字符串当可用 provider/model。

`existing ?? create` 保留了继续已有 Session 的语义；新建时才建立 parentID 与标题。前面的实现还检查 existing 的父关系，因此知道一个 sessionID 不应直接获得任意子会话控制权。

**注意：** 新建 child 并不在这段复制父历史。要区分 fresh context、fork 和 resume，不能统一叫“继承父 Agent”。具体失败消息映射也不证明底层错误必然是父缺失，原 error 仍作为数据保留。

### 3. 核心源码 B：Prompt 不能藏在可能被跳过的 Job.run 里

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L166-L269 -->
```ts
              // Standard prompt admission outside the job: Job.start joining a running child skips
              // its run effect, and the default wake starts an idle child or steers a running one.
              yield* sessions
                .prompt({
                  sessionID: child.id,
                  text:
                    existing === undefined
                      ? ["You are a subagent spawned by another session.", input.prompt].join("\n")
                      : input.prompt,
                  ...(background && existing === undefined ? { resume: false } : {}),
                })
                .pipe(
                  Effect.mapError(
                    (error) => new ToolFailure({ message: `Failed to prompt subagent: ${child.id}`, error }),
                  ),
                )
```

#### 逐段讲解

注释直接给出设计原因：加入正在运行的 child job 可能不再执行该 job 的 run effect。如果输入只在 run 内提交，那么“加入已有执行”会导致本次新 Prompt 没有接纳。故这里先走普通 Session.prompt。

新建 child 增加委派上下文，继续已有 child 不重复增加。新建且 background 时设置 resume:false，先接纳输入，后续由 SubagentJob 控制启动；其他情况由正常 wake 处理。

**核心抽象：** durable admission、execution ownership、delivery 是三项独立责任。不是有一个 Future 就同时完成了任务记录、运行和通知。

### 4. 核心源码 C：前台等待取消会传播给两层对象

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L166-L269 -->
```ts
              const result = yield* jobs.block({ id: child.id, sessionID: context.sessionID }).pipe(
                Effect.onInterrupt(() =>
                  Effect.all([sessions.interrupt(child.id), jobs.cancel(child.id)], {
                    discard: true,
                  }),
                ),
              )
              if (result?.type === "backgrounded") {
                yield* subagents.notify(recovery, result.info.started_at)
                return backgroundResult(child.id)
              }
```

取消的是前台阻塞等待，但 cleanup 同时请求中断 child Session 与取消 Job，避免只有父调用退出、子工作继续失去管理。Effect.all 在这里协调两项清理；不应进一步推断所有底层副作用都被回滚。

等待结果还可能是 backgrounded，此时进入通知路径，而不是把它当完成文本。源码后续区分 error、cancelled、completed，并保留 child ID。`completed` 只表示这段编排结束，不证明代码补丁或业务结果正确。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/opencode/06-task-orchestration.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
