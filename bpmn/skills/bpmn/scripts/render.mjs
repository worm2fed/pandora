#!/usr/bin/env node
/**
 * render.mjs — render .bpmn file(s) to a self-contained HTML preview.
 *
 * Usage:
 *   node render.mjs <file.bpmn> [-o <out.html>]              single diagram
 *   node render.mjs <a.bpmn> <b.bpmn> ... [-o <suite.html>]  tabbed suite
 *
 * The HTML inlines the bpmn-js navigated viewer (no CDN, no network): pan/zoom,
 * fit button, and download buttons for the SVG export and the .bpmn source.
 * With multiple inputs a tab bar switches between diagrams (tab title = the
 * bpmn:process name, falling back to the filename); download buttons act on
 * the active tab. Re-rendering to the same path after editing updates the
 * preview. Default output: <first-input>.html, or <dir>/suite.html for suites.
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { basename, dirname, join } from 'node:path';

const require = createRequire(import.meta.url);

const args = process.argv.slice(2);
const outFlag = args.indexOf('-o');
const outFile = outFlag !== -1 ? args[outFlag + 1] : null;
const inFiles = args.filter((a, i) => outFlag === -1 || (i !== outFlag && i !== outFlag + 1));

if (!inFiles.length) {
  console.error('usage: node render.mjs <file.bpmn> [<more.bpmn> ...] [-o <out.html>]');
  process.exit(2);
}

const diagrams = inFiles.map((file) => {
  const xml = readFileSync(file, 'utf8');
  const nameMatch = xml.match(/<bpmn\w*:process[^>]*\sname="([^"]+)"/);
  return {
    file: basename(file),
    title: decodeEntities(nameMatch?.[1] ?? basename(file).replace(/\.bpmn$/, '')),
    xml,
  };
});

const viewerJs = readFileSync(
  require.resolve('bpmn-js/dist/bpmn-navigated-viewer.production.min.js'),
  'utf8',
);
const bpmnCss = readFileSync(require.resolve('bpmn-js/dist/assets/bpmn-js.css'), 'utf8');
const diagramCss = readFileSync(
  require.resolve('bpmn-js/dist/assets/diagram-js.css'),
  'utf8',
);

const suite = diagrams.length > 1;
const pageTitle = suite
  ? basename(inFiles[0]).replace(/\.bpmn$/, '').replace(/-[a-z]+$/, '') + ' suite'
  : diagrams[0].title;
const target =
  outFile ??
  (suite
    ? join(dirname(inFiles[0]), 'suite.html')
    : inFiles[0].replace(/\.bpmn$/, '') + '.html');

const html = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(pageTitle)} — BPMN</title>
<style>
${diagramCss}
${bpmnCss}
html, body { margin: 0; height: 100%; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
body { display: flex; flex-direction: column; background: #f4f4f4; }
header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #fff; border-bottom: 1px solid #ddd; flex: none; flex-wrap: wrap; }
header h1 { font-size: 14px; font-weight: 600; margin: 0 auto 0 0; color: #333; }
header button { font: inherit; font-size: 12px; padding: 4px 10px; border: 1px solid #ccc; border-radius: 4px; background: #fafafa; cursor: pointer; color: #333; }
header button:hover { background: #eee; }
nav { display: flex; gap: 4px; padding: 6px 12px 0; background: #fff; flex: none; ${suite ? '' : 'display: none;'} }
nav button { font: inherit; font-size: 13px; padding: 6px 14px; border: 1px solid #ddd; border-bottom: none; border-radius: 6px 6px 0 0; background: #f1f1f1; cursor: pointer; color: #555; }
nav button.active { background: #fff; color: #111; font-weight: 600; border-color: #ccc; position: relative; top: 1px; }
main { flex: 1; position: relative; background: #fff; border-top: 1px solid #ddd; }
main .canvas { position: absolute; inset: 0; visibility: hidden; }
main .canvas.active { visibility: visible; }
#warnings { flex: none; max-height: 120px; overflow: auto; font-size: 11px; font-family: ui-monospace, monospace; color: #92400e; background: #fffbeb; border-top: 1px solid #fde68a; padding: 4px 12px; white-space: pre-wrap; display: none; }
</style>
</head>
<body>
<header>
  <h1>${escapeHtml(pageTitle)}</h1>
  <button id="fit">Fit</button>
  <button id="zoom-in">+</button>
  <button id="zoom-out">−</button>
  <button id="dl-svg">Download SVG</button>
  <button id="dl-bpmn">Download .bpmn</button>
</header>
<nav id="tabs"></nav>
<main id="main"></main>
<div id="warnings"></div>
<script>${viewerJs}</script>
<script>
  var DIAGRAMS = ${JSON.stringify(diagrams)};
  var main = document.getElementById('main');
  var tabs = document.getElementById('tabs');
  var warningsBox = document.getElementById('warnings');
  var active = 0;
  var entries = DIAGRAMS.map(function (d, i) {
    var el = document.createElement('div');
    el.className = 'canvas';
    main.appendChild(el);
    var btn = document.createElement('button');
    btn.textContent = d.title;
    btn.onclick = function () { activate(i); };
    tabs.appendChild(btn);
    var viewer = new BpmnJS({ container: el });
    var entry = { d: d, el: el, btn: btn, viewer: viewer, fitted: false, warnings: [] };
    viewer.importXML(d.xml).then(function (result) {
      entry.warnings = (result.warnings || []).map(function (w) { return d.file + ': ' + w.message; });
      if (i === active) activate(i);
    }).catch(function (err) {
      el.innerHTML = '<pre style="color:#b91c1c;padding:16px;white-space:pre-wrap;">' + d.file + ' import failed: ' + err.message + '</pre>';
    });
    return entry;
  });

  function activate(i) {
    active = i;
    entries.forEach(function (e, j) {
      e.el.classList.toggle('active', j === i);
      e.btn.classList.toggle('active', j === i);
    });
    var e = entries[i];
    if (!e.fitted) {
      e.viewer.get('canvas').zoom('fit-viewport');
      e.fitted = true;
    }
    warningsBox.style.display = e.warnings.length ? 'block' : 'none';
    warningsBox.textContent = e.warnings.map(function (w) { return 'import warning: ' + w; }).join('\\n');
  }
  activate(0);

  document.getElementById('fit').onclick = function () { entries[active].viewer.get('canvas').zoom('fit-viewport'); };
  document.getElementById('zoom-in').onclick = function () { entries[active].viewer.get('zoomScroll').stepZoom(1); };
  document.getElementById('zoom-out').onclick = function () { entries[active].viewer.get('zoomScroll').stepZoom(-1); };

  function download(name, type, content) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([content], { type: type }));
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  }
  document.getElementById('dl-bpmn').onclick = function () {
    download(entries[active].d.file, 'application/xml', entries[active].d.xml);
  };
  document.getElementById('dl-svg').onclick = function () {
    entries[active].viewer.saveSVG().then(function (r) {
      download(entries[active].d.file.replace(/\\.bpmn$/, '') + '.svg', 'image/svg+xml', r.svg);
    });
  };
</script>
</body>
</html>
`;

writeFileSync(target, html);
console.log(`preview written: ${target}`);

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function decodeEntities(s) {
  return s
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"');
}
