"""Interactive knowledge graph visualizer for dregs."""
from __future__ import annotations

import json
import http.server
import threading
import webbrowser
from typing import Optional

from dregs.store import DregsStore


def _build_graph_data(store: DregsStore, graph_uri: Optional[str] = None) -> dict:
    """Extract nodes and edges from the store, then compute analytics."""
    prefixes = store.get_prefixes()

    def shorten(uri: str) -> str:
        for prefix, ns in prefixes.items():
            if uri.startswith(ns):
                return f"{prefix}:{uri[len(ns):]}"
        if "#" in uri:
            return uri.split("#")[-1]
        return uri.split("/")[-1]

    # Get all entity-to-entity relationships (object properties), data graphs only
    sparql = """
    SELECT ?s ?p ?o ?stype ?otype
    WHERE {
        ?s ?p ?o .
        FILTER(isIRI(?s) && isIRI(?o))
        FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
        FILTER(!STRSTARTS(STR(?p), "http://www.w3.org/2002/07/owl#"))
        FILTER(!STRSTARTS(STR(?p), "http://www.w3.org/ns/shacl#"))
        FILTER(!STRSTARTS(STR(?p), "http://www.w3.org/2000/01/rdf-schema#"))
        FILTER(!STRSTARTS(STR(?p), "http://www.w3.org/1999/02/22-rdf-syntax-ns#"))
        FILTER(!STRSTARTS(STR(?p), "http://www.w3.org/2004/02/skos/"))
        FILTER(!STRSTARTS(STR(?s), "http://www.w3.org/"))
        FILTER(!STRSTARTS(STR(?o), "http://www.w3.org/"))
        FILTER(!STRSTARTS(STR(?p), "http://www.w3.org/ns/prov#"))
        ?s a ?stype . FILTER(!STRSTARTS(STR(?stype), "http://www.w3.org/"))
        ?o a ?otype . FILTER(!STRSTARTS(STR(?otype), "http://www.w3.org/"))
    }
    """
    from dregs.sparql import execute_sparql
    result = execute_sparql(store, sparql, graph_uri=graph_uri, format="json")

    nodes_map = {}  # uri -> node data
    edges = []

    # Get labels/names
    label_sparql = """
    SELECT ?s ?label ?name
    WHERE {
        { ?s <http://www.w3.org/2000/01/rdf-schema#label> ?label }
        UNION
        { ?s ?nameProp ?name . FILTER(CONTAINS(STR(?nameProp), "name")) }
    }
    """
    label_result = execute_sparql(store, label_sparql, graph_uri=graph_uri, format="json")
    labels = {}
    for row in label_result.bindings:
        s = row.get("s", "")
        label = row.get("label", "") or row.get("name", "")
        if s and label:
            labels[s] = label

    for row in result.bindings:
        s = row.get("s", "")
        p = row.get("p", "")
        o = row.get("o", "")
        stype = row.get("stype", "")
        otype = row.get("otype", "")

        if not s or not o:
            continue
        if "wasDerivedFrom" in p:
            continue

        s_short = shorten(s) if ":" not in s or s.startswith("http") else s
        o_short = shorten(o) if ":" not in o or o.startswith("http") else o
        s_type_short = shorten(stype) if stype else ""
        o_type_short = shorten(otype) if otype else ""

        if s_short not in nodes_map:
            label = labels.get(s, s_short.split(":")[-1] if ":" in s_short else s_short)
            nodes_map[s_short] = {
                "id": s_short, "label": label, "type": s_type_short,
                "color": "#b2bec3", "edges": 0, "size": 4,
            }
        if o_short not in nodes_map:
            label = labels.get(o, o_short.split(":")[-1] if ":" in o_short else o_short)
            nodes_map[o_short] = {
                "id": o_short, "label": label, "type": o_type_short,
                "color": "#b2bec3", "edges": 0, "size": 4,
            }

        p_short = shorten(p) if ":" not in p or p.startswith("http") else p
        nodes_map[s_short]["edges"] += 1
        nodes_map[o_short]["edges"] += 1

        edges.append({
            "source": s_short, "target": o_short,
            "label": p_short.split(":")[-1] if ":" in p_short else p_short,
        })

    nodes = list(nodes_map.values())

    # Compute analytics (community detection, centrality, gaps)
    from dregs.analytics import compute_analytics
    analytics = compute_analytics(nodes, edges)

    # After analytics, node colors come from community
    # Keep type info but use community color as primary
    for n in nodes:
        n["color"] = n.get("communityColor", n["color"])

    return {
        "nodes": nodes,
        "edges": edges,
        "analytics": analytics,
    }


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>dregs — knowledge graph</title>
<style>
:root {
    --bg: #0a0a0f;
    --panel-bg: rgba(15, 15, 25, 0.92);
    --border: rgba(255,255,255,0.08);
    --text: #c8d6e5;
    --text-bright: #f5f6fa;
    --text-dim: #636e72;
    --accent: #4ecdc4;
    --pin-color: #0089e0;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; overflow: hidden; }
#canvas { width: 100vw; height: 100vh; display: block; }
svg { width: 100%; height: 100%; }

/* Left controls */
#controls {
    position: fixed; top: 16px; left: 16px; z-index: 10;
    display: flex; flex-direction: column; gap: 8px; max-width: 260px;
}
.panel {
    background: var(--panel-bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 12px 16px; backdrop-filter: blur(12px);
}
.panel h1 { font-size: 14px; font-weight: 600; color: var(--text-bright); letter-spacing: 0.5px; }
.panel .subtitle { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
.panel h2 { font-size: 11px; font-weight: 600; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.8px; margin: 8px 0 4px; }

/* Search */
#search {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px; padding: 8px 12px; color: #dfe6e9; font-size: 13px;
    width: 100%; outline: none;
}
#search:focus { border-color: rgba(78, 205, 196, 0.5); }
#search::placeholder { color: var(--text-dim); }

/* Legend / community list */
.legend { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; max-height: 180px; overflow-y: auto; }
.legend-item {
    display: flex; align-items: center; gap: 6px; font-size: 11px; color: #b2bec3;
    cursor: pointer; padding: 3px 6px; border-radius: 4px; transition: background 0.15s;
}
.legend-item:hover { background: rgba(255,255,255,0.06); }
.legend-item.dimmed { opacity: 0.3; }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.legend-meta { font-size: 10px; color: var(--text-dim); margin-left: auto; }

/* Buttons */
.btn-row { display: flex; gap: 4px; margin-top: 6px; flex-wrap: wrap; }
.btn {
    background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
    border-radius: 4px; padding: 4px 8px; color: #b2bec3; font-size: 11px;
    cursor: pointer; transition: all 0.15s;
}
.btn:hover { background: rgba(255,255,255,0.1); }
.btn.active { background: rgba(78,205,196,0.2); border-color: rgba(78,205,196,0.4); color: var(--accent); }

/* Right analytics panel */
#analytics {
    position: fixed; top: 16px; right: 16px; z-index: 10; width: 280px;
    background: var(--panel-bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px 16px; backdrop-filter: blur(12px);
    max-height: calc(100vh - 32px); overflow-y: auto; display: none;
}
#analytics.visible { display: block; }
#analytics h2 { font-size: 11px; font-weight: 600; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.8px; margin: 10px 0 4px; }
#analytics h2:first-child { margin-top: 0; }
.metric-row { display: flex; justify-content: space-between; font-size: 12px; padding: 2px 0; }
.metric-label { color: var(--text-dim); }
.metric-value { color: var(--text-bright); font-variant-numeric: tabular-nums; }
.bias-badge {
    display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px;
    border-radius: 4px; margin-top: 4px;
}
.bias-Dispersed { background: rgba(255,107,107,0.2); color: #ff6b6b; }
.bias-Diversified { background: rgba(78,205,196,0.2); color: #4ecdc4; }
.bias-Focused { background: rgba(255,234,167,0.2); color: #ffeaa7; }
.bias-Biased { background: rgba(162,155,254,0.2); color: #a29bfe; }
.influential-item {
    display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 3px 0;
    color: var(--text); cursor: pointer;
}
.influential-item:hover { color: var(--text-bright); }
.influential-bc { font-size: 10px; color: var(--text-dim); margin-left: auto; }
.gap-item {
    font-size: 12px; color: var(--text); padding: 4px 0;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}
.gap-question { color: var(--accent); font-style: italic; font-size: 11px; }
.gap-meta { font-size: 10px; color: var(--text-dim); }

/* Info panel (bottom-left on click) */
#info {
    position: fixed; bottom: 16px; left: 16px; z-index: 10;
    background: var(--panel-bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 12px 16px; backdrop-filter: blur(12px);
    max-width: 360px; display: none;
}
#info h3 { font-size: 13px; color: var(--text-bright); margin-bottom: 4px; }
#info .type-badge { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 3px; margin-bottom: 6px; }
#info .connections { font-size: 11px; color: var(--text-dim); }
#info .conn-item { color: #b2bec3; padding: 1px 0; }
.node-stats { font-size: 11px; color: var(--text-dim); margin-bottom: 4px; }

/* Stats bar */
#stats {
    position: fixed; bottom: 16px; right: 16px; z-index: 10; font-size: 11px;
    color: var(--text-dim); background: rgba(15,15,25,0.8); border-radius: 6px; padding: 6px 10px;
}

/* Tooltip */
.node-tooltip {
    position: fixed; background: rgba(15,15,25,0.95); border: 1px solid rgba(255,255,255,0.15);
    border-radius: 6px; padding: 6px 10px; font-size: 12px; color: var(--text-bright);
    pointer-events: none; z-index: 100; display: none; white-space: nowrap;
}
.tooltip-bc { font-size: 10px; color: var(--text-dim); }

/* Edge labels */
.edge-label { font-size: 9px; fill: var(--text-dim); pointer-events: none; }

/* Gap dashes */
.gap-line { stroke-dasharray: 6 4; opacity: 0.3; }

/* Scrollbar */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
</style>
</head>
<body>
<div id="canvas"></div>

<div id="controls">
    <div class="panel">
        <h1>dregs</h1>
        <div class="subtitle" id="graph-info">knowledge graph</div>
    </div>
    <div class="panel">
        <input type="text" id="search" placeholder="Search nodes… ( / )" autocomplete="off">
        <h2>Topics</h2>
        <div class="legend" id="legend"></div>
        <div class="btn-row">
            <button class="btn active" data-action="toggle-analytics" title="Analytics panel">◈ Analytics</button>
            <button class="btn" data-action="toggle-edges" title="Edge labels">↔ Edges</button>
            <button class="btn" data-action="toggle-gaps" title="Gap lines">⚡ Gaps</button>
            <button class="btn" data-action="cycle-sizing" title="Node sizing">● Size: BC</button>
        </div>
    </div>
</div>

<div id="analytics"></div>
<div id="info"></div>
<div id="stats"></div>
<div class="node-tooltip" id="tooltip"></div>

<script>
// ── DATA ──
const DATA = __GRAPH_DATA__;
const nodes = DATA.nodes;
const edges = DATA.edges;
const analytics = DATA.analytics || {};
const communities = analytics.communities || [];

// ── SETUP ──
const container = document.getElementById('canvas');
const W = window.innerWidth, H = window.innerHeight;
const ns = 'http://www.w3.org/2000/svg';
const svg = document.createElementNS(ns, 'svg');
svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
container.appendChild(svg);

const defs = document.createElementNS(ns, 'defs');
svg.appendChild(defs);
const marker = document.createElementNS(ns, 'marker');
marker.setAttribute('id', 'arrow');
marker.setAttribute('viewBox', '0 -5 10 10');
marker.setAttribute('refX', 20); marker.setAttribute('refY', 0);
marker.setAttribute('markerWidth', 6); marker.setAttribute('markerHeight', 6);
marker.setAttribute('orient', 'auto');
const arrowPath = document.createElementNS(ns, 'path');
arrowPath.setAttribute('d', 'M0,-4L10,0L0,4');
arrowPath.setAttribute('fill', 'rgba(255,255,255,0.15)');
marker.appendChild(arrowPath);
defs.appendChild(marker);

const edgeGroup = document.createElementNS(ns, 'g');
const gapLineGroup = document.createElementNS(ns, 'g');
gapLineGroup.style.display = 'none';
const edgeLabelGroup = document.createElementNS(ns, 'g');
edgeLabelGroup.style.display = 'none';
const nodeGroup = document.createElementNS(ns, 'g');
const labelGroup = document.createElementNS(ns, 'g');
svg.appendChild(edgeGroup);
svg.appendChild(gapLineGroup);
svg.appendChild(edgeLabelGroup);
svg.appendChild(nodeGroup);
svg.appendChild(labelGroup);

// ── NODE INDEX ──
const nodeIndex = {};
nodes.forEach(n => nodeIndex[n.id] = n);

// ── ADJACENCY ──
const adjacency = {};
nodes.forEach(n => adjacency[n.id] = new Set());
edges.forEach(e => {
    if (adjacency[e.source] && adjacency[e.target]) {
        adjacency[e.source].add(e.target);
        adjacency[e.target].add(e.source);
    }
});

// ── INIT POSITIONS (community-clustered) ──
const communityCount = communities.length || 1;
nodes.forEach((n, i) => {
    const cid = n.community || 0;
    const cAngle = (cid / communityCount) * Math.PI * 2;
    const cR = Math.min(W, H) * 0.22;
    const cx = W/2 + Math.cos(cAngle) * cR;
    const cy = H/2 + Math.sin(cAngle) * cR;
    const spread = 60 + Math.random() * 40;
    const a2 = Math.random() * Math.PI * 2;
    n.x = cx + Math.cos(a2) * spread;
    n.y = cy + Math.sin(a2) * spread;
    n.vx = 0; n.vy = 0;
});

// ── SVG ELEMENTS ──
const edgeEls = [];
edges.forEach(e => {
    const line = document.createElementNS(ns, 'line');
    line.setAttribute('stroke', 'rgba(255,255,255,0.06)');
    line.setAttribute('stroke-width', '1');
    line.setAttribute('marker-end', 'url(#arrow)');
    edgeGroup.appendChild(line);
    edgeEls.push({ el: line, data: e });

    const text = document.createElementNS(ns, 'text');
    text.setAttribute('class', 'edge-label');
    text.setAttribute('text-anchor', 'middle');
    text.textContent = e.label;
    edgeLabelGroup.appendChild(text);
    e._labelEl = text;
});

const nodeEls = [];
nodes.forEach(n => {
    const glow = document.createElementNS(ns, 'circle');
    glow.setAttribute('r', n.size + 4);
    glow.setAttribute('fill', n.color);
    glow.setAttribute('opacity', '0');
    nodeGroup.appendChild(glow);

    const circle = document.createElementNS(ns, 'circle');
    circle.setAttribute('r', n.size);
    circle.setAttribute('fill', n.color);
    circle.setAttribute('opacity', '0.85');
    circle.setAttribute('cursor', 'pointer');
    nodeGroup.appendChild(circle);

    const text = document.createElementNS(ns, 'text');
    text.setAttribute('fill', '#dfe6e9');
    text.setAttribute('font-size', Math.max(9, Math.min(12, n.size * 0.7)));
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dy', n.size + 14);
    text.setAttribute('pointer-events', 'none');
    text.textContent = n.label.length > 24 ? n.label.slice(0, 22) + '…' : n.label;
    labelGroup.appendChild(text);

    const el = { circle, glow, text, data: n };
    nodeEls.push(el);
    n._el = el;

    circle.addEventListener('mouseenter', () => onNodeHover(n));
    circle.addEventListener('mouseleave', () => onNodeLeave(n));
    circle.addEventListener('click', (ev) => { ev.stopPropagation(); onNodeClick(n); });
    circle.addEventListener('mousedown', (ev) => onDragStart(ev, n));
});

// ── GAP LINES ──
const gapEls = [];
if (analytics.gaps) {
    analytics.gaps.forEach(gap => {
        const line = document.createElementNS(ns, 'line');
        line.setAttribute('class', 'gap-line');
        const cA = communities[gap.communityA];
        const cB = communities[gap.communityB];
        line.setAttribute('stroke', cA ? cA.color : '#fff');
        line.setAttribute('stroke-width', '2');
        gapLineGroup.appendChild(line);
        gapEls.push({ el: line, data: gap });
    });
}

// ── FORCE SIMULATION (community-aware) ──
let alpha = 1, alphaDecay = 0.02, alphaMin = 0.001;
let dragging = null;

function simulate() {
    if (alpha < alphaMin && !dragging) { requestAnimationFrame(simulate); return; }
    alpha *= (1 - alphaDecay);
    if (alpha < alphaMin) alpha = alphaMin;

    const cx = W/2, cy = H/2;
    // Center gravity
    nodes.forEach(n => {
        n.vx += (cx - n.x) * 0.001 * alpha;
        n.vy += (cy - n.y) * 0.001 * alpha;
    });

    // Repulsion (community-aware: inter-community 1.3x)
    const repulse = 900;
    for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
            const a = nodes[i], b = nodes[j];
            let dx = a.x - b.x, dy = a.y - b.y;
            let d2 = dx*dx + dy*dy;
            if (d2 < 1) d2 = 1;
            const d = Math.sqrt(d2);
            const communityBonus = (a.community !== undefined && a.community !== b.community) ? 1.3 : 1.0;
            const force = repulse * alpha * communityBonus / d2;
            const fx = dx/d * force, fy = dy/d * force;
            a.vx += fx; a.vy += fy;
            b.vx -= fx; b.vy -= fy;
        }
    }

    // Attraction (community-aware: intra-community 1.5x)
    const attract = 0.018;
    const idealLen = 110;
    edges.forEach(e => {
        const s = nodeIndex[e.source], t = nodeIndex[e.target];
        if (!s || !t) return;
        const dx = t.x - s.x, dy = t.y - s.y;
        const d = Math.sqrt(dx*dx + dy*dy) || 1;
        const communityBonus = (s.community !== undefined && s.community === t.community) ? 1.5 : 1.0;
        const force = (d - idealLen) * attract * alpha * communityBonus;
        const fx = dx/d * force, fy = dy/d * force;
        s.vx += fx; s.vy += fy;
        t.vx -= fx; t.vy -= fy;
    });

    // Velocity decay + update
    nodes.forEach(n => {
        if (n === dragging) return;
        n.vx *= 0.6; n.vy *= 0.6;
        n.x += n.vx; n.y += n.vy;
        n.x = Math.max(30, Math.min(W - 30, n.x));
        n.y = Math.max(30, Math.min(H - 30, n.y));
    });

    render();
    requestAnimationFrame(simulate);
}

function render() {
    nodeEls.forEach(({ circle, glow, text, data: n }) => {
        circle.setAttribute('cx', n.x); circle.setAttribute('cy', n.y);
        glow.setAttribute('cx', n.x); glow.setAttribute('cy', n.y);
        text.setAttribute('x', n.x); text.setAttribute('y', n.y);
    });
    edgeEls.forEach(({ el, data: e }) => {
        const s = nodeIndex[e.source], t = nodeIndex[e.target];
        if (!s || !t) return;
        el.setAttribute('x1', s.x); el.setAttribute('y1', s.y);
        el.setAttribute('x2', t.x); el.setAttribute('y2', t.y);
        if (e._labelEl) {
            e._labelEl.setAttribute('x', (s.x + t.x)/2);
            e._labelEl.setAttribute('y', (s.y + t.y)/2 - 4);
        }
    });
    // Gap lines connect community centroids
    gapEls.forEach(({ el, data: gap }) => {
        const cANodes = nodes.filter(n => n.community === gap.communityA);
        const cBNodes = nodes.filter(n => n.community === gap.communityB);
        if (cANodes.length && cBNodes.length) {
            const ax = cANodes.reduce((s,n)=>s+n.x,0)/cANodes.length;
            const ay = cANodes.reduce((s,n)=>s+n.y,0)/cANodes.length;
            const bx = cBNodes.reduce((s,n)=>s+n.x,0)/cBNodes.length;
            const by = cBNodes.reduce((s,n)=>s+n.y,0)/cBNodes.length;
            el.setAttribute('x1', ax); el.setAttribute('y1', ay);
            el.setAttribute('x2', bx); el.setAttribute('y2', by);
        }
    });
}

// ── ZOOM & PAN ──
let transform = { x: 0, y: 0, k: 1 };
let isPanning = false, panStart = { x: 0, y: 0 };

function applyTransform() {
    const g = `translate(${transform.x},${transform.y}) scale(${transform.k})`;
    [edgeGroup, gapLineGroup, edgeLabelGroup, nodeGroup, labelGroup].forEach(grp =>
        grp.setAttribute('transform', g));
}

svg.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    const scale = ev.deltaY > 0 ? 0.92 : 1.08;
    const rect = svg.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    transform.x = mx - (mx - transform.x) * scale;
    transform.y = my - (my - transform.y) * scale;
    transform.k = Math.max(0.1, Math.min(5, transform.k * scale));
    applyTransform();
}, { passive: false });

