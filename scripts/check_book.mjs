import { readdir, readFile, stat } from 'node:fs/promises';
import { resolve, dirname, extname } from 'node:path';
import { root } from './build_book.mjs';
const output = resolve(root, '_book');
async function filesAt(path) {
  const result = [];
  for (const entry of await readdir(path, { withFileTypes: true })) {
    const file = resolve(path, entry.name);
    if (entry.isDirectory()) result.push(...await filesAt(file));
    else if (entry.isFile()) result.push(file);
  }
  return result;
}
const all = await filesAt(output);
const pages = all.filter(file => extname(file) === '.html');
const errors = [];
const pageAnchors = new Map();
async function anchorsFor(file) {
  if (!pageAnchors.has(file)) {
    const html = await readFile(file, 'utf8');
    pageAnchors.set(file, new Set(Array.from(html.matchAll(/\bid=["']([^"']+)["']/g), match => match[1])));
  }
  return pageAnchors.get(file);
}
for (const file of pages) {
  const html = await readFile(file, 'utf8');
  for (const match of html.matchAll(/(?:href|src)=["']([^"']+)["']/g)) {
    const raw = match[1].replaceAll('&amp;', '&');
    if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(raw)) continue;
    const pathname = decodeURIComponent(raw.split(/[?#]/, 1)[0]);
    const fragment = raw.includes('#') ? decodeURIComponent(raw.slice(raw.indexOf('#') + 1)) : '';
    if (!pathname && !fragment) continue;
    let target = !pathname ? file : pathname.startsWith('/') ? resolve(output, '.' + pathname) : resolve(dirname(file), pathname);
    try {
      if ((await stat(target)).isDirectory()) target = resolve(target, 'index.html');
      await stat(target);
      if (fragment && extname(target) === '.html' && !(await anchorsFor(target)).has(fragment)) {
        errors.push(`${file.slice(output.length + 1)}: missing anchor ${raw}`);
      }
    } catch { errors.push(`${file.slice(output.length + 1)}: missing ${raw}`); }
  }
}
const search = JSON.parse(await readFile(resolve(output, 'search_plus_index.json'), 'utf8'));
for (const project of ['codex', 'opencode', 'dsh']) {
  const count = Object.keys(search).filter(path => path.startsWith(project + '/')).length;
  if (count !== 9) errors.push(`Expected 9 indexed ${project} chapters (architecture + 8 topics), found ${count}`);
  if (!search[`${project}/00-architecture.html`]) errors.push(`Missing ${project} architecture in search index`);
}
if (!Object.values(search).some(page => page.body.includes('顺序提交'))) errors.push('Chinese search corpus missing');
if (all.some(file => file.includes('/research/decisions/'))) errors.push('Authoring drafts were copied into the book');
if (errors.length) { console.error(errors.join('\n')); process.exitCode = 1; }
else console.log(`PASS: ${pages.length} HTML pages, ${Object.keys(search).length} indexed pages, all local page assets and links exist.`);
