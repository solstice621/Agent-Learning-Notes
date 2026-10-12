# 验证范围与报告

[总目录](../README.md) · [证据方法](../RESEARCH_METHOD.md)

本目录保存实际运行产生的报告。当前内容分为 3 篇整体架构与 24 篇专题，专题覆盖 48 个问题。专题原有 49 段源码已增加中文注释；架构篇的源码块也纳入核验，最新总数以报告为准。旧版摘录计数不再作为当前总量约束。

| 报告 | 检查什么 | 不证明什么 |
|---|---|---|
| [source-excerpts.json](source-excerpts.json) | 专题和架构的原码片段、固定版本、链接；注解块仅去掉显式笔记注释后比对；模式见 `mode` | 中文注释的语义、设计动机、推导或真实运行结果 |
| [design-structure.json](design-structure.json) | 源稿生成一致性、问题编号与篇目覆盖 | 内容正确或易懂 |
| [mechanism-models.json](mechanism-models.json) | 22 项独立 Python 教学模型 | 上游 Agent、真实模型、性能或 OS 沙箱 |

报告包含时间、笔记仓库 HEAD 和输入文件摘要。未提交修改时，HEAD 仍指向旧提交，因此判断对应内容应看摘要。后续修改相关输入后须重跑；PASS 只对当次输入负责。

源码核验的 `ONLINE_PINNED_SOURCE` 模式可能命中已保存的固定 URL 缓存；`LOCAL_PINNED_SOURCE` 模式检查本地固定版本标记并逐行比对；`STRUCTURE_ONLY` 不读取源码。以实际报告里的模式与来源字段为准，不把离线结构通过说成联网源码通过。

本轮重读了相关上游测试源码，但未运行上游测试。内容复核与程序校验分开：前者查看架构图、正常调用链、状态归属与代码注释是否一致，后者检查原码和文档生成。两者都不是上游全仓库审计。

## 重跑

```bash
python3 scripts/build_design_edition.py --check --report validation/design-structure.json
python3 scripts/verify_notes.py --report validation/source-excerpts.json
python3 scripts/run_mechanism_models.py --report validation/mechanism-models.json
python3 -m unittest discover -s tests -v
```

已下载源码且各目录带 `.source-pin.json` 时，可用 `--upstream-root /path/to/sources`；其下应有 `codex/`、`opencode/`、`dsh/`，标记的 repository 和 commit 必须匹配版本锁。该标记记录来源身份，实际摘录内容仍须比对。