svg.addEventListener('mousedown', (ev) => {
    if (ev.target === svg || ev.target.tagName === 'line') {
        isPanning = true;
        panStart = { x: ev.clientX - transform.x, y: ev.clientY - transform.y };
    }
});
window.addEventListener('mousemove', (ev) => {
    if (isPanning) {
        transform.x = ev.clientX - panStart.x;
        transform.y = ev.clientY - panStart.y;
        applyTransform();
    }
    if (dragging) {
        const rect = svg.getBoundingClientRect();
        dragging.x = (ev.clientX - rect.left - transform.x) / transform.k;
        dragging.y = (ev.clientY - rect.top - transform.y) / transform.k;
        dragging.vx = 0; dragging.vy = 0;
        alpha = 0.3;
    }
});
window.addEventListener('mouseup', () => { isPanning = false; dragging = null; });

function onDragStart(ev, node) { ev.stopPropagation(); dragging = node; alpha = 0.3; }

// ── PIN STATE ──
const pinnedNodes = new Set();

function updatePinVisuals() {
    if (pinnedNodes.size === 0) {
        // Reset all
        nodeEls.forEach(({ circle, glow, text, data: n }) => {
            n._dimmed = false;
            circle.setAttribute('fill', n.color);
            circle.setAttribute('opacity', '0.85');
            text.setAttribute('opacity', '1');
            glow.setAttribute('opacity', '0');
        });
        edgeEls.forEach(({ el }) => {
            el.setAttribute('stroke', 'rgba(255,255,255,0.06)');
            el.setAttribute('stroke-width', '1');
        });
        return;
    }

    // Compute visible set: pinned + their shared neighbors (if multiple) or all neighbors (if single)
    let visible;
    if (pinnedNodes.size === 1) {
        const pid = [...pinnedNodes][0];
        visible = new Set([pid, ...adjacency[pid]]);
    } else {
        // Intersection of neighbors + all pinned
        const neighborSets = [...pinnedNodes].map(pid => adjacency[pid]);
        let shared = new Set(neighborSets[0]);
        for (let i = 1; i < neighborSets.length; i++) {
            shared = new Set([...shared].filter(x => neighborSets[i].has(x)));
        }
        visible = new Set([...pinnedNodes, ...shared]);
    }

    nodeEls.forEach(({ circle, glow, text, data: n }) => {
        const isVisible = visible.has(n.id);
        const isPinned = pinnedNodes.has(n.id);
        n._dimmed = !isVisible;
        circle.setAttribute('opacity', isVisible ? '1' : '0.06');
        text.setAttribute('opacity', isVisible ? '1' : '0.06');
        if (isPinned) {
            circle.setAttribute('fill', 'var(--pin-color)');
            glow.setAttribute('fill', 'var(--pin-color)');
            glow.setAttribute('opacity', '0.4');
        } else {
            circle.setAttribute('fill', n.color);
            glow.setAttribute('opacity', '0');
        }
    });
    edgeEls.forEach(({ el, data: e }) => {
        const show = visible.has(e.source) && visible.has(e.target) &&
                     (pinnedNodes.has(e.source) || pinnedNodes.has(e.target));
        el.setAttribute('stroke', show ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.015)');
        el.setAttribute('stroke-width', show ? '2' : '1');
    });
}

