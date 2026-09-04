"""
Q-PORT Road Network Loader
==========================
Two modes:
  1. Real OSM network via osmnx (Tughlakabad ICD, Delhi) — cached to disk
  2. Fallback deterministic synthetic grid — used automatically if OSM fails

The module always logs which mode was used so demo presenters know immediately.
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Optional, Tuple

import networkx as nx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[2]  # e:/sih/
_CACHE_PATH = _ROOT / "data" / "network_cache.graphml"

# ---------------------------------------------------------------------------
# OSM constants
# ---------------------------------------------------------------------------
TUGHLAKABAD_ICD = (28.5010, 77.2822)   # (lat, lon)
DEFAULT_RADIUS_KM = 15.0
AVG_SPEED_KMPH = 35.0                  # assumed average speed for time estimation


def _km_to_deg_lat(km: float) -> float:
    return km / 111.0


def _annotate_graph(G: nx.DiGraph) -> nx.DiGraph:
    """
    Annotate every edge with distance_km and base_time_min.
    Also ensures the graph is strongly connected so all nodes can reach each other.
    """
    if not nx.is_strongly_connected(G):
        sccs = list(nx.strongly_connected_components(G))
        if sccs:
            largest = max(sccs, key=len)
            G = G.subgraph(largest).copy()

    for u, v, data in G.edges(data=True):
        if "distance_km" not in data:
            length_m = data.get("length", 1000.0)  # OSM default: metres
            data["distance_km"] = length_m / 1000.0
        if "base_time_min" not in data:
            data["base_time_min"] = (data["distance_km"] / AVG_SPEED_KMPH) * 60.0
        data.setdefault("traffic_multiplier", 1.0)
    return G


def load_network(
    center: Tuple[float, float] = TUGHLAKABAD_ICD,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> Tuple[nx.DiGraph, bool]:
    """
    Load the real OSM drive network for the given centre/radius.

    Returns
    -------
    (graph, is_real)
        graph   — annotated NetworkX DiGraph
        is_real — True if OSM was used, False if fallback grid was used
    """
    # ---- Check offline override -------------------------------------------
    if os.environ.get("QPORT_OFFLINE") == "1":
        logger.info("QPORT_OFFLINE=1 set — using fallback synthetic grid network immediately.")
        return fallback_grid_network(), False

    # ---- try to load from disk cache first --------------------------------
    if _CACHE_PATH.exists():
        try:
            logger.info("Loading road network from disk cache: %s", _CACHE_PATH)
            G = nx.read_graphml(_CACHE_PATH)
            G = nx.DiGraph(G)
            G = _annotate_graph(G)
            logger.info(
                "✅ OSM network loaded from cache — %d nodes, %d edges",
                G.number_of_nodes(),
                G.number_of_edges(),
            )
            return G, True
        except Exception as exc:
            logger.warning("Cache load failed (%s); will try live OSM fetch.", exc)

    # ---- try live OSM fetch -----------------------------------------------
    try:
        import osmnx as ox  # noqa: PLC0415

        logger.info(
            "Fetching OSM drive network: centre=%s radius_km=%.1f …", center, radius_km
        )
        G = ox.graph_from_point(
            center,
            dist=int(radius_km * 1000),
            network_type="drive",
            simplify=True,
        )
        G = nx.DiGraph(G)   # convert MultiDiGraph → DiGraph (keep first parallel edge)
        G = _annotate_graph(G)

        # persist cache
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Clean list/dict attributes for GraphML writer compatibility
            G_copy = G.copy()
            for _, data in G_copy.nodes(data=True):
                for k, v in list(data.items()):
                    if isinstance(v, (list, dict, tuple, set)):
                        data[k] = str(v)
            for _, _, data in G_copy.edges(data=True):
                for k, v in list(data.items()):
                    if isinstance(v, (list, dict, tuple, set)):
                        data[k] = str(v)
            nx.write_graphml(G_copy, _CACHE_PATH)
            logger.info("OSM network cached to %s", _CACHE_PATH)
        except Exception as cache_exc:
            logger.warning("Could not cache graph: %s", cache_exc)

        logger.info(
            "✅ Real OSM network loaded — %d nodes, %d edges",
            G.number_of_nodes(),
            G.number_of_edges(),
        )
        return G, True

    except Exception as exc:
        logger.warning(
            "⚠️  OSM fetch failed (%s). Falling back to synthetic grid network.", exc
        )
        return fallback_grid_network(), False


def fallback_grid_network(
    rows: int = 8,
    cols: int = 8,
    spacing_km: float = 2.0,
    origin_lat: float = TUGHLAKABAD_ICD[0],
    origin_lon: float = TUGHLAKABAD_ICD[1],
) -> nx.DiGraph:
    """
    Deterministic synthetic grid graph.

    Nodes are labelled "r{row}_c{col}" with realistic lat/lon coordinates
    centred near Tughlakabad ICD so Leaflet renders them in roughly the right
    place even in fallback mode.
    """
    G = nx.DiGraph()

    deg_lat = spacing_km / 111.0
    deg_lon = spacing_km / (111.0 * math.cos(math.radians(origin_lat)))

    # Centre the grid on the ICD coordinates
    start_lat = origin_lat - (rows // 2) * deg_lat
    start_lon = origin_lon - (cols // 2) * deg_lon

    # Add nodes
    for r in range(rows):
        for c in range(cols):
            nid = f"r{r}_c{c}"
            G.add_node(
                nid,
                lat=start_lat + r * deg_lat,
                lon=start_lon + c * deg_lon,
                y=start_lat + r * deg_lat,
                x=start_lon + c * deg_lon,
            )

    # Add edges (bidirectional grid links)
    for r in range(rows):
        for c in range(cols):
            nid = f"r{r}_c{c}"
            # right neighbour
            if c + 1 < cols:
                nbr = f"r{r}_c{c+1}"
                G.add_edge(nid, nbr, distance_km=spacing_km,
                           base_time_min=(spacing_km / AVG_SPEED_KMPH) * 60.0,
                           traffic_multiplier=1.0)
                G.add_edge(nbr, nid, distance_km=spacing_km,
                           base_time_min=(spacing_km / AVG_SPEED_KMPH) * 60.0,
                           traffic_multiplier=1.0)
            # down neighbour
            if r + 1 < rows:
                nbr = f"r{r+1}_c{c}"
                G.add_edge(nid, nbr, distance_km=spacing_km,
                           base_time_min=(spacing_km / AVG_SPEED_KMPH) * 60.0,
                           traffic_multiplier=1.0)
                G.add_edge(nbr, nid, distance_km=spacing_km,
                           base_time_min=(spacing_km / AVG_SPEED_KMPH) * 60.0,
                           traffic_multiplier=1.0)

    logger.info(
        "✅ Fallback synthetic grid — %d nodes, %d edges (rows=%d cols=%d spacing=%.1fkm)",
        G.number_of_nodes(), G.number_of_edges(), rows, cols, spacing_km,
    )
    return G


def get_node_coords(G: nx.DiGraph) -> dict[str, Tuple[float, float]]:
    """Return {node_id: (lat, lon)} for all nodes."""
    coords: dict[str, Tuple[float, float]] = {}
    for nid, data in G.nodes(data=True):
        lat = data.get("y", data.get("lat", 0.0))
        lon = data.get("x", data.get("lon", 0.0))
        coords[str(nid)] = (lat, lon)
    return coords


def build_distance_matrix(
    G: nx.DiGraph, node_ids: list[str]
) -> dict[str, dict[str, float]]:
    """
    Precompute all-pairs shortest-path distances (km) between the given node IDs.
    Uses Dijkstra with distance_km as weight. Returns nested dict.
    Missing paths get a large sentinel (999999).
    """
    matrix: dict[str, dict[str, float]] = {}
    for src in node_ids:
        try:
            lengths = nx.single_source_dijkstra_path_length(
                G, src, weight="distance_km"
            )
            matrix[src] = {str(dst): lengths.get(dst, 999_999.0) for dst in node_ids}
        except (nx.NodeNotFound, nx.NetworkXError):
            matrix[src] = {str(dst): 999_999.0 for dst in node_ids}
    return matrix


def build_time_matrix(
    G: nx.DiGraph, node_ids: list[str]
) -> dict[str, dict[str, float]]:
    """
    Precompute all-pairs shortest-path travel times (minutes) using
    base_time_min * traffic_multiplier as the edge weight.
    """
    # Inject effective time weight onto each edge
    for u, v, data in G.edges(data=True):
        data["_eff_time"] = data.get("base_time_min", 1.0) * data.get(
            "traffic_multiplier", 1.0
        )

    matrix: dict[str, dict[str, float]] = {}
    for src in node_ids:
        try:
            lengths = nx.single_source_dijkstra_path_length(
                G, src, weight="_eff_time"
            )
            matrix[src] = {str(dst): lengths.get(dst, 999_999.0) for dst in node_ids}
        except (nx.NodeNotFound, nx.NetworkXError):
            matrix[src] = {str(dst): 999_999.0 for dst in node_ids}
    return matrix


def get_route_coords(
    G: nx.DiGraph,
    node_sequence: list[str],
) -> list[Tuple[float, float]]:
    """
    Given an ordered list of node ids, expand to a list of (lat, lon) waypoints
    following actual shortest-path geometry for Leaflet rendering.
    """
    coords_map = get_node_coords(G)
    result: list[Tuple[float, float]] = []
    for i in range(len(node_sequence) - 1):
        src, dst = node_sequence[i], node_sequence[i + 1]
        try:
            path = nx.shortest_path(G, src, dst, weight="distance_km")
        except (nx.NodeNotFound, nx.NetworkXError, nx.NetworkXNoPath):
            path = [src, dst]
        for nid in path:
            pt = coords_map.get(str(nid))
            if pt:
                result.append(pt)
    return result
