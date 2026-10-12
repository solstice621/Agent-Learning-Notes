# OpenCode 03｜为什么一次请求要捕获工具，结果又要分 output、content 与 metadata？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 从一个普通函数说起

对于固定工具集，一个 `Map<string, Function>` 加 JSON 参数可以工作。动态插件、MCP、多模型 schema、Code Mode 和 UI 展示出现后，单个函数返回值却要同时承担多种职责。最危险的不是类型繁琐，而是“模型获知的能力”“实际执行的能力”“下一次模型看到的结果”不再一致。

官方 V2 Tools 契约将请求捕获、输入/输出 codec、规范模型 content、UI metadata 和结果限制明确分开。[D1] 下方源码展示一次调用何时发布、何时 fork 执行及如何结算。[F1]

## 2. 决策 O03-D1：为什么不在 tool-call 到达时查最新注册表？

文档明确一次模型请求同时捕获广告定义与实际工具值；后续注册变化影响后续请求，而非让已产生调用执行另一个版本。[D1]

**反事实：** 插件 V1 接受参数 `{path}`，请求已发送；插件热更新成同名 V2，但参数或权限语义不同；模型仍根据 V1 返回调用。到达时查最新表会把“同名”误当“同一个执行契约”。请求捕获使当前逻辑一致，代价是旧工具对象可能继续驻留。

| 选择 | 好处 | 必须处理的问题 |
|---|---|---|
| 执行时最新工具 | 立即看到更新 | 模型 schema 与 handler 不匹配 |
| 会话级永久工具集 | 一致且简单 | 更新不生效、旧对象长驻 |
| 请求级捕获 | 当前请求一致，后续可更新 | 正在执行的旧代际如何卸载 |
| 请求携带显式版本、执行时协商 | 对远程协议清楚 | 版本仓库与兼容策略复杂 |

**重要边界：** 捕获工具实现不意味着安全撤销可以延迟。执行点的实时政策可以另行判断；“已公布”与“现在有权调用”是两个问题。第三方插件如果拥有可信服务引用，也不因进入同一 registry 就自动获得 OS 隔离。[D1]

## 3. 决策 O03-D2：为什么不能返回一个大 JSON 给所有消费者？

文档定义 `output` 是 schema 验证后的临时机器值，`content` 是持久化给模型的规范表示，metadata 是紧凑 UI 数据。[D1]

假设检索工具返回一千条记录：Code Mode 可能要对结构化数组做筛选；模型只需要有限摘要与后续读取入口；UI 需要状态和表格信息。把一个 JSON 无差别复制到所有通路，既浪费上下文，又可能泄漏机器内部细节。反过来，仅返回自然语言，会损害程序消费者的结构化能力。

这种分离的收益不是“字段更多”，而是明确每个表示的使用者和持久性。**推导代价：** 同一结果现在需要验证多条转换链；如果 output 说成功而 content 误写失败，两个消费者得到矛盾事实。规范 content 应成为后续模型历史的真实依据，不能从 UI metadata 偷偷重构另一份历史。

输出上限还分为采集端与 registry：进程输出在采集时被丢弃的字节，后续保存预览时无法恢复；一个有文本上限的结果也可能含大媒体或 metadata。[D1] 正确的 retention 状态应区分“完整内容已另存”和“生产者本来就截断”，否则模型会追索一个根本不存在的完整文件。

## 4. 为什么工具调用要先有 durable identity，再启动执行？

Step 先完成调用事件发布，再 fork 本地工具；providerExecuted 的工具不在本地重复执行。[F1] 这让观测和恢复有已知 invocation 身份，不能把同一 provider-hosted action 再跑一次。

但 call-before-body 不等于副作用 exactly-once。工具成功执行到结果发布之间仍可能崩溃；取消也必须分离“工作停止”与“结果结算”。把未知结果补为失败，不能据此断言工具没有修改任何东西。

## 5. 适用条件、验证与反证

**上游实验待运行：** 请求发出后替换同名工具，检查实际执行版本；为 output/content/metadata 填不同合成信息，捕获机器消费者、持久记录与下一模型请求；制造输入 codec 失败，确认 handler 未运行；制造完整输出保留失败，检查不会发布伪成功。