// Click background clears pins
svg.addEventListener('click', (ev) => {
    if (ev.target === svg) {
        pinnedNodes.clear();
        updatePinVisuals();
        document.getElementById('info').style.display = 'none';
    }
});

// ── HOVER ──
const tooltip = document.getElementById('tooltip');

function onNodeHover(node) {
    if (pinnedNodes.size > 0) {
        // Don't change visibility, just show tooltip
    } else {
        node._el.glow.setAttribute('opacity', '0.3');
        node._el.circle.setAttribute('opacity', '1');
        const connected = adjacency[node.id];
        nodeEls.forEach(({ circle, text, data: n }) => {
            if (n === node || connected.has(n.id)) {
                circle.setAttribute('opacity', '1'); text.setAttribute('opacity', '1');
            } else {
                circle.setAttribute('opacity', '0.1'); text.setAttribute('opacity', '0.1');
            }
        });
        edgeEls.forEach(({ el, data: e }) => {
            if (e.source === node.id || e.target === node.id) {
                el.setAttribute('stroke', 'rgba(255,255,255,0.3)'); el.setAttribute('stroke-width', '2');
            } else {
                el.setAttribute('stroke', 'rgba(255,255,255,0.015)');
            }
        });
    }

    let ttHtml = `${node.label}`;
    if (node.type) ttHtml += ` <span class="tooltip-bc">${node.type}</span>`;
    ttHtml += `<br><span class="tooltip-bc">BC: ${node.bc?.toFixed(3) || 0} · Degree: ${node.degree || 0}</span>`;
    tooltip.innerHTML = ttHtml;
    tooltip.style.display = 'block';
    document.addEventListener('mousemove', moveTooltip);
}
function moveTooltip(ev) { tooltip.style.left = (ev.clientX+12)+'px'; tooltip.style.top = (ev.clientY-8)+'px'; }

