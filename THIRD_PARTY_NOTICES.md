# 第三方源码与许可声明

本仓库的源码节选分别来自 OpenAI Codex、OpenCode 与 DeepSeek Harness 的官方仓库。所有者保留原版权；中文分析、选择与组织并不改变原源码许可。本项目不是上游官方文档，也不代表上游为讲解或实验结论背书。

原文代码块为固定提交的连续节选，保留原代码和注释。注解代码块在这些节选中额外插入独立的 `// 笔记：` 中文注释行，并用 `annotated-source` 标记与原文块的 `source` 标记区分；新增注释属于本笔记，不代表上游作者的表述。去除这些显式注释后，剩余行仍须与上游连续原文一致。节选不等于完整可执行文件。每段标明来源文件、完整 Commit 和定位行号。不得将讲解作者视为第三方源码作者。

| 来源 | 固定提交 | 许可与保留材料 |
|---|---|---|
| [OpenAI Codex](https://github.com/openai/codex) | `a9b0815167c27ab13719dd12d13b63e02b70d221` | [Apache License 2.0 副本](licenses/codex-Apache-2.0.txt)、[上游 NOTICE](licenses/codex-NOTICE.txt)；Copyright 2025 OpenAI |
| [OpenCode](https://github.com/anomalyco/opencode) | `60a212c0769acd96b446acbadeb790486830f91d` | [MIT License 副本](licenses/opencode-MIT.txt)；Copyright (c) 2025 opencode |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | `d743267388641bc76f17c45ce8b4c231aed1d32c` | [MIT License 副本](licenses/dsh-MIT.txt)；Copyright (c) 2026 DeepSeek |

上述副本取自相应固定提交的根 LICENSE/NOTICE。源码节选不包含上游依赖包的完整实现；如后续加入其他目录或依赖源码，应重新检查该文件及所属目录的许可，不根据仓库根许可证猜测全部第三方内容。

`source-lock.json` 与各篇 `source` / `annotated-source` 标记用于追踪来源；检查器只读取公开源码，不执行上游代码。源代码许可与文档质量/运行验证是不同问题：保留许可不意味着代码已测试，原码比对也不证明系统正确性或新增注释的解释成立。
