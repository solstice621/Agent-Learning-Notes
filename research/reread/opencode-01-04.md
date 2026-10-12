# OpenCode 01–04｜重新阅读记录

日期：2026-10-12。固定源码 SHA：`60a212c0769acd96b446acbadeb790486830f91d`。

本轮先阅读项目入口和跨模块契约，再沿真实执行查核心实现、被调模块及测试。下列测试均为阅读测试代码与断言，**未执行上游测试**，未运行模型、付费 API、构建、性能或隔离实验。示例情景是教学构造，不冒充运行观测。

## 共用架构入口

- [README.md:1–129](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/README.md#L1-L129)：产品含终端/桌面等入口；不把某个界面请求当成整个执行生命周期。
- [specs/v2/README.md:1–38](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/README.md#L1-L38)：Protocol 定义 HTTP，Schema 定义公共与持久结构，Core 拥有执行和持久化；文档用于找跨模块关系，遇到漂移以固定实现为准。
- [packages/server/src/handlers/session.ts:307–335](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/handlers/session.ts#L307-L335)：`session.prompt` HTTP handler 调 Core facade。
- [packages/core/src/session/session.ts:145–175](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/session.ts#L145-L175)：Session 操作先 reconcile、准备、admit，最后按 resume 决定 wake。
- [packages/core/src/session/execution.ts:87–148](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L87-L148)：进程级 Execution 读取会话，进入所选 instance，再调用 runner；move/reload 可以重新选择实例继续。
- [packages/core/src/session/runner/llm.ts:54–295](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L54-L295)：Runner drain 在步骤边界控制输入递送，runStep 内管理重试，Attempt 负责模型流和工具结算。

## 01｜O01-D1、O01-D2

旧问题：durable input 与 wake 为什么分开；Step 为什么允许多个 Attempt。

实际追踪：

1. 入口与上下游：上方 HTTP → Session.prompt → [packages/core/src/session/inbox.ts:43–63](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/inbox.ts#L43-L63) → Execution → [packages/core/src/session/runner/llm.ts:161–195](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L161-L195)。
2. 核心协调器：[packages/core/src/session/run-coordinator.ts:74–145](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/run-coordinator.ts#L74-L145)。`pendingWake` 只保留需要再次 drain 的范围；消息数据仍在 inbox。循环返回与 settle 之间到达的 wake 可以启动 successor。
3. 步骤与尝试：[packages/core/src/session/runner/llm.ts:205–295](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L205-L295)；[packages/core/src/session/runner/step.ts:77–158](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L77-L158)。runStep 重试时重新准备和加载上下文，没有重新 promote；Continue 生成新 assistant ID，但继续使用这次逻辑步骤的重试政策。
4. 残留工具：[packages/core/src/session/runner/llm.ts:329–351](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L329-L351)。启动 drain 时将旧进程留下的 streaming/running 工具结算为失败，不直接重新执行工具。
5. 测试：[packages/core/test/session-run-coordinator.test.ts:10–27](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-run-coordinator.test.ts#L10-L27) 检查同会话并发 resume 共用一次运行；[packages/core/test/session-run-coordinator.test.ts:263–280](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-run-coordinator.test.ts#L263-L280) 检查收尾窗口 wake 创建后继；[packages/core/test/session-run-coordinator.test.ts:317–353](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-run-coordinator.test.ts#L317-L353) 检查取消清理期间到来的新 wake；[packages/core/test/session-runner.test.ts:5950–5989](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-runner.test.ts#L5950-L5989) 检查重试不消耗逻辑 step allowance；[packages/core/test/session-prompt.test.ts:566–619](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-prompt.test.ts#L566-L619) 检查重试消息 ID 的接纳幂等性。

确认与修订：

- 保留“输入内容与执行通知分离”的结论；不把 wake 描写为持久消息队列或崩溃恢复凭据。
- “同会话串行”指这个进程的协调器，不能推出跨节点唯一执行。
- 取消时清掉的是此前意图的提醒；清理期间新提醒仍可启动后继。正文保留三种等待含义，但删除大段接口罗列。
- 通俗主线改为“修测试时又补了一条要求”，再解释谁保存、谁提醒、重做哪里。

待运行：受控收尾竞态、取消等待时刻及重试期间输入递送的动态复核；未把现有测试源码称为本轮已通过。

## 02｜O02-D1、O02-D2

旧问题：准备指令为何早于递送输入；压缩为何影响历史与续接。

实际追踪：

1. 边界调用者：[packages/core/src/session/runner/llm.ts:163–203](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L163-L203)。prepareContext → promote → context.load；控制项可能在准备期间到达并要求重新判断。
2. 上下文选择与加载：[packages/core/src/session/context.ts:121–179](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/context.ts#L121-L179)。选择时收集工具和指令；load 再解析模型并按来源读取活动历史。
3. 指令实现：[packages/core/src/session/instruction-state.ts:38–87](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/instruction-state.ts#L38-L87) 与 [packages/core/src/instructions/index.ts:134–158](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/instructions/index.ts#L134-L158)。初始指令 unavailable 才阻塞；已有值时 unavailable 不产生删除 delta。
4. 历史查询：[packages/core/src/session/history.ts:16–107](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/history.ts#L16-L107)。从最新可适用压缩点读取，不删除完整记录；原生 checkpoint 的适用性根据来源判断。
5. 压缩与转换：[packages/core/src/session/compaction.ts:205–251](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/compaction.ts#L205-L251)、[packages/core/src/session/compaction.ts:312–366](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/compaction.ts#L312-L366)、[packages/core/src/session/runner/to-llm-message.ts:306–325](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/to-llm-message.ts#L306-L325)、[packages/core/src/session/provider-context.ts:17–58](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/provider-context.ts#L17-L58)。本地摘要与 provider 原生 replacement 是两种路径。
6. 传输续接：[packages/ai/src/protocols/open-responses-continuation.ts:96–182](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/ai/src/protocols/open-responses-continuation.ts#L96-L182)。append baseline 要求配置一致和完整前缀一致；显式 trigger 完成后不再建立该基线，保留连接。
7. 测试：[packages/core/test/session-runner.test.ts:1260–1286](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-runner.test.ts#L1260-L1286) 检查初始指令不可用时 input 留在 inbox 且没有请求；[packages/core/test/session-runner.test.ts:2092–2109](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-runner.test.ts#L2092-L2109) 检查后续不可用时保留已有值；[packages/core/test/session-checkpoint-transport.test.ts:94–128](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-checkpoint-transport.test.ts#L94-L128) 检查 trigger 后不带旧 response ID、但带原生 item 且复用 socket；[packages/core/test/session-compaction-transport.test.ts:80–128](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-compaction-transport.test.ts#L80-L128) 检查普通 context_management 的 compaction item 可以继续 ID 续接，恢复时完整重发仍含该 item。

确认与纠正：

- 准备顺序是特定前提的保证，不是“所有请求准备完成后才消费输入”：模型加载仍在 promote 之后。
- 删去旧稿“所有 provider-native state 在压缩后必须失效”的笼统印象。持久的原生 replacement 应继续使用；临时 previous_response_id 是否可复用由请求追加关系与 trigger 语义决定。
- 同 SHA 的 specs/v2/session.md:100–104 只概述 summary＋recent，不足以代表当前原生压缩实现；其“provider-native continuation state 不跨边界”不能推广为删除所有原生状态。
- 正文以“收到消息但规则未备齐”和“完整记录与本轮材料分开”串联，不引入冗长缓存术语列表。

独立交叉复核：子研究者 `compaction_evidence` 沿 AI 传输实现与上述两个 transport 测试只读复核；其定位随后被本稿作者重新打开核对。

待运行：指令故障恢复、切换模型后的原生窗口选择、真实请求捕获、摘要保真度及成本实验。

## 03｜O03-D1、O03-D2

旧问题：为何请求捕获工具；output/content/metadata 为什么分开。

实际追踪：

1. Context 调 registry.snapshot，见上方 context.ts；请求准备 [packages/core/src/session/model-request.ts:236–274](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/model-request.ts#L236-L274)、[packages/core/src/session/model-request.ts:394–417](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/model-request.ts#L394-L417) 捕获 definitions 与执行入口，处理 hook 移除和重命名。
2. Registry：[packages/core/src/tool.ts:225–284](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool.ts#L225-L284)。active/direct/codeModeTools 集合在 snapshot 内构造，execute 使用捕获集合。
3. 执行入口：[packages/core/src/session/runner/step.ts:95–142](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L95-L142)。先发布 tool-call，再启动本地工具；providerExecuted 调用不在本地重复执行。
4. 编解码与结果：[packages/core/src/tool/runtime.ts:29–69](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/runtime.ts#L29-L69)；[packages/core/src/tool.ts:113–155](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool.ts#L113-L155)；[packages/core/src/codemode/tool.ts:90–108](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/codemode/tool.ts#L90-L108)；[packages/core/src/tool-output.ts:67–117](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool-output.ts#L67-L117)；[packages/core/src/session/runner/publish-llm-event.ts:578–596](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/publish-llm-event.ts#L578-L596)。工具 runtime 执行并形成 output/content；Code Mode 优先把 output 交给程序；最终成功事件存 content＋metadata，不存独立 output。
5. 权限：[packages/core/src/tool/plugin/write.ts:64–95](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/write.ts#L64-L95) 与 [packages/core/src/permission.ts:158–188](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/permission.ts#L158-L188)、[packages/core/src/permission.ts:231–258](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/permission.ts#L231-L258)。写文件实现先发 permission.assert；服务重新读取会话/Agent 配置。不是 registry 自动给所有工具加检查。
6. 测试：[packages/core/test/tool-registry.test.ts:199–221](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/tool-registry.test.ts#L199-L221) 检查重载前后的捕获实现；[packages/core/test/tool-execute.test.ts:44–104](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/tool-execute.test.ts#L44-L104) 检查三类结果以及缺失/非法输出；[packages/core/test/session-step.test.ts:85–141](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-step.test.ts#L85-L141) 检查 final-Step toolChoice=none 时不会执行 handler。

确认与纠正：

- 请求级捕获绑定的是这次请求的实现和说明；不等于授予一次永久权限，也不等于 OS 沙箱。
- `output` 可以转换成默认 `content`；“不独立落库”不等于“该数据永远不会进入模型”。Code Mode 外层也可以选择把计算结果返回为最终内容。
- **发现固定版本文档漂移**：specs/v2/tools.md:129–154 声称 registry 先限制内容，再 execute.after，默认 head＋tail，metadata 独立校验及限额。实际 tool.ts:140–154 先运行 execute.after；step.ts:129–132 随后调用 ToolOutput.truncate；tool-output.ts:67–116 保留文本开头并另存完整文本，已有 metadata.truncated 会跳过通用截断。这里未发现文档所述 metadata 大小守卫。正文删除这些未获实现支持的说法，不把契约文字当成已存在行为。
- “输入无效不执行”由 runtime.decodeInput 位于 handler 之前支持；“调用已持久后执行”不提供外部副作用 exactly-once。

待运行：同名工具热更新期间的完整请求实验、机器值与持久内容捕获、权限变化及输出保留失败注入。

## 04｜O04-D1、O04-D2

旧问题：Retry 与 Continue 的区别；默认重试政策和不可覆盖预算的区别。

实际追踪：

1. Runner runStep → [packages/core/src/session/runner/step.ts:159–287](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L159-L287)。Attempt 根据已记录输出、工具结算、错误及 retry decision 返回结果。
2. 实际输出开始点：[packages/core/src/session/runner/publish-llm-event.ts:405–471](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/publish-llm-event.ts#L405-L471)。文本/推理/工具输入开始即标记 outputStarted，不能只看可见文本长度。
3. Runner 的 Outcome 处理：[packages/core/src/session/runner/llm.ts:270–295](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L270-L295)。Retry 保留 assistant ID；Continue 保存 synthetic 指令并换 ID；RecoverFull 和 Compacted 分别只允许有限特殊恢复。
4. 策略：[packages/core/src/session/runner/retry.ts:31–91](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/retry.ts#L31-L91)。十次一般 schedule，超时默认三次，Retry-After 预处理最多十五分钟；hook 在默认决定之后执行。schedule 耗尽的 return 发生在 hook 前。
5. 测试：[packages/core/test/session-runner.test.ts:5544–5593](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-runner.test.ts#L5544-L5593) 保留部分回答并创建新 assistant；[packages/core/test/session-runner.test.ts:5779–5813](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-runner.test.ts#L5779-L5813) 保留已结算工具且只执行一次；[packages/core/test/session-runner.test.ts:5885–5948](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-runner.test.ts#L5885-L5948) 检查共享重试预算耗尽；[packages/core/test/session-runner-retry.test.ts:12–47](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-runner-retry.test.ts#L12-L47) 检查默认三次超时政策；[packages/core/test/session-runner.test.ts:6035–6057](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/test/session-runner.test.ts#L6035-L6057) 检查未完成工具输入的失败结算。

确认与纠正：

- 通俗问题从“相同错误码”改为“已经写好文件后断线”，强调恢复策略看执行事实。
- 补明 Retry/Continue 都以策略允许为前提，已有输出不意味着必定续写。
- 同 SHA specs/v2/session.md:84 仍写最多四次；retry.ts 的 Schedule.recurs(10) 与 runner 测试一致，因此正文明确以十次为当前固定实现。
- 默认超时次数与 Retry-After 延迟预处理之后还有 hook，不能把默认值叫绝不可放宽安全上限；总体 schedule 次数耗尽则先于 hook。未声称插件可以无限突破所有预算。
- 工具已执行但结果未保存的崩溃窗口仍存在；“续写保留工具结果”不等于外部操作必定恰好一次。

待运行：mock clock 重试、hook 修改 timeout 决定、输出开始前后断流与工具执行次数；无真实请求或性能测试。
