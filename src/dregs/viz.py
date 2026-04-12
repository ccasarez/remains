"""Interactive knowledge graph visualizer for dregs."""
from __future__ import annotations

import json
import http.server
import threading
import webbrowser
from typing import Optional

from dregs.store import DregsStore


def _build_graph_data(store: DregsStore, graph_uri: Optional[str] = None) -> dict:
    """Extract nodes and edges from the store for visualization."""
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

    # Also get labels/names for nodes
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

    # Type-to-color mapping
    type_colors = {
        "Meeting": "#4ecdc4",
        "Person": "#ff6b6b",
        "Organization": "#45b7d1",
        "Facility": "#96ceb4",
        "Decision": "#ffeaa7",
        "AgendaItem": "#dfe6e9",
        "RegulatoryDocument": "#a29bfe",
    }

    for row in result.bindings:
        s = row.get("s", "")
        p = row.get("p", "")
        o = row.get("o", "")
        stype = row.get("stype", "")
        otype = row.get("otype", "")

        if not s or not o:
            continue

        # Skip prov:wasDerivedFrom edges to URL nodes (clutters the graph)
        if "wasDerivedFrom" in p:
            continue

        s_short = shorten(s) if ":" not in s or s.startswith("http") else s
        o_short = shorten(o) if ":" not in o or o.startswith("http") else o

        # Extract type short names
        s_type_short = shorten(stype) if stype else ""
        o_type_short = shorten(otype) if otype else ""

        if s_short not in nodes_map:
            label = labels.get(s, s_short.split(":")[-1] if ":" in s_short else s_short)
            color = type_colors.get(s_type_short, "#b2bec3")
            nodes_map[s_short] = {
                "id": s_short,
                "label": label,
                "type": s_type_short,
                "color": color,
                "edges": 0,
            }

        if o_short not in nodes_map:
            label = labels.get(o, o_short.split(":")[-1] if ":" in o_short else o_short)
            color = type_colors.get(o_type_short, "#b2bec3")
            nodes_map[o_short] = {
                "id": o_short,
                "label": label,
                "type": o_type_short,
                "color": color,
                "edges": 0,
            }

        p_short = shorten(p) if ":" not in p or p.startswith("http") else p

        nodes_map[s_short]["edges"] += 1
        nodes_map[o_short]["edges"] += 1

        edges.append({
            "source": s_short,
            "target": o_short,
            "label": p_short.split(":")[-1] if ":" in p_short else p_short,
        })

    # Scale node sizes by edge count
    for node in nodes_map.values():
        node["size"] = max(4, min(20, 4 + node["edges"] * 1.5))

    return {
        "nodes": list(nodes_map.values()),
        "edges": edges,
        "types": list(type_colors.items()),
    }


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>dregs — knowledge graph</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: #0a0a0f;
    color: #c8d6e5;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    overflow: hidden;
}
#canvas { width: 100vw; height: 100vh; display: block; }
svg { width: 100%; height: 100%; }

/* Controls overlay */
#controls {
    position: fixed;
    top: 16px;
    left: 16px;
    z-index: 10;
    display: flex;
    flex-direction: column;
    gap: 8px;
}
#controls .panel {
    background: rgba(15, 15, 25, 0.92);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    padding: 12px 16px;
    backdrop-filter: blur(12px);
}
#controls h1 {
    font-size: 14px;
    font-weight: 600;
    color: #f5f6fa;
    letter-spacing: 0.5px;
}
#controls .subtitle {
    font-size: 11px;
    color: #636e72;
    margin-top: 2px;
}

/* Search */
#search {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    padding: 8px 12px;
    color: #dfe6e9;
    font-size: 13px;
    width: 240px;
    outline: none;
}
#search:focus { border-color: rgba(78, 205, 196, 0.5); }
#search::placeholder { color: #636e72; }

