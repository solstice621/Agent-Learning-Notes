import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

export const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export async function buildBook() {
  const rendered = spawnSync(process.env.PYTHON || 'python3', ['scripts/build_design_edition.py'], { cwd: root, encoding: 'utf8' });
  if (rendered.status !== 0) throw new Error(rendered.stderr || rendered.stdout || 'Note generation failed');
  const lock = JSON.parse(await readFile(join(root, 'source-lock.json'), 'utf8'));
  const entries = ['# 目录', '', '* [关于这套笔记](README.md)', '* [Agent 架构导览](START_HERE.md)', ''];
  for (const [directory, title] of [['codex', 'Codex'], ['opencode', 'OpenCode'], ['dsh', 'DeepSeek Harness']]) {
    entries.push(`## ${title}`, '');
    entries.push(`* [00 · 整体架构与任务执行链](${directory}/00-architecture.md)`);
    for (const topic of lock.topics) {
      const path = `${directory}/${topic.id}-${topic.slug}.md`;
      const text = await readFile(join(root, path), 'utf8');
      const heading = text.split('\n')[0].replace(/^#\s*/, '').split('｜').slice(1).join('｜');
      if (!heading) throw new Error(`Missing chapter title in ${path}`);
      entries.push(`* [${topic.id} · ${heading}](${path})`);
    }
    entries.push('');
  }
  entries.push('## 机制对比与练习', '',
    '* [三项目执行机制对比](COMPARISON.md)',
    '* [Agent 设计要点](RESEARCH_FINDINGS.md)',
    '* [48 个问题索引](DESIGN_INDEX.md)',
    '* [阅读路线与综合练习](LABS.md)',
    '* [教学模型与实验](RESEARCH_EXPERIMENTS.md)', '',
    '## 来源与研究记录', '',
    '* [研究方法](RESEARCH_METHOD.md)',
    '* [源码地图](SOURCES.md)',
    '* [重新研究后的修正](RESEARCH_EVIDENCE.md)',
    '* [源码重读记录](research/reread/README.md)',
    '  * [Codex 架构核对](research/reread/codex-architecture.md)',
    '  * [Codex 01–04](research/reread/codex-01-04.md)',
    '  * [Codex 05–08](research/reread/codex-05-08.md)',
    '  * [OpenCode 架构核对](research/reread/opencode-architecture.md)',
    '  * [OpenCode 01–04](research/reread/opencode-01-04.md)',
    '  * [OpenCode 05–08](research/reread/opencode-05-08.md)',
    '  * [DSH 架构核对](research/reread/dsh-architecture.md)',
    '  * [DSH 01–04](research/reread/dsh-01-04.md)',
    '  * [DSH 05–08](research/reread/dsh-05-08.md)',
    '* [验证报告说明](validation/README.md)',
    '* [勘误](ERRATA.md)',
    '* [修订记录](RESEARCH_CHANGELOG.md)',
    '* [源码归属与许可](THIRD_PARTY_NOTICES.md)',
    '* [本地阅读与构建](LOCAL_BOOK.md)', '');
  await writeFile(join(root, 'SUMMARY.md'), entries.join('\n'));
  await mkdir(join(root, 'book-plugin/assets'), { recursive: true });
  await copyFile(join(root, 'node_modules/mermaid/dist/mermaid.min.js'), join(root, 'book-plugin/assets/mermaid.min.js'));
  const built = spawnSync(process.execPath, [join(root, 'node_modules/honkit/bin/honkit.js'), 'build', '.', '_book', '--reload', '--log=warn'], { cwd: root, stdio: 'inherit' });
  if (built.status !== 0) throw new Error(`HonKit build failed (${built.status})`);
  console.log(`Book generated: ${join(root, '_book/index.html')}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  buildBook().catch(error => { console.error(error.message); process.exitCode = 1; });
}