function onNodeLeave(node) {
    tooltip.style.display = 'none';
    document.removeEventListener('mousemove', moveTooltip);
    if (pinnedNodes.size > 0) {
        updatePinVisuals();
    } else {
        node._el.glow.setAttribute('opacity', '0');
        nodeEls.forEach(({ circle, text, data: n }) => {
            circle.setAttribute('opacity', n._dimmed ? '0.06' : '0.85');
            text.setAttribute('opacity', n._dimmed ? '0.06' : '1');
        });
        edgeEls.forEach(({ el }) => {
            el.setAttribute('stroke', 'rgba(255,255,255,0.06)'); el.setAttribute('stroke-width', '1');
        });
    }
}

// ── CLICK / PIN ──
const infoPanel = document.getElementById('info');

function onNodeClick(node) {
    if (pinnedNodes.has(node.id)) {
        pinnedNodes.delete(node.id);
    } else {
        pinnedNodes.add(node.id);
    }
    updatePinVisuals();
    showNodeInfo(node);
}

function showNodeInfo(node) {
    const outgoing = edges.filter(e => e.source === node.id);
    const incoming = edges.filter(e => e.target === node.id);
    const comm = communities[node.community];
    let html = `<h3>${node.label}</h3>`;
    html += `<div class="node-stats">`;
    if (node.type) html += `<span class="type-badge" style="background:${node.color}33;color:${node.color}">${node.type}</span> `;
    if (comm) html += `<span class="type-badge" style="background:${comm.color}33;color:${comm.color}">Topic ${node.community}</span>`;
    html += `<br>BC: ${node.bc?.toFixed(3) || 0} · Degree: ${node.degree || 0}`;
    html += `</div>`;
    html += `<div class="connections">`;
    if (outgoing.length) {
        html += `<div style="color:var(--text-dim)">→ ${outgoing.length} outgoing</div>`;
        outgoing.slice(0, 8).forEach(e => {
            const t = nodeIndex[e.target];
            html += `<div class="conn-item">${e.label} → ${t ? t.label : e.target}</div>`;
        });
        if (outgoing.length > 8) html += `<div class="conn-item" style="color:var(--text-dim)">… +${outgoing.length - 8} more</div>`;
    }
    if (incoming.length) {
        html += `<div style="margin-top:4px;color:var(--text-dim)">← ${incoming.length} incoming</div>`;
        incoming.slice(0, 8).forEach(e => {
            const s = nodeIndex[e.source];
            html += `<div class="conn-item">${s ? s.label : e.source} → ${e.label}</div>`;
        });
        if (incoming.length > 8) html += `<div class="conn-item" style="color:var(--text-dim)">… +${incoming.length - 8} more</div>`;
    }
    html += `</div>`;
    infoPanel.innerHTML = html;
    infoPanel.style.display = 'block';
}

