"""Self-contained HTML flame graph ("burn map", doc §3.2/§7.7): the
shareable, screenshot-worthy report. Everything — CSS, JS, data — is inlined
into one file; no CDN, no external font, no network call of any kind (doc
§7.7 requires this and §3.6 verifies it by scanning the output).

Sizing and category semantics are documented in tree.py; this module owns
the page shell, the flame-graph rendering/interaction JS, and the findings
sidebar.
"""

from __future__ import annotations

import json
from xml.sax.saxutils import escape

from wattage.models import Report, Trace
from wattage.render.html.tree import build_tree

_SEVERITY_STATUS = {
    "info": "warning",
    "low": "warning",
    "medium": "serious",
    "high": "critical",
    "critical": "critical",
}

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>__TITLE__</title>
<style>
  :root {
    --surface-1: #fcfcfb; --page: #f9f9f7; --ink-1: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
    --grid: #e1e0d9; --baseline: #c3c2b7; --border: rgba(11,11,11,0.10);
    --cat-input: #2a78d6; --cat-cache-read: #1baf7a; --cat-cache-creation: #4a3aa7;
    --cat-reasoning: #eda100; --cat-output: #008300; --cat-tool-io: #eb6834;
    --status-good: #0ca30c; --status-warning: #fab219; --status-serious: #ec835a; --status-critical: #d03b3b;
    --neutral-frame: #efeee9; --neutral-frame-2: #e4e3dc; --neutral-frame-ink: #3a3936;
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      --surface-1: #1a1a19; --page: #0d0d0d; --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
      --grid: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
      --cat-input: #3987e5; --cat-cache-read: #199e70; --cat-cache-creation: #9085e9;
      --cat-reasoning: #c98500; --cat-output: #008300; --cat-tool-io: #d95926;
      --neutral-frame: #26251f; --neutral-frame-2: #302f27; --neutral-frame-ink: #d8d6cd;
      color-scheme: dark;
    }
  }
  :root[data-theme="dark"] {
    --surface-1: #1a1a19; --page: #0d0d0d; --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
    --grid: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
    --cat-input: #3987e5; --cat-cache-read: #199e70; --cat-cache-creation: #9085e9;
    --cat-reasoning: #c98500; --cat-output: #008300; --cat-tool-io: #d95926;
    --neutral-frame: #26251f; --neutral-frame-2: #302f27; --neutral-frame-ink: #d8d6cd;
    color-scheme: dark;
  }
  :root[data-theme="light"] {
    --surface-1: #fcfcfb; --page: #f9f9f7; --ink-1: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
    --grid: #e1e0d9; --baseline: #c3c2b7; --border: rgba(11,11,11,0.10);
    --cat-input: #2a78d6; --cat-cache-read: #1baf7a; --cat-cache-creation: #4a3aa7;
    --cat-reasoning: #eda100; --cat-output: #008300; --cat-tool-io: #eb6834;
    --neutral-frame: #efeee9; --neutral-frame-2: #e4e3dc; --neutral-frame-ink: #3a3936;
    color-scheme: light;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--page); color: var(--ink-1);
    font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  .num { font-variant-numeric: tabular-nums; font-family: ui-monospace, "SF Mono", Consolas, monospace; }
  header {
    display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
    padding: 20px 24px; border-bottom: 1px solid var(--border);
  }
  header h1 { font-size: 18px; margin: 0; }
  header .source { color: var(--ink-muted); font-size: 13px; }
  header .spacer { flex: 1; }
  .score-chip {
    display: inline-flex; align-items: baseline; gap: 6px; padding: 4px 12px;
    border-radius: 999px; background: var(--neutral-frame); font-size: 13px;
  }
  .score-chip b { font-size: 15px; }
  button.theme-toggle {
    border: 1px solid var(--border); background: var(--surface-1); color: var(--ink-1);
    border-radius: 6px; padding: 5px 10px; font-size: 12px; cursor: pointer;
  }
  main { display: flex; gap: 0; align-items: flex-start; }
  .graph-panel { flex: 1; min-width: 0; padding: 20px 24px; }
  .graph-scroll { overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-1); }
  svg#flamegraph { display: block; width: 100%; }
  .frame { stroke: var(--page); stroke-width: 1; cursor: pointer; }
  .frame:hover { stroke: var(--ink-1); stroke-width: 1.5; }
  .frame-label {
    font-size: 11px; fill: var(--neutral-frame-ink); pointer-events: none;
    font-family: ui-monospace, "SF Mono", Consolas, monospace;
  }
  .frame-label.on-color { fill: #ffffff; }
  .breadcrumb { padding: 8px 2px 12px; font-size: 12px; color: var(--ink-2); }
  .breadcrumb span { cursor: pointer; text-decoration: underline; text-decoration-style: dotted; }
  .breadcrumb .sep { margin: 0 4px; color: var(--ink-muted); }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; padding: 10px 2px 0; font-size: 12px; color: var(--ink-2); }
  .legend .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: middle; }
  #tooltip {
    position: fixed; pointer-events: none; z-index: 10; display: none;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 10px; font-size: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.18); max-width: 320px;
  }
  #tooltip .t-name { font-weight: 600; margin-bottom: 3px; word-break: break-word; }
  #tooltip .t-row { color: var(--ink-2); }
  aside {
    width: 340px; flex-shrink: 0; border-left: 1px solid var(--border);
    padding: 20px 20px; max-height: calc(100vh - 61px); overflow-y: auto;
  }
  aside h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: var(--ink-muted); margin: 0 0 12px; }
  .finding { border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 10px; }
  .finding-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .sev-chip {
    font-size: 10px; text-transform: uppercase; letter-spacing: .03em; font-weight: 700;
    padding: 2px 7px; border-radius: 999px; color: #fff;
  }
  .sev-warning { background: var(--status-warning); color: #3a2a00; }
  .sev-serious { background: var(--status-serious); }
  .sev-critical { background: var(--status-critical); }
  .finding-id { font-weight: 600; font-size: 13px; }
  .finding .dollars { margin-left: auto; font-size: 13px; }
  .finding .evidence { color: var(--ink-2); font-size: 12.5px; margin-bottom: 6px; }
  .finding .fix { font-size: 12.5px; }
  .finding .fix::before { content: "Fix: "; font-weight: 600; }
  .no-findings { color: var(--ink-muted); font-size: 13px; }
  footer { padding: 14px 24px; color: var(--ink-muted); font-size: 11.5px; border-top: 1px solid var(--border); }
</style>
</head>
<body>
<header>
  <h1>&#9889; wattage &mdash; burn map</h1>
  <span class="source">__SOURCE__</span>
  <div class="spacer"></div>
  <div class="score-chip"><b>__GRADE__ (__EFFICIENCY__)</b> &middot; $__RECOVERABLE__ recoverable</div>
  <button class="theme-toggle" onclick="toggleTheme()">&#9788;/&#9789; theme</button>
</header>
<main>
  <div class="graph-panel">
    <div class="breadcrumb" id="breadcrumb"></div>
    <div class="graph-scroll">
      <svg id="flamegraph" xmlns="http://www.w3.org/2000/svg"></svg>
    </div>
    <div class="legend" id="legend"></div>
  </div>
  <aside>
    <h2>Findings (__FINDING_COUNT__)</h2>
    __FINDINGS_HTML__
  </aside>
</main>
<footer>pricing: __PRICING_VERSION__ &middot; generated __GENERATED_AT__</footer>
<div id="tooltip"></div>
<script>
const DATA = __TREE_JSON__;
const CATEGORY_COLORS = {
  input: 'var(--cat-input)', cache_read: 'var(--cat-cache-read)', cache_creation: 'var(--cat-cache-creation)',
  reasoning: 'var(--cat-reasoning)', output: 'var(--cat-output)', tool_io: 'var(--cat-tool-io)'
};
const CATEGORY_LABELS = {
  input: 'Input', cache_read: 'Cache read', cache_creation: 'Cache write',
  reasoning: 'Reasoning', output: 'Output', tool_io: 'Tool / retrieval I/O'
};
const BAND_HEIGHT = 26;
const VIRTUAL_WIDTH = 1000;
const svgNS = 'http://www.w3.org/2000/svg';
const svg = document.getElementById('flamegraph');
const tooltip = document.getElementById('tooltip');

let zoomStack = [DATA];

function colorFor(node) {
  if (node.kind === 'segment') return CATEGORY_COLORS[node.category] || 'var(--neutral-frame)';
  return null; // structural frame; painted a depth-based neutral shade
}

function layout(node, x, width, depth, out) {
  out.push({ node: node, x: x, width: width, depth: depth });
  if (!node.children || node.children.length === 0 || width < 0.5) return;
  const total = node.value || 1;
  let childX = x;
  for (const child of node.children) {
    const childWidth = (child.value / total) * width;
    if (childWidth > 0.15) layout(child, childX, childWidth, depth + 1, out);
    childX += childWidth;
  }
}

function fmtTokens(n) {
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n);
}
function fmtDollars(n) {
  if (n === null || n === undefined) return null;
  return '$' + n.toFixed(n < 1 ? 4 : 2);
}

