# OpenCode 05｜插件管理：状态重算与更新失败处理

假设模型原名叫 X，插件 A 把它改成 A，插件 B 又改成 B。现在卸载 A：如果 A 执行“恢复成 X”，仍在工作的 B 就被覆盖了。

**更可靠的办法是：保留仍有效的修改，按原顺序重新算一遍。** 插件更新出错时，再根据出错阶段决定保留还是撤下。

这套机制位于项目实例内部。`PluginSupervisor` 决定本次应该启用哪些插件，`Plugin` 管理它们的加载和清理，`State` 根据插件登记的修改生成工具、命令等领域状态。可以把它理解为：先决定谁在场，再计算它们合起来提供什么。

<!-- decision: O05-D1 | 卸载后怎样保住其他插件的修改？ -->
## 卸载插件后的状态重算

插件登记的是一段修改步骤，源码叫 `transform`。每次需要重建，`State` 都先创建新对象，再顺序执行仍有效的步骤：

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/state.ts#L172-L184 -->
```ts
  const get = () => {
    // 笔记：没有变化时直接复用已算好的状态，避免每次读取都重放插件。
    if (closed || !dirty) return state
    while (true) {
      const started = version
      // 笔记：重建从全新初始值开始，剩余修改依次重放；不在旧读者持有的对象上撤销修改。
      const next = options.initial()
      const editor = options.editor(next)
      for (const transform of transforms) {
        try {
          transform.run(editor)
        } catch (cause) {
          if (!transform.group) throw cause
          // 笔记：有分组的插件失败时撤下整组贡献；后续版本检查会丢弃这一半成品并重建。
          disable(transform.group, { state: options.name ?? "anonymous", cause })
        }
```

回到例子：卸载 A 后，重新从 X 开始，只执行 B，结果仍然是 B。关闭插件的资源作用域时，它登记的步骤会被删除，下一次重建自然就不再包含它。旧读者已经拿到的对象也不会被原地改写。

重新算有成本。因此注册表会保留开头连续未变的插件，只清理并重新加载从第一个变化位置往后的部分。即使 B 自己没更新，只要前面的 A 变了，B 也可能重载，以保住修改顺序。`State.batch` 则把这段过程中重复的变化通知合并起来；它没有替任意外部操作提供回滚。

这里最重要的写法约束是：修改步骤要能重复执行。把“发送邮件”放进 `transform`，每次重算都可能再发一封。

<!-- decision: O05-D2 | 新插件坏了，什么时候还能继续用旧版？ -->
## 加载失败与策略禁用的处理差异

设 v1 正常，刚保存的 v2 有语法错误，连模块都无法导入。Supervisor 会记录失败，并把已运行版本放回本次启用名单：

<!-- annotated-source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/supervisor.ts#L79-L90 -->
```ts
    // 笔记：这是新版模块加载失败分支；明确被策略禁用的 blocked 分支在此前单独处理。
    if ("error" in plugin) {
      failures.set(operation.target, {
        source: pluginSource(operation.target),
        state: { status: "failed", error: plugin.error, ref: plugin.ref },
        features: { server: true },
      })
      // The new revision never became a generation, so the one already running keeps its place.
      // 笔记：新版尚未成为运行版本，先找仍可保留的旧版；从未成功加载过则没有回退对象。
      const retained = packages.get(operation.target) ?? running.get(operation.target)
      if (!retained) continue
      packages.set(operation.target, retained)
      enabled.add(retained.id)
      continue
```

这段保留的是“新版还没加载起来”的情况。继续往下追，普通初始化失败时，注册表也会尝试重新加载旧版；但如果是修改步骤在重放时抛错，系统会撤下该插件整组贡献，避免留下改到一半的状态。

还有一种更直接的撤下：策略已经禁止使用这个插件。模块加载器会先检查 `integration.use`，命中禁止规则就返回 `blocked`，Supervisor 不把旧版放回名单。这次重读确认了具体来源，而不只是从变量名猜“可能被禁用”。相关分支见[加载器](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/module.ts#L49-L60)。

所以，“更新失败就继续用旧版”太宽泛。需要分别处理导入失败、初始化失败、重放失败和明确禁用。

## 适用条件与实现成本

一次运行就退出的小工具，修改插件后重启通常已经够用。长期服务需要热更新，才值得支付重建、顺序维护、旧资源清理和失败隔离的成本。

**小自测：** A、B 依次覆盖同一个名字，卸载 A 后应该显示什么？如果 B 被策略禁用，可以用“保留旧版”维持它吗？

<details>
<summary>展开答案</summary>

仍显示 B，因为只重放剩余修改。B 被禁用后应退出当前启用名单；保留旧版适用于特定加载失败，不能绕过禁用。

</details>

> 证据边界：已读实现及卸载、失败回退、组织策略变化的上游测试，未运行。历史 Catalog 方案只帮助理解动机；这里按当前 `State` 与插件注册表讲解。
