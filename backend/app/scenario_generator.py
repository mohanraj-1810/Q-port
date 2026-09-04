"""
Q-PORT Scenario Generator
=========================
Generates reproducible small / medium / large routing scenarios and persists
them as JSON under data/sample_scenarios/{scenario_id}.json.

All randomness is seeded so the same (size, seed) pair always produces the
same scenario — important for benchmark reproducibility during judging.
"""
from __future__ import annotations

import json
import logging
import random
import uuid
from pathlib import Path
from typing import Literal

import networkx as nx

from app.models import Container, Node, Scenario, Truck
from app.network import get_node_coords, load_network

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_SCENARIOS_DIR = _ROOT / "data" / "sample_scenarios"

# ---------------------------------------------------------------------------
# Size specs
# ---------------------------------------------------------------------------
_SPECS = {
    "small":  {"containers": 20,  "trucks": 5},
    "medium": {"containers": 100, "trucks": 20},
    "large":  {"containers": 300, "trucks": 50},
}

# Truck colour palette for frontend (one colour per truck index)
_TRUCK_COLORS = [
    "#4ade80", "#60a5fa", "#f472b6", "#fb923c", "#a78bfa",
    "#34d399", "#fbbf24", "#38bdf8", "#f87171", "#c084fc",
    "#86efac", "#93c5fd", "#f9a8d4", "#fdba74", "#c4b5fd",
    "#6ee7b7", "#fcd34d", "#7dd3fc", "#fca5a5", "#d8b4fe",
]


def _pick_nodes(
    G: nx.DiGraph,
    rng: random.Random,
    n: int,
    exclude: set[str] | None = None,
) -> list[str]:
    """Pick n random nodes from the graph (excluding a set if given)."""
    candidates = [str(nid) for nid in G.nodes() if str(nid) not in (exclude or set())]
    return rng.sample(candidates, min(n, len(candidates)))


def generate_scenario(
    size: Literal["small", "medium", "large"] = "small",
    seed: int = 42,
    container_count: int | None = None,  # override for large tier
    truck_count: int | None = None,
) -> Scenario:
    """
    Generate a scenario and persist it to disk. Returns the Scenario object.

    Parameters
    ----------
    size            : 'small' | 'medium' | 'large'
    seed            : random seed for full reproducibility
    container_count : override for large tier (250–500)
    truck_count     : override for large tier (50+)
    """
    rng = random.Random(seed)
    spec = _SPECS[size].copy()
    if container_count is not None:
        spec["containers"] = container_count
    if truck_count is not None:
        spec["trucks"] = truck_count

    n_containers = spec["containers"]
    n_trucks = spec["trucks"]

    logger.info(
        "Generating scenario: size=%s seed=%d containers=%d trucks=%d",
        size, seed, n_containers, n_trucks,
    )

    # ---- Load network (OSM or fallback) ------------------------------------
    G, is_real = load_network()
    coords = get_node_coords(G)
    all_node_ids = list(coords.keys())

    if len(all_node_ids) < n_containers + 2:
        raise ValueError(
            f"Network has only {len(all_node_ids)} nodes but need "
            f"at least {n_containers + 2}."
        )

    # ---- Pick ICD node (closest to Tughlakabad coords if OSM, else centre) -
    if is_real:
        # find node closest to the ICD coordinates
        target_lat, target_lon = 28.5010, 77.2822
        icd_node = min(
            all_node_ids,
            key=lambda nid: (
                (coords[nid][0] - target_lat) ** 2
                + (coords[nid][1] - target_lon) ** 2
            ),
        )
    else:
        # for the synthetic grid, use the centre node
        icd_node = f"r3_c3"
        if icd_node not in coords:
            icd_node = all_node_ids[len(all_node_ids) // 2]

    # ---- Build Node list ---------------------------------------------------
    nodes: list[Node] = []
    for nid in all_node_ids:
        lat, lon = coords[nid]
        kind = "icd" if nid == icd_node else "destination"
        nodes.append(Node(id=nid, lat=lat, lon=lon, kind=kind))

    # ---- Pick destination nodes (exclude ICD) ------------------------------
    dest_pool = _pick_nodes(G, rng, n_containers, exclude={icd_node})

    # ---- Generate containers -----------------------------------------------
    containers: list[Container] = []
    for i in range(n_containers):
        dest = dest_pool[i % len(dest_pool)]
        earliest = 0
        latest = rng.randint(120, 480)
        containers.append(
            Container(
                id=f"C{i:04d}",
                origin_node=icd_node,
                destination_node=dest,
                weight_kg=round(rng.uniform(500.0, 4000.0), 1),
                priority=rng.choices([1, 2, 3], weights=[0.5, 0.3, 0.2])[0],
                earliest_time_min=earliest,
                latest_time_min=latest,
                status="pending",
            )
        )

    # ---- Generate trucks ---------------------------------------------------
    trucks: list[Truck] = []
    for i in range(n_trucks):
        trucks.append(
            Truck(
                id=f"T{i:03d}",
                capacity_kg=round(rng.uniform(20000.0, 40000.0), 1),
                current_node=icd_node,
                available=True,
                speed_kmph=35.0,
            )
        )

    # ---- Build edges list from graph ---------------------------------------
    from app.models import Edge  # local import to avoid circular at module level
    edges: list[Edge] = []
    for u, v, data in G.edges(data=True):
        edges.append(
            Edge(
                from_node=str(u),
                to_node=str(v),
                distance_km=round(data.get("distance_km", 1.0), 4),
                base_time_min=round(data.get("base_time_min", 1.0), 4),
                traffic_multiplier=data.get("traffic_multiplier", 1.0),
            )
        )

    # ---- Assemble and persist scenario ------------------------------------
    scenario_id = f"{size}_seed{seed}"
    scenario = Scenario(
        id=scenario_id,
        size=size,
        seed=seed,
        nodes=nodes,
        edges=edges,
        containers=containers,
        trucks=trucks,
        icd_node_id=icd_node,
    )

    _persist_scenario(scenario)
    logger.info("✅ Scenario '%s' generated and persisted.", scenario_id)
    return scenario


def _persist_scenario(scenario: Scenario) -> None:
    _SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    path = _SCENARIOS_DIR / f"{scenario.id}.json"
    path.write_text(scenario.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Scenario saved to %s", path)


def load_scenario(scenario_id: str) -> Scenario | None:
    """Load a previously generated scenario from disk. Returns None if not found."""
    path = _SCENARIOS_DIR / f"{scenario_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Scenario(**data)


def list_scenarios() -> list[str]:
    """Return all persisted scenario IDs."""
    _SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    return [p.stem for p in _SCENARIOS_DIR.glob("*.json")]