/* Legend */
.legend { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.legend-item {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    color: #b2bec3;
    cursor: pointer;
    padding: 2px 6px;
    border-radius: 4px;
    transition: background 0.15s;
}
.legend-item:hover { background: rgba(255,255,255,0.06); }
.legend-item.dimmed { opacity: 0.3; }
.legend-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

/* Filter buttons */
.filter-row {
    display: flex;
    gap: 4px;
    margin-top: 6px;
}
.filter-btn {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 4px;
    padding: 4px 8px;
    color: #b2bec3;
    font-size: 11px;
    cursor: pointer;
    transition: all 0.15s;
}
.filter-btn:hover { background: rgba(255,255,255,0.1); }
.filter-btn.active { background: rgba(78, 205, 196, 0.2); border-color: rgba(78, 205, 196, 0.4); color: #4ecdc4; }

/* Info panel */
#info {
    position: fixed;
    bottom: 16px;
    left: 16px;
    z-index: 10;
    background: rgba(15, 15, 25, 0.92);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    padding: 12px 16px;
    backdrop-filter: blur(12px);
    max-width: 360px;
    display: none;
}
#info h3 { font-size: 13px; color: #f5f6fa; margin-bottom: 4px; }
#info .type-badge {
    display: inline-block;
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 3px;
    margin-bottom: 6px;
}
#info .connections { font-size: 11px; color: #636e72; }
#info .conn-item { color: #b2bec3; padding: 1px 0; }

/* Stats */
#stats {
    position: fixed;
    bottom: 16px;
    right: 16px;
    z-index: 10;
    font-size: 11px;
    color: #636e72;
    background: rgba(15, 15, 25, 0.8);
    border-radius: 6px;
    padding: 6px 10px;
}

/* Edge labels */
.edge-label {
    font-size: 9px;
    fill: #636e72;
    pointer-events: none;
}

/* Tooltip */
.node-tooltip {
    position: fixed;
    background: rgba(15, 15, 25, 0.95);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    color: #f5f6fa;
    pointer-events: none;
    z-index: 100;
    display: none;
    white-space: nowrap;
}
</style>
</head>
<body>
<div id="canvas"></div>

<div id="controls">
    <div class="panel">
        <h1>dregs</h1>
        <div class="subtitle" id="graph-info"></div>
    </div>
    <div class="panel">
        <input type="text" id="search" placeholder="Search nodes…" autocomplete="off">
        <div class="legend" id="legend"></div>
        <div class="filter-row" id="filters">
            <button class="filter-btn active" data-filter="all">All</button>
            <button class="filter-btn" data-filter="edges">Show edge labels</button>
        </div>
    </div>
</div>

<div id="info"></div>
<div id="stats"></div>
<div class="node-tooltip" id="tooltip"></div>

<script>
// ── DATA (injected by server) ──
const GRAPH_DATA = __GRAPH_DATA__;

// ── SETUP ──
const container = document.getElementById('canvas');
const width = window.innerWidth;
const height = window.innerHeight;

const ns = 'http://www.w3.org/2000/svg';
const svg = document.createElementNS(ns, 'svg');
svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
container.appendChild(svg);

const defs = document.createElementNS(ns, 'defs');
svg.appendChild(defs);

// Arrow marker
const marker = document.createElementNS(ns, 'marker');
marker.setAttribute('id', 'arrow');
marker.setAttribute('viewBox', '0 -5 10 10');
marker.setAttribute('refX', 20);
marker.setAttribute('refY', 0);
marker.setAttribute('markerWidth', 6);
marker.setAttribute('markerHeight', 6);
marker.setAttribute('orient', 'auto');
const arrowPath = document.createElementNS(ns, 'path');
arrowPath.setAttribute('d', 'M0,-4L10,0L0,4');
arrowPath.setAttribute('fill', 'rgba(255,255,255,0.15)');
marker.appendChild(arrowPath);
defs.appendChild(marker);

// Groups for layering
const edgeGroup = document.createElementNS(ns, 'g');
const edgeLabelGroup = document.createElementNS(ns, 'g');
edgeLabelGroup.style.display = 'none';
const nodeGroup = document.createElementNS(ns, 'g');
const labelGroup = document.createElementNS(ns, 'g');
svg.appendChild(edgeGroup);
svg.appendChild(edgeLabelGroup);
svg.appendChild(nodeGroup);
svg.appendChild(labelGroup);

// ── NODES & EDGES ──
const nodes = GRAPH_DATA.nodes;
const edges = GRAPH_DATA.edges;
const typeColors = Object.fromEntries(GRAPH_DATA.types);

// Initialize positions
nodes.forEach((n, i) => {
    const angle = (i / nodes.length) * Math.PI * 2;
    const r = Math.min(width, height) * 0.35;
    n.x = width / 2 + Math.cos(angle) * r * (0.5 + Math.random() * 0.5);
    n.y = height / 2 + Math.sin(angle) * r * (0.5 + Math.random() * 0.5);
    n.vx = 0;
    n.vy = 0;
});

// Build node index
const nodeIndex = {};
nodes.forEach(n => nodeIndex[n.id] = n);

