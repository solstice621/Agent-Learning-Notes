# OpenCode 05｜为什么插件卸载要重新计算状态，坏更新又不应一律保留旧版本？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 问题：插件修改的不是一张静态功能表

模型目录可以来自配置、远程数据和认证状态；插件可随运行加载、更新或移除。朴素实现让每个插件直接修改全局对象，卸载时“把它改过的字段改回来”。当多个插件覆盖相同字段，这种逆操作可能错误恢复过时值。

官方历史决策记录比较过 Config transforms 与 Catalog transforms，明确选择后者；当前生命周期则应看 PluginSupervisor，而不是把历史接口草图当作当前 API。[A1][F1]

## 2. 决策 O05-D1：为什么重放贡献比让每个插件自己 undo 更可控？

**分析例子：** 基线名称 X，插件 A 改为 A，插件 B 再改为 B。卸载 A 时若它执行“恢复 X”，会覆盖仍有效的 B。与其要求每个插件理解后续覆盖，不如从基线重放当前有效贡献，重新产生最终状态。

官方选定 Catalog transforms 的直接理由是：允许任意 Config transform 修改任何配置，会让系统无法安全判断只重载某一域是否够用，可能需要全服务 reload；将变化限制在 Catalog 后，可将重建职责放回 Catalog。[A1]

| 方案 | 优势 | 成本或反例 |
|---|---|---|
| 插件直接修改＋自行 undo | 简单场景代码少 | 叠加覆盖和卸载顺序容易破坏状态 |
| 任意 Config transform＋全局 reload | 一个统一扩展入口 | 变化影响面过大、就绪震荡 |
| 域内 transform＋重放有效贡献 | 撤销可重新计算、影响域明确 | 顺序、重建、diff 发布需要协议 |
| 插件独立进程＋纯协议 | 隔离更强 | 状态同步、序列化、故障管理更复杂 |

重放不是天然免费：插件 transform 若不纯、含外部副作用，重复运行会有不同效果；变化频繁还可能造成重建放大。历史文档也指出 Catalog 重建的 debounce 不会从 transform API 自动出现，需额外协调。[A1]

## 3. 决策 O05-D2：为什么普通更新失败保留旧 generation，而明确 blocked 不应如此？

Supervisor 对新 revision 加载失败记录独立失败，并保留先前运行 generation；重复 ID 也不会让整代内建插件一起丢失。但 `blocked` 分支会撤销先前包的启用与记录。[F1]

**推导：** “新版坏了”与“政策不允许这个插件继续”是不同事件。对前者 last-known-good 提高可用性；对后者继续使用旧版可能违背禁用意图。不能将保留旧版本作为所有错误通用恢复策略。

时间线：t0 A_v1 活跃；t1 A_v2 导入失败；保持 v1 是一种合理降级。若 t1 是明确禁止 A，则保留 v1 不是降级，而是绕过当前政策。具体 blocked 的全部来源尚需继续审计，本篇只依已读分支说明二者在实现中被区分。

generation 编号还用于拒绝过期异步更新结果。observed/hold 则使变更即使被 sliding queue 合并，也不会在激活未完成时误报 ready。[F1] 这些各自防止不同竞争，不能笼统叫“缓存”。

## 4. 卸载的隐藏成本：旧请求还拿着旧能力

请求捕获工具值能保证声明与执行一致，但也意味着新 generation 激活后，旧请求可能仍持有旧工具。资源清理必须与依赖服务关闭有明确顺序；Supervisor 为 registry.close 安排 finalizer。[F1]

**研究边界：** 这段源码不能证明全部 registry 内部的热卸载都能等待所有活动调用。应该继续追踪 Scope 和请求快照的实际引用关系。对必须立即撤销的能力，更新逻辑还需要实时拒绝或取消，而不是只等待对象最终回收。

是否值得热更新？短命单次 CLI 可以直接重启，以明显更低的复杂度获得配置一致性；长期多 Session 服务不能随意停机时，代际与就绪屏障才更有价值。学习成熟系统不等于默认复制它所有热重载能力。

