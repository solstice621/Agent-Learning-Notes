# 在本地阅读这本书

[总目录](README.md)

本地书籍由 [HonKit](https://github.com/honkit/honkit) 生成，沿用 GitBook 的 `book.json`、`SUMMARY.md` 和 Markdown 结构。页面提供分组目录、上一篇/下一篇、中文全文搜索、代码高亮和折叠答案。流程图和字体资源也保存在本地，不依赖 CDN。

较宽的架构图默认显示全图，点击“放大阅读”后可横向滚动查看原始大小；再次点击可恢复全图预览。

## 开始阅读

在本仓库目录运行：

```bash
npm ci
npm run book:serve
```

需要 Node.js 22 或更新版本，以及 Python 3。已经安装依赖时，可以跳过 `npm ci`。启动命令会先同步笔记、生成目录和静态页面，再打印本地网址，通常是 `http://127.0.0.1:4000`；若端口被占用，会尝试后续端口。按 `Ctrl+C` 停止。

首次安装需要网络；安装完成后，书籍构建和站内阅读可离线使用。外部 GitHub 源码链接仍需联网。

## 只生成文件

```bash
npm run book:build
npm run book:check
```

输出在 `_book/`。`book:check` 检查生成页面的本地链接、资源和搜索索引。`_book/index.html` 是首页；使用本地服务阅读，搜索和页面切换才能可靠工作。修改 Markdown 后，重新构建，或停止并重启 `book:serve`。

只预览已经生成的文件：

```bash
npm run book:serve -- --no-build
```

## 修改章节和样式

专题笔记仍编辑 `research/decisions/` 中的源稿。构建书籍时会自动同步到 24 篇专题主文；三篇整体架构直接编辑各项目的 `00-architecture.md`。目录每个项目先读架构，再读八篇专题；章节标题自动写入 `SUMMARY.md`，因此无需手动维护两份标题。

其他目录分组在 `scripts/build_book.mjs` 中维护；主题细节在 `book-plugin/assets/notes.css` 中调整。生成文件、依赖和临时缓存已从 Git 跟踪及书籍内容中排除。详细研究记录保留在附录，不重复展示写作源稿。

## 在线阅读与自动发布

公开网站：[Agent Learning Notes](https://solstice621.github.io/Agent-Learning-Notes/)。[架构导览](https://solstice621.github.io/Agent-Learning-Notes/START_HERE.html) 对应本地的 `START_HERE.html` 页面，访问在线网站无需启动本地服务。

GitHub Pages 使用 GitHub Actions 发布。将修改提交并推送到 `main` 后，`Publish reading website` 工作流会安装锁定依赖、构建书籍、检查链接和搜索索引，再发布 `_book/`。也可以在仓库的 Actions 页面手动运行该工作流。生成目录、依赖和源码缓存不提交到仓库。