// Build adjacency
const adjacency = {};
nodes.forEach(n => adjacency[n.id] = new Set());
edges.forEach(e => {
    if (adjacency[e.source] && adjacency[e.target]) {
        adjacency[e.source].add(e.target);
        adjacency[e.target].add(e.source);
    }
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

    // Edge label
    const text = document.createElementNS(ns, 'text');
    text.setAttribute('class', 'edge-label');
    text.setAttribute('text-anchor', 'middle');
    text.textContent = e.label;
    edgeLabelGroup.appendChild(text);
    e._labelEl = text;
});

const nodeEls = [];
nodes.forEach(n => {
    // Glow
    const glow = document.createElementNS(ns, 'circle');
    glow.setAttribute('r', n.size + 4);
    glow.setAttribute('fill', n.color);
    glow.setAttribute('opacity', '0');
    glow.setAttribute('filter', 'blur(6px)');
    nodeGroup.appendChild(glow);

    const circle = document.createElementNS(ns, 'circle');
    circle.setAttribute('r', n.size);
    circle.setAttribute('fill', n.color);
    circle.setAttribute('opacity', '0.85');
    circle.setAttribute('cursor', 'pointer');
    nodeGroup.appendChild(circle);

    // Label
    const text = document.createElementNS(ns, 'text');
    text.setAttribute('fill', '#dfe6e9');
    text.setAttribute('font-size', Math.max(9, Math.min(12, n.size * 0.8)));
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dy', n.size + 14);
    text.setAttribute('pointer-events', 'none');
    text.textContent = n.label.length > 24 ? n.label.slice(0, 22) + '…' : n.label;
    labelGroup.appendChild(text);

    const el = { circle, glow, text, data: n };
    nodeEls.push(el);
    n._el = el;

    // Events
    circle.addEventListener('mouseenter', () => onNodeHover(n));
    circle.addEventListener('mouseleave', () => onNodeLeave(n));
    circle.addEventListener('click', () => onNodeClick(n));
    circle.addEventListener('mousedown', (ev) => onDragStart(ev, n));
});

// ── FORCE SIMULATION ──
let alpha = 1;
let alphaDecay = 0.0228;
let alphaMin = 0.001;
let dragging = null;

function simulate() {
    if (alpha < alphaMin && !dragging) {
        requestAnimationFrame(simulate);
        return;
    }

    alpha *= (1 - alphaDecay);
    if (alpha < alphaMin) alpha = alphaMin;

    // Center gravity
    const cx = width / 2, cy = height / 2;
    nodes.forEach(n => {
        n.vx += (cx - n.x) * 0.0008 * alpha;
        n.vy += (cy - n.y) * 0.0008 * alpha;
    });

    // Repulsion (Barnes-Hut approximation via grid)
    const repulse = 800;
    for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
            const a = nodes[i], b = nodes[j];
            let dx = a.x - b.x, dy = a.y - b.y;
            let d2 = dx * dx + dy * dy;
            if (d2 < 1) d2 = 1;
            const d = Math.sqrt(d2);
            const force = repulse * alpha / d2;
            const fx = dx / d * force;
            const fy = dy / d * force;
            a.vx += fx; a.vy += fy;
            b.vx -= fx; b.vy -= fy;
        }
    }

    // Attraction along edges
    const attract = 0.02;
    const idealLen = 120;
    edges.forEach(e => {
        const s = nodeIndex[e.source], t = nodeIndex[e.target];
        if (!s || !t) return;
        const dx = t.x - s.x, dy = t.y - s.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (d - idealLen) * attract * alpha;
        const fx = dx / d * force;
        const fy = dy / d * force;
        s.vx += fx; s.vy += fy;
        t.vx -= fx; t.vy -= fy;
    });

    // Velocity decay + position update
    nodes.forEach(n => {
        if (n === dragging) return;
        n.vx *= 0.6;
        n.vy *= 0.6;
        n.x += n.vx;
        n.y += n.vy;
        // Bounds
        n.x = Math.max(20, Math.min(width - 20, n.x));
        n.y = Math.max(20, Math.min(height - 20, n.y));
    });

    render();
    requestAnimationFrame(simulate);
}