// ── SEARCH ──
const searchInput = document.getElementById('search');
searchInput.addEventListener('input', () => {
    const q = searchInput.value.toLowerCase().trim();
    pinnedNodes.clear();
    if (!q) { updatePinVisuals(); return; }

    const matching = new Set();
    nodes.forEach(n => {
        if (n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q) || (n.type||'').toLowerCase().includes(q)) {
            matching.add(n.id);
            adjacency[n.id].forEach(id => matching.add(id));
        }
    });
    nodeEls.forEach(({ circle, text, data: n }) => {
        const m = matching.has(n.id);
        n._dimmed = !m;
        circle.setAttribute('opacity', m ? '1' : '0.06');
        text.setAttribute('opacity', m ? '1' : '0.06');
    });
    edgeEls.forEach(({ el, data: e }) => {
        const m = matching.has(e.source) && matching.has(e.target);
        el.setAttribute('stroke', m ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.01)');
    });
});

// ── COMMUNITY LEGEND ──
const legendEl = document.getElementById('legend');
const activeCommunities = new Set(communities.map(c => c.id));

communities.forEach(c => {
    if (c.nodeCount === 0) return;
    const item = document.createElement('div');
    item.className = 'legend-item';
    const topLabels = (c.topNodes || []).slice(0, 3).join(', ');
    item.innerHTML = `<span class="legend-dot" style="background:${c.color}"></span>
        <span>${topLabels || 'Topic ' + c.id}</span>
        <span class="legend-meta">${c.nodeCount}</span>`;
    item.addEventListener('click', () => {
        if (activeCommunities.has(c.id)) {
            activeCommunities.delete(c.id);
            item.classList.add('dimmed');
        } else {
            activeCommunities.add(c.id);
            item.classList.remove('dimmed');
        }
        applyCommunityFilter();
    });
    legendEl.appendChild(item);
});

