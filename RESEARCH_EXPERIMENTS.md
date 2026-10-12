# 机制实验：验证反例，不冒充上游运行测试

[总目录](README.md) · [测试源码](tests/test_design_mechanisms.py) · [机器报告说明](validation/README.md)

## 1. 为什么做小模型，而不是只给一段设计故事？

某些结论可以用明确假设和很少状态检验，例如在途并发上限能否限制所有结果积压、一个 busy 标记会不会在特定窗口丢唤醒。这些实验不需要真实模型，更不应该让模型随机输出掩盖状态机问题。

本轮实现并运行了 22 项 Python 标准库确定性测试。它们全部是独立编写的教学模型，不是从三个仓库抽出的运行组件，不使用 Effect/Tokio/Cordis，不调用 LLM，不执行工具进程，不测 OS 沙箱。它们不能作为产品缺陷或性能成绩的证明。

## 2. 实验 A：在途上限与待提交结果

假设所有 body 独立、没有 hooks、没有取消、没有实际 I/O，只有规定耗时；按模型顺序提交。输入为 `[100, 1, 1, 1, 1, 1, 1]`，并发宽度为 2，时间是抽象离散单位。

| 模型策略 | 最大在途 | 最大已完成待提交 | 逻辑完成时间 |
|---|---:|---:|---:|
| 仅限制在途、完成后补充 | 2 | 6 | 100 |
| 同时限制已启动未提交窗口为 2 | 2 | 1 | 103 |

这些值来自 `schedule()` 实际运行。第一个结果说明并发计数不限制待提交积压；第二个说明额外预算可减少 backlog，却可能降低 overlap。这里不计算 DSH 的真实 heap/RSS，也不模拟它的全部动态分类和保留结果语义。

同一实验还确认完成顺序可以是 `(1,2,3,4,5,6,0)` 而提交顺序是 `(0,1,2,3,4,5,6)`。记录完成顺序也能重放，因此“可重放”并不单独要求模型顺序提交。相关研究见 [DSH 03](dsh/03-tools-sandbox.md)。

## 3. 实验 B：增量投影与完整数组快照

假设每次追加一条消息、只投影新消息，同时向调用者返回完整的新外层数组。追加 100 条后，投影计数是 100，数组引用复制总量是 1+2+…+100=5,050。

这不是 DSH 的运行时间测量；它说明两项不同工作不能用一个 O(delta) 描述。真实成本还包括调用频次、Surface 访问、序列化和模型请求。相关研究见 [DSH 02](dsh/02-context-session.md)。

## 4. 实验 C：同一日志并不能区分所有外部世界

世界 A：已记录 call-x、外部效果为 0。世界 B：同样已记录 call-x、外部效果为 1、结果还没记录。测试确认日志观察相同而效果不同；独立的幂等执行集合才能阻止重复应用同一 invocation。

这只在给定观察条件下展示歧义，不是宣称 exactly-once 在所有系统都不可能。数据库同事务效果、外部幂等协议等增加了信息和约束。相关研究见三项目的 07。

## 5. 其他机制测试及适用边界

| 模型 | 验证什么 | 不覆盖什么 |
|---|---|---|
| busy / doorbell | 特定最后检查与 idle 间的唤醒反例 | 完整 Effect coordinator 状态空间 |
| 请求快照 / 实时许可 | schema 一致性不等于当前授权 | 所有权限与撤销实现 |
| 旧对象 / goal revision | 相同 ID 下旧生命周期或旧版本不同 | 分布式 lease、fencing、重启 |
| 插件 naive undo / replay | A/B 覆盖后撤销 A 的反例 | 插件 transform 纯度、实际 Supervisor |
| load-error / blocked | 保留旧版与政策禁止语义不同 | 所有 blocked 来源和管理策略 |
| independent feed | 慢订阅者可以单独失败 | HTTP、socket、线程、真实背压 |
| 事件数 / 字节 | 同条目数可以有极不同 payload 大小 | 实际内存布局与压缩 |
| handoff high watermark | 后续成功可能越过失败缺口 | OTel 后端队列和远端重试 |
| retry hook / hard guard | 默认决定可覆盖与最终预算不同 | Effect Schedule 的所有边界 |
| round 数 / token 数 | 相同轮数不能决定总 token | 真实模型 tokenization 与计费 |
| checkpoint refusal | 明确 gate 可阻止抽象 body | fsync/文件系统/崩溃一致性 |

## 6. 复现

```bash
python3 -m unittest discover -s tests -p 'test_design_mechanisms.py' -v
python3 scripts/run_mechanism_models.py --report /tmp/mechanism-models.json
```

全部仓库测试另外包含 7 项原核验器测试和 4 项构建器测试，共 33 项；三类测试目的不同，不能把总数写成“33 项 Agent 测试通过”。

## 7. 真实上游验证矩阵：全部待运行

| 主题 | 需要真正观测的内容 |
|---|---|
| Loop | 同会话输入 promote、steer、取消与 successor 的时序 |
| Context | 三视图、真实请求、压缩保真、续接失效和缓存 |
| Tools | 调用/结果配对、并发冲突、取消后进程清理和实际输出预算 |
| Streaming | 各阶段断流、provider-hosted 行动、已提交输出与重试 |
| Plugin | 更新失败、明确禁用、旧请求与卸载、迟到资源释放 |
| Orchestration | 子任务归属、fresh/fork/resume、结果通知与父取消 |
| Persistence | 各检查点崩溃、双 writer、租约、外部结果未知 |
| Observability | 日志/实时/导出三通路、缺口、去重、脱敏、实际 RSS |

这些实际实验尚未做。每篇已给出具体失败窗口与断言，后续应在隔离工作区运行，并标记 PASS/FAIL/SKIPPED/INCONCLUSIVE，不能用模型最终自述完成代替验收。
