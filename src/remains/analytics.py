"""Graph analytics: community detection, centrality, structural gap analysis."""
from __future__ import annotations

import math
from typing import Optional

import networkx as nx
from networkx.algorithms.community import louvain_communities


def compute_analytics(
    nodes: list[dict],
    edges: list[dict],
) -> dict:
    """Compute community detection, centrality, and structural gap analysis.

    Operates on the pre-extracted node/edge dicts from _build_graph_data.
    Returns analytics dict to be merged into the graph JSON.
    """
    if len(nodes) == 0:
        return _empty_analytics(nodes, edges)

    # Build undirected networkx graph
    G = nx.Graph()
    node_ids = {n["id"] for n in nodes}
    for n in nodes:
        G.add_node(n["id"])
    for e in edges:
        if e["source"] in node_ids and e["target"] in node_ids:
            # Weight by edge count between same pair
            if G.has_edge(e["source"], e["target"]):
                G[e["source"]][e["target"]]["weight"] += 1
            else:
                G.add_edge(e["source"], e["target"], weight=1)

    # ── Community detection (Louvain) ──
    communities = _detect_communities(G)
    node_community = {}  # node_id -> community_id
    for cid, members in enumerate(communities):
        for nid in members:
            node_community[nid] = cid

    # Community colors — evenly spaced hues on dark-bg palette
    n_communities = len(communities)
    community_colors = _generate_community_palette(n_communities)

    # Modularity
    modularity = _compute_modularity(G, communities)

    # ── Betweenness centrality ──
    bc_scores = _compute_betweenness(G)

    # ── Degree ──
    degrees = dict(G.degree())

    # ── Class (RDF type) palette ──
    distinct_types = sorted({n.get("type", "") for n in nodes} - {""})
    class_colors = _generate_community_palette(len(distinct_types))
    class_palette = {t: class_colors[i] for i, t in enumerate(distinct_types)}

    # ── Annotate nodes ──
    bc_values = list(bc_scores.values()) if bc_scores else [0]
    bc_min, bc_max = min(bc_values), max(bc_values)

    for n in nodes:
        nid = n["id"]
        cid = node_community.get(nid, 0)
        n["community"] = cid
        n["communityColor"] = community_colors[cid] if cid < len(community_colors) else "#b2bec3"
        n["classColor"] = class_palette.get(n.get("type", ""), "#b2bec3")
        n["bc"] = round(bc_scores.get(nid, 0), 4)
        n["degree"] = degrees.get(nid, 0)

        # Size by BC (lerp between 4 and 28)
        if bc_max > bc_min:
            t = (bc_scores.get(nid, 0) - bc_min) / (bc_max - bc_min)
        else:
            t = 0.5
        n["size"] = round(4 + t * 24, 1)

    # ── Community metadata ──
    community_meta = []
    for cid, members in enumerate(communities):
        # Top nodes by BC within community
        member_bc = [(m, bc_scores.get(m, 0)) for m in members]
        member_bc.sort(key=lambda x: -x[1])
        top_nodes = [m for m, _ in member_bc[:3]]
        # Get labels
        node_index = {n["id"]: n for n in nodes}
        top_labels = [node_index[nid]["label"] for nid in top_nodes if nid in node_index]

        community_meta.append({
            "id": cid,
            "nodeCount": len(members),
            "color": community_colors[cid] if cid < len(community_colors) else "#b2bec3",
            "topNodes": top_labels,
        })

    # Sort by size descending
    community_meta.sort(key=lambda c: -c["nodeCount"])

    # ── Graph stats ──
    density = nx.density(G) if len(G) > 1 else 0
    n_components = nx.number_connected_components(G)
    avg_degree = sum(degrees.values()) / len(degrees) if degrees else 0

    # ── Structural gap analysis ──
    gaps = _find_gaps(G, communities, node_community, bc_scores, nodes)

    # ── Bias label ──
    bias_label = _compute_bias_label(modularity, communities, len(nodes))

    # ── Top BC nodes ──
    top_bc = sorted(nodes, key=lambda n: -n["bc"])[:4]
    top_bc_list = [
        {"id": n["id"], "label": n["label"], "bc": n["bc"],
         "community": n["community"], "color": n["classColor"]}
        for n in top_bc
    ]

    return {
        "communities": community_meta,
        "classPalette": class_palette,
        "modularity": round(modularity, 3),
        "density": round(density, 4),
        "componentCount": n_components,
        "avgDegree": round(avg_degree, 1),
        "biasLabel": bias_label,
        "gaps": gaps,
        "topBCNodes": top_bc_list,
    }


def _detect_communities(G: "nx.Graph") -> list[set]:
    """Run Louvain community detection. Returns list of node-id sets."""
    if len(G) == 0:
        return []
    try:
        communities = louvain_communities(G, weight="weight", resolution=1.0, seed=42)
        # Sort by size descending
        return sorted(communities, key=len, reverse=True)
    except Exception:
        # Fallback: each connected component is a community
        return [set(c) for c in nx.connected_components(G)]