function applyCommunityFilter() {
    nodeEls.forEach(({ circle, text, data: n }) => {
        const visible = activeCommunities.has(n.community);
        n._dimmed = !visible;
        circle.setAttribute('opacity', visible ? '0.85' : '0.04');
        text.setAttribute('opacity', visible ? '1' : '0.04');
    });
    edgeEls.forEach(({ el, data: e }) => {
        const sv = nodeIndex[e.source], tv = nodeIndex[e.target];
        const visible = sv && tv && !sv._dimmed && !tv._dimmed;
        el.setAttribute('stroke', visible ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.01)');
    });
}

// ── ANALYTICS PANEL ──
const analyticsPanel = document.getElementById('analytics');

function buildAnalyticsPanel() {
    let html = '';

    // Overview
    html += `<h2>Overview</h2>`;
    html += `<div class="metric-row"><span class="metric-label">Nodes</span><span class="metric-value">${nodes.length}</span></div>`;
    html += `<div class="metric-row"><span class="metric-label">Edges</span><span class="metric-value">${edges.length}</span></div>`;
    html += `<div class="metric-row"><span class="metric-label">Density</span><span class="metric-value">${analytics.density || 0}</span></div>`;
    html += `<div class="metric-row"><span class="metric-label">Components</span><span class="metric-value">${analytics.componentCount || 1}</span></div>`;
    html += `<div class="metric-row"><span class="metric-label">Avg Degree</span><span class="metric-value">${analytics.avgDegree || 0}</span></div>`;

    // Structure
    html += `<h2>Structure</h2>`;
    html += `<div class="metric-row"><span class="metric-label">Modularity</span><span class="metric-value">${analytics.modularity || 0}</span></div>`;
    html += `<div class="metric-row"><span class="metric-label">Communities</span><span class="metric-value">${communities.length}</span></div>`;
    const bias = analytics.biasLabel || 'Unknown';
    html += `<div><span class="bias-badge bias-${bias}">${bias}</span></div>`;

    // Influential
    if (analytics.topBCNodes && analytics.topBCNodes.length) {
        html += `<h2>Most Influential</h2>`;
        analytics.topBCNodes.forEach(n => {
            html += `<div class="influential-item" data-node="${n.id}">
                <span class="legend-dot" style="background:${n.color}"></span>
                ${n.label}
                <span class="influential-bc">${n.bc.toFixed(3)}</span>
            </div>`;
        });
    }

    // Gaps
    if (analytics.gaps && analytics.gaps.length) {
        html += `<h2>Structural Gaps</h2>`;
        analytics.gaps.forEach(gap => {
            html += `<div class="gap-item">
                <div class="gap-question">${gap.question}</div>
                <div class="gap-meta">Communities ${gap.communityA} ↔ ${gap.communityB} · ${gap.crossEdges} cross-edges</div>
            </div>`;
        });
    }

    analyticsPanel.innerHTML = html;

    // Click handlers for influential nodes
    analyticsPanel.querySelectorAll('.influential-item').forEach(el => {
        el.addEventListener('click', () => {
            const nid = el.dataset.node;
            const node = nodeIndex[nid];
            if (node) {
                pinnedNodes.clear();
                pinnedNodes.add(nid);
                updatePinVisuals();
                showNodeInfo(node);
            }
        });
    });
}
buildAnalyticsPanel();
analyticsPanel.classList.add('visible');

