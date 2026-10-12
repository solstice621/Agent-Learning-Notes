# OpenCode 05｜Plugins：失败更新、代际与卸载顺序

[总目录](../README.md) · P1 · 对照：[Codex](../codex/05-extension-architecture.md) / [DSH](../dsh/05-extension-architecture.md)

**固定源码：** `anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。原文来自当前 `plugin/supervisor.ts`，不是历史 ADR 的接口草图。未运行热更新实验。

## 1. 研究问题

插件架构最难的不只是加载一个模块，而是新版本失败时保留什么、旧资源何时关闭、异步结果是否属于当前 generation、运行请求是否看到完整能力集合。

历史 [Catalog / Config 决策记录](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/catalog-config-plugin-lifecycle.md) 可用于理解方案比较；以下实际行为以固定源码为准。

## 2. 核心源码 A：新版本失败，不一定卸掉旧版本

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

### 逐段讲解

failure 独立记录更新失败与诊断 ref；然后查找可保留的旧 generation。如果存在，就把旧对象维持在 packages/enabled 中，而不是将失败的新对象发布出去。

“更新失败”与“当前能力不可用”因此不是同义词。但这段只处理未成功成为 generation 的加载错误；不能推导已激活插件内部抛异常也总能自动回滚。

**设计分析：** 将期望 revision、实际运行 generation 和 failure 状态分开，能防止错误配置一次性移除正在服务的能力。代价是操作者必须能看见当前仍是旧版，不能静默宣称升级成功。

## 3. 核心源码 B：重复 ID 不应拖垮整个 generation

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

## 4. 核心源码 C：依赖关闭前先卸载消费者

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

## 5. 与 Agent 请求的连接

Runner 在执行入口等待插件 activation。请求工具又有独立的 prepared snapshot。需要同时考虑新请求等待就绪、已有请求使用哪些已捕获对象、旧 Scope 什么时候可关闭；不能以“配置文件已经保存”代表变更已完全生效。

## 6. 实验与验收

做一个只提供合成工具的本地插件：先加载有效版本，再制造导入失败，核对旧 generation 保留与失败可见；再触发重复 ID；最后让工具阻塞时禁用插件，记录活动任务和资源卸载。

验收产物是 generation 时间线，分别标注 desired、running、failed、retired 状态。能解释模块加载失败与执行异常为什么不同、为什么插件清理必须早于依赖关闭、为什么历史方案草图不能当作当前 API。

本篇未运行实验或证明全部卸载竞态。源码许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