def _compute_modularity(G: "nx.Graph", communities: list[set]) -> float:
    """Compute modularity score for the community partition."""
    if len(communities) <= 1 or len(G.edges()) == 0:
        return 0.0
    try:
        return nx.community.modularity(G, communities, weight="weight")
    except Exception:
        return 0.0


def _compute_betweenness(G: "nx.Graph") -> dict[str, float]:
    """Compute normalized betweenness centrality. Uses approximate BC for large graphs."""
    if len(G) <= 2:
        return {n: 0.0 for n in G.nodes()}

    try:
        if len(G) > 1000:
            # Approximate with k sampled pivots
            return nx.betweenness_centrality(G, weight="weight", normalized=True, k=min(100, len(G)))
        else:
            return nx.betweenness_centrality(G, weight="weight", normalized=True)
    except Exception:
        return {n: 0.0 for n in G.nodes()}


def _find_gaps(
    G: "nx.Graph",
    communities: list[set],
    node_community: dict[str, int],
    bc_scores: dict[str, float],
    nodes: list[dict],
) -> list[dict]:
    """Find structural gaps between communities."""
    if len(communities) <= 1:
        return []

    node_index = {n["id"]: n for n in nodes}

    # Count cross-community edges for each pair
    pair_edges = {}
    for u, v in G.edges():
        cu = node_community.get(u, -1)
        cv = node_community.get(v, -1)
        if cu != cv and cu >= 0 and cv >= 0:
            pair = (min(cu, cv), max(cu, cv))
            pair_edges[pair] = pair_edges.get(pair, 0) + 1

    # Find all community pairs
    gaps = []
    for i in range(len(communities)):
        for j in range(i + 1, len(communities)):
            # Only consider pairs where both communities have at least 2 nodes
            if len(communities[i]) < 2 or len(communities[j]) < 2:
                continue
            pair = (i, j)
            cross = pair_edges.get(pair, 0)
            # Potential edges = |Ci| * |Cj|
            potential = len(communities[i]) * len(communities[j])
            ratio = cross / potential if potential > 0 else 0

            # Gap if ratio is very low
            if ratio < 0.05:  # less than 5% of possible cross-edges
                # Find top BC node in each community
                def top_bc_in(cid):
                    members = communities[cid]
                    best = max(members, key=lambda m: bc_scores.get(m, 0))
                    return best

                bridge_a = top_bc_in(i)
                bridge_b = top_bc_in(j)

                label_a = node_index[bridge_a]["label"] if bridge_a in node_index else bridge_a
                label_b = node_index[bridge_b]["label"] if bridge_b in node_index else bridge_b

                gaps.append({
                    "communityA": i,
                    "communityB": j,
                    "crossEdges": cross,
                    "bridgeNodeA": label_a,
                    "bridgeNodeB": label_b,
                    "question": f"What connects {label_a} to {label_b}?",
                })

    # Sort by fewest cross-edges (biggest gaps first), limit to 3
    gaps.sort(key=lambda g: g["crossEdges"])
    return gaps[:3]


def _compute_bias_label(modularity: float, communities: list[set], total_nodes: int) -> str:
    """Compute discourse bias label based on modularity and community balance."""
    if total_nodes == 0:
        return "Empty"

    top_community_share = max(len(c) for c in communities) / total_nodes if communities else 1.0

    if modularity > 0.65 and top_community_share < 0.5:
        return "Dispersed"
    elif modularity > 0.4:
        return "Diversified"
    elif modularity > 0.2:
        return "Focused"
    else:
        return "Biased"


def _generate_community_palette(n: int) -> list[str]:
    """Generate n visually distinct colors for dark backgrounds."""
    if n == 0:
        return []
    if n == 1:
        return ["#4ecdc4"]

    # Base hues distributed evenly, with saturation/lightness tuned for dark bg
    colors = []
    # Golden angle distribution for better separation
    golden = 137.508
    for i in range(n):
        hue = (i * golden) % 360
        sat = 0.65 + (i % 3) * 0.1  # 65-85% saturation
        lit = 0.55 + (i % 2) * 0.1  # 55-65% lightness
        colors.append(_hsl_to_hex(hue, sat, lit))
    return colors


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    """Convert HSL to hex color string."""
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2

    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    r = int((r + m) * 255)
    g = int((g + m) * 255)
    b = int((b + m) * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def _empty_analytics(nodes: list[dict], edges: list[dict]) -> dict:
    """Analytics payload for an empty graph."""
    return {
        "communities": [],
        "modularity": 0,
        "density": 0,
        "componentCount": 0,
        "avgDegree": 0,
        "biasLabel": "Empty",
        "gaps": [],
        "topBCNodes": [],
    }
