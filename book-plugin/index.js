function escapeHtml(value) {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}
module.exports = {
  website: {
    assets: './assets',
    js: ['mermaid.min.js', 'notes.js'],
    css: ['notes.css']
  },
  hooks: {
    'page:before': function (page) {
      page.content = page.content.replace(/^```mermaid\r?\n([\s\S]*?)^```[ \t]*$/gm, function (_, source) {
        return '<div class="mermaid" aria-label="任务执行流程图">\n' + escapeHtml(source.trim()) + '\n</div>\n';
      });
      return page;
    }
  }
};
