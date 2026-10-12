/* Everything is served locally; no CDN is required for diagrams. */
require(['gitbook', 'jquery'], function (gitbook, $) {
  // The search plugin listens for keyup; also support paste and mobile input.
  $(document).on('input', '#book-search-input input', function () {
    $(this).trigger('keyup');
  });
  async function renderDiagrams() {
    if (!window.mermaid) return;
    const nodes = Array.from(document.querySelectorAll('.mermaid:not([data-processed])'));
    document.querySelectorAll('pre > code.lang-mermaid, pre > code.language-mermaid').forEach(function (code) {
      const diagram = document.createElement('div');
      diagram.className = 'mermaid';
      diagram.setAttribute('aria-label', '任务执行流程图');
      diagram.textContent = code.textContent;
      code.parentElement.replaceWith(diagram);
      nodes.push(diagram);
    });
    if (!nodes.length) return;
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral', fontFamily: 'system-ui, sans-serif' });
    try {
      await mermaid.run({ nodes: nodes });
      nodes.forEach(function (diagram) {
        const svg = diagram.querySelector('svg');
        if (!svg || svg.viewBox.baseVal.width < 640) return;
        // Offer an overview and a full-size reading mode for wide diagrams.
        diagram.classList.add('diagram-wide', 'diagram-fit');
        diagram.tabIndex = 0;
        svg.style.width = Math.ceil(svg.viewBox.baseVal.width) + 'px';
        const controls = document.createElement('div');
        controls.className = 'diagram-controls';
        const hint = document.createElement('span');
        hint.textContent = '全图预览';
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.textContent = '放大阅读';
        toggle.setAttribute('aria-pressed', 'true');
        toggle.addEventListener('click', function () {
          const fit = diagram.classList.toggle('diagram-fit');
          toggle.textContent = fit ? '放大阅读' : '适应页面宽度';
          toggle.setAttribute('aria-pressed', String(fit));
          hint.textContent = fit ? '全图预览' : '可左右滚动查看完整图';
        });
        controls.append(hint, toggle);
        diagram.before(controls);
      });
    } catch (error) {
      console.error('Unable to render a Mermaid diagram', error);
    }
  }
  gitbook.events.bind('page.change', renderDiagrams);
  renderDiagrams();
});