## 5. 验证与自测

本仓库机制实验构造 A/B 覆盖后卸载 A，比较 naive undo 与 replay 的结果，属于自建模型，不是 PluginSupervisor 测试。

**上游实验待运行：** 有效 v1 → 无法加载 v2 → 明确 blocked 三步比较；配置突发中让旧检查结果晚到，确认不会覆盖新 generation；工具执行中禁用插件，检查旧工作、新请求和资源回收分别怎样变化。

读后应能回答：哪些变化适合保留旧版，哪些需要 fail-closed；撤销操作是逆修改还是重建有效贡献；为了热更新究竟增加了哪些所有权和同步成本。

[A1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/catalog-config-plugin-lifecycle.md
[F1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/supervisor.ts#L1-L270

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：新版本失败，不一定卸掉旧版本

源码：[`plugin/supervisor.ts`，L65–L168](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/supervisor.ts#L65-L168)。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/supervisor.ts#L65-L168 -->
```ts
    if ("error" in plugin) {
      failures.set(operation.target, {
        source: pluginSource(operation.target),
        state: { status: "failed", error: plugin.error, ref: plugin.ref },
        features: { server: true },
      })
      // The new revision never became a generation, so the one already running keeps its place.
      const retained = packages.get(operation.target) ?? running.get(operation.target)
      if (!retained) continue
      packages.set(operation.target, retained)
      enabled.add(retained.id)
      continue
    }
```

#### 逐段讲解

failure 独立记录更新失败与诊断 ref；然后查找可保留的旧 generation。如果存在，就把旧对象维持在 packages/enabled 中，而不是将失败的新对象发布出去。

“更新失败”与“当前能力不可用”因此不是同义词。但这段只处理未成功成为 generation 的加载错误；不能推导已激活插件内部抛异常也总能自动回滚。

**设计分析：** 将期望 revision、实际运行 generation 和 failure 状态分开，能防止错误配置一次性移除正在服务的能力。代价是操作者必须能看见当前仍是旧版，不能静默宣称升级成功。

### 3. 核心源码 B：重复 ID 不应拖垮整个 generation

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/supervisor.ts#L65-L168 -->
```ts
  // Registry activation dies on a duplicate ID, which would drop the whole generation including builtins.
  // Keep the first occurrence in boot order and report later ones like any other plugin setup failure.
  const duplicate = (plugin: Plugin.Generation, index: number) =>
    ordered.findIndex((other) => other.id === plugin.id) !== index
```

判定以启动顺序中首次出现的位置为准。后续返回结构分别过滤 active plugins，并把重复项加入 failures。这里不是工具同名覆盖机制，而是 plugin ID 冲突处理；不要把两种命名空间混淆。

**反例练习：** 如果先把整组插件交给 registry 才发现重复，内建能力也可能随这一代激活失败。用隔离配置添加一个重复 ID，观察哪些插件仍运行、哪里报告失败。

### 4. 核心源码 C：依赖关闭前先卸载消费者

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/supervisor.ts#L65-L168 -->
```ts
    let release: Effect.Effect<void> | undefined = yield* registry.hold()
    yield* Effect.addFinalizer(() => release ?? Effect.void)
    // Built-ins capture services from this layer; unload them before those services close.
    yield* Effect.addFinalizer(registry.close)
    let packages = new Set<string>()
    // Last generation handed to the registry per target; a failed reload keeps it in place.
    let running = new Map<string, Plugin.Generation>()
    let outdated = new Set<string>()
    const updating = new Set<string>()
    let generation = 0
    let observed = 0
```

hold/release 表达就绪门的生命周期；finalizer 保证正常退出或失败时有清理入口。注释特别要求捕获服务的内建插件先卸载，再让依赖服务关闭，防止清理 callback 使用已经不存在的资源。

running/outdated/updating/generation/observed 各自表示不同状态，不应压成单一 `loaded:true`。此处只展示声明与初始化；异步代际检查及触发合并还要看后面的 activate/watch 实现，不能从变量名推断全部保证。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/opencode/05-extension-architecture.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