function render() {
  const root = zoomStack[zoomStack.length - 1];
  const rects = [];
  layout(root, 0, VIRTUAL_WIDTH, 0, rects);
  const maxDepth = rects.reduce((m, r) => Math.max(m, r.depth), 0);
  const height = (maxDepth + 1) * BAND_HEIGHT;
  svg.setAttribute('viewBox', '0 0 ' + VIRTUAL_WIDTH + ' ' + height);
  svg.setAttribute('height', height);
  svg.innerHTML = '';

  for (const r of rects) {
    const isSegment = r.node.kind === 'segment';
    const fill = isSegment ? colorFor(r.node) : (r.depth % 2 === 0 ? 'var(--neutral-frame)' : 'var(--neutral-frame-2)');
    const rect = document.createElementNS(svgNS, 'rect');
    rect.setAttribute('x', r.x.toFixed(2));
    rect.setAttribute('y', r.depth * BAND_HEIGHT);
    rect.setAttribute('width', Math.max(r.width - 0.6, 0).toFixed(2));
    rect.setAttribute('height', BAND_HEIGHT - 2);
    rect.setAttribute('fill', fill);
    rect.setAttribute('class', 'frame');
    rect.addEventListener('click', () => { zoomStack.push(r.node); render(); });
    rect.addEventListener('mousemove', (e) => showTooltip(e, r.node));
    rect.addEventListener('mouseleave', hideTooltip);
    svg.appendChild(rect);

    if (r.width > 16) {
      const text = document.createElementNS(svgNS, 'text');
      text.setAttribute('x', (r.x + 4).toFixed(2));
      text.setAttribute('y', r.depth * BAND_HEIGHT + BAND_HEIGHT / 2 + 4);
      text.setAttribute('class', 'frame-label' + (isSegment ? ' on-color' : ''));
      text.style.pointerEvents = 'none';
      text.textContent = r.node.name;
      svg.appendChild(text);
      // Truncate against the box's *actual* rendered text width (not a
      // fixed char-width guess) so long labels never overflow into
      // neighboring frames or past the container's right edge.
      const available = r.width - 8;
      let label = r.node.name;
      while (label.length > 1 && text.getComputedTextLength() > available) {
        label = label.slice(0, -1);
        text.textContent = label + '…';
      }
      if (text.getComputedTextLength() > available) svg.removeChild(text);
    }
  }
  renderBreadcrumb();
}