function render() {
    nodeEls.forEach(({ circle, glow, text, data: n }) => {
        circle.setAttribute('cx', n.x);
        circle.setAttribute('cy', n.y);
        glow.setAttribute('cx', n.x);
        glow.setAttribute('cy', n.y);
        text.setAttribute('x', n.x);
        text.setAttribute('y', n.y);
    });

    edgeEls.forEach(({ el, data: e }) => {
        const s = nodeIndex[e.source], t = nodeIndex[e.target];
        if (!s || !t) return;
        el.setAttribute('x1', s.x);
        el.setAttribute('y1', s.y);
        el.setAttribute('x2', t.x);
        el.setAttribute('y2', t.y);
        if (e._labelEl) {
            e._labelEl.setAttribute('x', (s.x + t.x) / 2);
            e._labelEl.setAttribute('y', (s.y + t.y) / 2 - 4);
        }
    });
}

// ── ZOOM & PAN ──
let transform = { x: 0, y: 0, k: 1 };
let isPanning = false, panStart = { x: 0, y: 0 };

function applyTransform() {
    const g = `translate(${transform.x},${transform.y}) scale(${transform.k})`;
    edgeGroup.setAttribute('transform', g);
    edgeLabelGroup.setAttribute('transform', g);
    nodeGroup.setAttribute('transform', g);
    labelGroup.setAttribute('transform', g);
}

svg.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    const scale = ev.deltaY > 0 ? 0.92 : 1.08;
    const rect = svg.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    transform.x = mx - (mx - transform.x) * scale;
    transform.y = my - (my - transform.y) * scale;
    transform.k *= scale;
    transform.k = Math.max(0.1, Math.min(5, transform.k));
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
        dragging.vx = 0;
        dragging.vy = 0;
        alpha = 0.3;
    }
});
window.addEventListener('mouseup', () => {
    isPanning = false;
    dragging = null;
});

// ── DRAG ──
function onDragStart(ev, node) {
    ev.stopPropagation();
    dragging = node;
    alpha = 0.3;
}

// ── HOVER ──
const tooltip = document.getElementById('tooltip');
let hoveredNode = null;

function onNodeHover(node) {
    hoveredNode = node;
    node._el.glow.setAttribute('opacity', '0.3');
    node._el.circle.setAttribute('opacity', '1');

    // Highlight connected
    const connected = adjacency[node.id];
    nodeEls.forEach(({ circle, text, data: n }) => {
        if (n === node || connected.has(n.id)) {
            circle.setAttribute('opacity', '1');
            text.setAttribute('opacity', '1');
        } else {
            circle.setAttribute('opacity', '0.12');
            text.setAttribute('opacity', '0.12');
        }
    });
    edgeEls.forEach(({ el, data: e }) => {
        if (e.source === node.id || e.target === node.id) {
            el.setAttribute('stroke', 'rgba(255,255,255,0.3)');
            el.setAttribute('stroke-width', '2');
        } else {
            el.setAttribute('stroke', 'rgba(255,255,255,0.02)');
        }
    });

    // Tooltip
    tooltip.textContent = node.label + (node.type ? ` (${node.type})` : '');
    tooltip.style.display = 'block';
    document.addEventListener('mousemove', moveTooltip);
}

function moveTooltip(ev) {
    tooltip.style.left = (ev.clientX + 12) + 'px';
    tooltip.style.top = (ev.clientY - 8) + 'px';
}

function onNodeLeave(node) {
    hoveredNode = null;
    node._el.glow.setAttribute('opacity', '0');
    tooltip.style.display = 'none';
    document.removeEventListener('mousemove', moveTooltip);

    nodeEls.forEach(({ circle, text, data: n }) => {
        circle.setAttribute('opacity', n._dimmed ? '0.08' : '0.85');
        text.setAttribute('opacity', n._dimmed ? '0.08' : '1');
    });
    edgeEls.forEach(({ el }) => {
        el.setAttribute('stroke', 'rgba(255,255,255,0.06)');
        el.setAttribute('stroke-width', '1');
    });
}

// ── CLICK / INFO ──
const infoPanel = document.getElementById('info');