若只有两个静态工具、没有 UI 或 Code Mode，拆三种表示可能不必要。若要加入程序化工具编排、复杂输出和多前端，单个字符串返回值则容易成为隐形耦合。

应学会判断：什么需要被模型知道、什么只属于机器计算、什么只用于展示；一次 schema 与 handler 的绑定应持续多久；哪些安全检查必须不依赖模型和插件的自律。

[D1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/tools.md
[F1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L75-L290

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：用 prepared 工具执行器，并保留调用身份

源码：[`session/runner/step.ts`，L86–L150](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L86-L150)。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L86-L150 -->
```ts
    const executeTool = (call: ToolCall) => {
      if (input.prepared.request.toolChoice?.type === "none")
        return new Tool.Error({ message: "Tools are disabled after the maximum agent steps" })
      return input.prepared.executeTool({
        sessionID: input.sessionID,
        agent: input.agent,
        messageID: input.assistantMessageID,
        call,
        progress: (update) => publisher.progress(call.id, update),
      })
    }
```

#### 逐段讲解

执行入口绑定 `input.prepared`，不是在响应回来后随意从全局查一个同名函数。[工具契约](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/tools.md) 对 request-scoped tool snapshot 有进一步规定；这里看到实际消费者使用 prepared executor。

达到最大步骤后的 toolChoice=none 在本地有错误分支，因此不只依赖模型听从提示。这个条件是步数相关限制，不能代替用户权限与 OS 隔离政策。

Session、Agent、assistant message 与 call 一起传递，把工具结果归到正确的 assistant 请求。call ID 不能脱离所属消息/步骤被当作任意全局唯一键。

### 3. 核心源码 B：发布调用事实之后才运行 body

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L86-L150 -->
```ts
          yield* publisher.publish(event)
          if (event.type !== "tool-call" || event.providerExecuted) return
          toolRuns.push({
            call: event,
            fiber: yield* Effect.uninterruptibleMask((restore) =>
              restore(executeTool(event)).pipe(
                Effect.flatMap(toolOutput.truncate),
                Effect.flatMap((outcome) => publisher.toolExecution(event.id, event.name, outcome)),
                Effect.catchTag("Tool.Error", (error) =>
                  publisher.failTool(event.id, toSessionError(error), error.metadata).pipe(Effect.asVoid),
                ),
              ),
            ).pipe(Effect.forkScoped),
          })
```

#### 逐段讲解

先等待 publish，再判断是否启动本地工具。`providerExecuted` 的调用不能在本地执行第二遍；只有完整 `tool-call` 事件进入这一分支，增量参数片段不触发 body。

`restore(executeTool(event))` 把工作本身置于可中断区域，而截断和 terminal publication 位于受保护处理链。`forkScoped` 把异步任务的寿命绑定 Scope，避免只留一个不受管理的 Promise。

`toolOutput.truncate` 在发布结果之前运行；如果把它放在 UI 渲染后，不能限制真正送给模型的内容。完整保留、媒体和 metadata 的规则要进一步读 ToolOutput 与 registry，不能把这一个函数当作总内存上限。

catchTag 只翻译特定 Tool.Error，没有使用 catch-all 把 interruption 和 defect 都变成模型可见字符串。**分析：** 可预期工具失败、用户取消和运行时错误应该保留不同控制语义。

### 4. 核心源码 C：停止所有已启动的工具

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L86-L150 -->
```ts
    const toolRuns: Array<{
      readonly call: ToolCall
      readonly fiber: Fiber.Fiber<void, Permission.DeclinedError | QuestionTool.CancelledError>
    }> = []
    const interruptTools = Effect.suspend(() => Fiber.interruptAll(toolRuns.map((run) => run.fiber)))
```

记录的是 invocation 与 Fiber 的对应关系，不只有工具名称。`Effect.suspend` 延迟读取 toolRuns，使执行取消效果时使用那时已经登记的任务，而不是构造之初的空数组。

类型中保留权限拒绝和问题交互取消。取消请求不是事务回滚；工具可能已经产生外部效果，但结果尚未发布。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/opencode/03-tools-sandbox.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