function renderBreadcrumb() {
  const el = document.getElementById('breadcrumb');
  el.innerHTML = '';
  zoomStack.forEach((node, i) => {
    if (i > 0) {
      const sep = document.createElement('span');
      sep.className = 'sep'; sep.textContent = '/';
      el.appendChild(sep);
    }
    const span = document.createElement('span');
    span.textContent = node.name;
    span.addEventListener('click', () => { zoomStack = zoomStack.slice(0, i + 1); render(); });
    el.appendChild(span);
  });
}

function showTooltip(evt, node) {
  const dollars = fmtDollars(node.dollars);
  let html = '<div class="t-name">' + escapeHtml(node.name) + '</div>';
  html += '<div class="t-row">' + node.kind + ' &middot; ' + fmtTokens(node.tokens) + ' tokens';
  if (dollars !== null) html += ' &middot; ' + dollars;
  html += '</div>';
  if (node.model) html += '<div class="t-row">model: ' + escapeHtml(node.model) + '</div>';
  tooltip.innerHTML = html;
  tooltip.style.display = 'block';
  const x = evt.clientX + 14, y = evt.clientY + 14;
  tooltip.style.left = x + 'px';
  tooltip.style.top = y + 'px';
}
function hideTooltip() { tooltip.style.display = 'none'; }
function escapeHtml(s) {
  const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
}

function renderLegend() {
  const el = document.getElementById('legend');
  el.innerHTML = '';
  for (const key of Object.keys(CATEGORY_LABELS)) {
    const item = document.createElement('span');
    const swatch = document.createElement('span');
    swatch.className = 'swatch';
    swatch.style.background = CATEGORY_COLORS[key];
    item.appendChild(swatch);
    item.appendChild(document.createTextNode(CATEGORY_LABELS[key]));
    el.appendChild(item);
  }
}

function toggleTheme() {
  const root = document.documentElement;
  const current = root.getAttribute('data-theme');
  root.setAttribute('data-theme', current === 'dark' ? 'light' : 'dark');
}

render();
renderLegend();
</script>
</body>
</html>
"""


def render_html(trace: Trace, report: Report) -> str:
    tree = build_tree(trace)
    findings_html = _render_findings(report)

    html = _TEMPLATE
    html = html.replace("__TITLE__", escape(f"wattage burn map — {report.trace_source}"))
    html = html.replace("__SOURCE__", escape(report.trace_source))
    html = html.replace("__GRADE__", escape(report.score.grade))
    html = html.replace("__EFFICIENCY__", str(report.score.efficiency))
    html = html.replace("__RECOVERABLE__", f"{report.score.recoverable_dollars:.2f}")
    html = html.replace("__FINDING_COUNT__", str(len(report.findings)))
    html = html.replace("__FINDINGS_HTML__", findings_html)
    html = html.replace("__PRICING_VERSION__", escape(report.pricing_version))
    html = html.replace("__GENERATED_AT__", escape(report.generated_at))
    html = html.replace("__TREE_JSON__", json.dumps(tree))
    return html


def _render_findings(report: Report) -> str:
    if not report.findings:
        return '<p class="no-findings">No findings — this trace looks efficient.</p>'

    parts = []
    for finding in report.findings:
        status = _SEVERITY_STATUS.get(finding.severity.value, "warning")
        parts.append(
            '<div class="finding">'
            '<div class="finding-head">'
            f'<span class="sev-chip sev-{status}">{escape(finding.severity.value)}</span>'
            f'<span class="finding-id">{escape(finding.id)}</span>'
            f'<span class="dollars num">${finding.wasted_dollars:.4f}</span>'
            "</div>"
            f'<div class="evidence">{escape(finding.evidence)}</div>'
            f'<div class="fix">{escape(finding.fix)}</div>'
            "</div>"
        )
    return "\n".join(parts)