function onNodeClick(node) {
    // Get connections
    const outgoing = edges.filter(e => e.source === node.id);
    const incoming = edges.filter(e => e.target === node.id);

    let html = `<h3>${node.label}</h3>`;
    if (node.type) {
        html += `<span class="type-badge" style="background:${node.color}33;color:${node.color}">${node.type}</span>`;
    }
    html += `<div class="connections">`;
    if (outgoing.length) {
        html += `<div style="margin-top:6px;color:#636e72">→ outgoing (${outgoing.length})</div>`;
        outgoing.forEach(e => {
            const target = nodeIndex[e.target];
            html += `<div class="conn-item">  ${e.label} → ${target ? target.label : e.target}</div>`;
        });
    }
    if (incoming.length) {
        html += `<div style="margin-top:6px;color:#636e72">← incoming (${incoming.length})</div>`;
        incoming.forEach(e => {
            const source = nodeIndex[e.source];
            html += `<div class="conn-item">  ${source ? source.label : e.source} → ${e.label}</div>`;
        });
    }
    html += `</div>`;
    infoPanel.innerHTML = html;
    infoPanel.style.display = 'block';
}

// ── SEARCH ──
const searchInput = document.getElementById('search');
searchInput.addEventListener('input', () => {
    const q = searchInput.value.toLowerCase().trim();
    if (!q) {
        nodeEls.forEach(({ circle, text, data: n }) => {
            n._dimmed = false;
            circle.setAttribute('opacity', '0.85');
            text.setAttribute('opacity', '1');
        });
        edgeEls.forEach(({ el }) => {
            el.setAttribute('stroke', 'rgba(255,255,255,0.06)');
        });
        return;
    }

    const matching = new Set();
    nodes.forEach(n => {
        if (n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q) || n.type.toLowerCase().includes(q)) {
            matching.add(n.id);
            // Also highlight neighbors
            adjacency[n.id].forEach(id => matching.add(id));
        }
    });

    nodeEls.forEach(({ circle, text, data: n }) => {
        const match = matching.has(n.id);
        n._dimmed = !match;
        circle.setAttribute('opacity', match ? '1' : '0.08');
        text.setAttribute('opacity', match ? '1' : '0.08');
    });
    edgeEls.forEach(({ el, data: e }) => {
        const match = matching.has(e.source) && matching.has(e.target);
        el.setAttribute('stroke', match ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.01)');
    });
});

// ── LEGEND ──
const legendEl = document.getElementById('legend');
const activeTypes = new Set(GRAPH_DATA.types.map(t => t[0]));
activeTypes.add('');  // untyped

GRAPH_DATA.types.forEach(([type, color]) => {
    const count = nodes.filter(n => n.type === type).length;
    if (count === 0) return;
    const item = document.createElement('div');
    item.className = 'legend-item';
    item.innerHTML = `<span class="legend-dot" style="background:${color}"></span>${type} (${count})`;
    item.addEventListener('click', () => {
        if (activeTypes.has(type)) {
            activeTypes.delete(type);
            item.classList.add('dimmed');
        } else {
            activeTypes.add(type);
            item.classList.remove('dimmed');
        }
        applyTypeFilter();
    });
    legendEl.appendChild(item);
});

function applyTypeFilter() {
    nodeEls.forEach(({ circle, text, data: n }) => {
        const visible = activeTypes.has(n.type) || activeTypes.has('');
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

// ── FILTER BUTTONS ──
document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const filter = btn.dataset.filter;
        if (filter === 'edges') {
            btn.classList.toggle('active');
            edgeLabelGroup.style.display = btn.classList.contains('active') ? 'block' : 'none';
        }
    });
});

// ── STATS ──
document.getElementById('stats').textContent = `${nodes.length} nodes · ${edges.length} edges`;
document.getElementById('graph-info').textContent = `knowledge graph visualizer`;

// ── KEYBOARD ──
document.addEventListener('keydown', (ev) => {
    if (ev.key === '/' && document.activeElement !== searchInput) {
        ev.preventDefault();
        searchInput.focus();
    }
    if (ev.key === 'Escape') {
        searchInput.value = '';
        searchInput.dispatchEvent(new Event('input'));
        searchInput.blur();
        infoPanel.style.display = 'none';
    }
});

// ── START ──
simulate();
</script>
</body>
</html>"""


def serve_viz(store: DregsStore, port: int = 7171, graph_uri: Optional[str] = None, open_browser: bool = True, _prebuilt_data: Optional[dict] = None) -> None:
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
            else:
                self.send_error(404)

        def log_message(self, format, *args):
            pass  # Suppress request logs

    import socket as _socket

    class ReuseServer(http.server.HTTPServer):
        allow_reuse_address = True
        allow_reuse_port = True

    server = ReuseServer(("0.0.0.0", port), Handler)

    node_count = len(data["nodes"])
    edge_count = len(data["edges"])
    print(f"dregs viz — {node_count} nodes, {edge_count} edges")
    print(f"Serving on http://0.0.0.0:{port}")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