// ── BUTTON ACTIONS ──
let sizingMode = 'bc'; // bc | degree | type

document.querySelectorAll('.btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const action = btn.dataset.action;
        if (action === 'toggle-edges') {
            btn.classList.toggle('active');
            edgeLabelGroup.style.display = btn.classList.contains('active') ? 'block' : 'none';
        } else if (action === 'toggle-gaps') {
            btn.classList.toggle('active');
            gapLineGroup.style.display = btn.classList.contains('active') ? 'block' : 'none';
        } else if (action === 'toggle-analytics') {
            btn.classList.toggle('active');
            analyticsPanel.classList.toggle('visible');
        } else if (action === 'cycle-sizing') {
            const modes = ['bc', 'degree', 'type'];
            sizingMode = modes[(modes.indexOf(sizingMode) + 1) % modes.length];
            btn.textContent = `● Size: ${sizingMode.toUpperCase()}`;
            applySizing();
        }
    });
});

function applySizing() {
    let values;
    if (sizingMode === 'bc') {
        values = nodes.map(n => n.bc || 0);
    } else if (sizingMode === 'degree') {
        values = nodes.map(n => n.degree || 0);
    } else {
        // Uniform
        nodes.forEach(n => {
            const newSize = 8;
            n.size = newSize;
            n._el.circle.setAttribute('r', newSize);
            n._el.glow.setAttribute('r', newSize + 4);
            n._el.text.setAttribute('dy', newSize + 14);
        });
        return;
    }
    const vmin = Math.min(...values), vmax = Math.max(...values);
    nodes.forEach((n, i) => {
        const t = vmax > vmin ? (values[i] - vmin) / (vmax - vmin) : 0.5;
        const newSize = Math.round(4 + t * 24);
        n.size = newSize;
        n._el.circle.setAttribute('r', newSize);
        n._el.glow.setAttribute('r', newSize + 4);
        n._el.text.setAttribute('dy', newSize + 14);
        n._el.text.setAttribute('font-size', Math.max(9, Math.min(12, newSize * 0.7)));
    });
}

// ── STATS ──
document.getElementById('stats').textContent =
    `${nodes.length} nodes · ${edges.length} edges · ${communities.length} communities · modularity ${analytics.modularity || 0}`;

// ── KEYBOARD ──
document.addEventListener('keydown', (ev) => {
    if (ev.key === '/' && document.activeElement !== searchInput) { ev.preventDefault(); searchInput.focus(); }
    if (ev.key === 'Escape') {
        searchInput.value = ''; searchInput.dispatchEvent(new Event('input')); searchInput.blur();
        pinnedNodes.clear(); updatePinVisuals();
        infoPanel.style.display = 'none';
    }
});

// ── START ──
simulate();
</script>
</body>
</html>"""


def serve_viz(
    store: DregsStore,
    port: int = 7171,
    graph_uri: Optional[str] = None,
    open_browser: bool = True,
    _prebuilt_data: Optional[dict] = None,
) -> None:
    """Build graph data and serve the interactive visualizer."""
    data = _prebuilt_data or _build_graph_data(store, graph_uri)
    html = _HTML.replace("__GRAPH_DATA__", json.dumps(data))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/" or self.path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            elif self.path == "/api/graph":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode("utf-8"))
            elif self.path == "/api/analytics":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data.get("analytics", {})).encode("utf-8"))
            else:
                self.send_error(404)

        def log_message(self, format, *args):
            pass

    class ReuseServer(http.server.HTTPServer):
        allow_reuse_address = True
        allow_reuse_port = True

    server = ReuseServer(("0.0.0.0", port), Handler)

    nc = len(data.get("nodes", []))
    ec = len(data.get("edges", []))
    cc = len(data.get("analytics", {}).get("communities", []))
    mod = data.get("analytics", {}).get("modularity", 0)
    bias = data.get("analytics", {}).get("biasLabel", "?")
    print(f"dregs viz — {nc} nodes, {ec} edges, {cc} communities (modularity={mod}, {bias})")
    print(f"Serving on http://0.0.0.0:{port}")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
