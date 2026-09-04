"""
Q-PORT OR-Tools CVRPTW Baseline
================================
Solves the Container Vehicle Routing Problem with Time Windows and Capacity
constraints using Google OR-Tools' CP-SAT / VRP routing module.

This solver's output serves as:
  1. A quality baseline for benchmarking QPSO and GA.
  2. The reference solution for min-max normalising the shared fitness function.

Usage
-----
    from app.optimizers.ortools_baseline import solve as ortools_solve
    solution = ortools_solve(scenario)
"""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Optional

from app.models import Assignment, Container, Scenario, Solution, Truck
from app.network import build_distance_matrix, build_time_matrix, load_network

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OR-Tools import (optional — graceful error if not installed)
# ---------------------------------------------------------------------------
try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    _ORTOOLS_AVAILABLE = True
except ImportError:
    _ORTOOLS_AVAILABLE = False
    logger.warning("ortools not available — OR-Tools baseline will raise on use.")

# ---------------------------------------------------------------------------
# Cost constants (same as fitness.py — single source of truth)
# ---------------------------------------------------------------------------
FIXED_COST_PER_TRUCK = 2000.0   # INR placeholder — clearly not production values
PER_KM_COST = 15.0               # INR/km placeholder

# ---------------------------------------------------------------------------
# Time limits per scenario size (seconds)
# ---------------------------------------------------------------------------
_TIME_LIMITS = {"small": 15, "medium": 45, "large": 120}

# ---------------------------------------------------------------------------
# Matrix cache
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[3]
_MATRIX_CACHE_DIR = _ROOT / "data" / "matrix_cache"


def _cache_key(scenario: Scenario) -> Path:
    _MATRIX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _MATRIX_CACHE_DIR / f"{scenario.id}_matrix.json"


def _load_or_build_matrices(
    scenario: Scenario,
) -> tuple[list[str], list[list[int]], list[list[int]]]:
    """
    Build (or load from cache) integer distance and time matrices for OR-Tools.

    Returns
    -------
    node_ids  : ordered list of node ids used (index → node_id)
    dist_mat  : integer distance matrix (metres * 1000, to avoid float)
    time_mat  : integer time matrix (seconds * 10, to avoid float)
    """
    # Collect all relevant nodes: ICD + all container destinations + truck starts
    node_set: set[str] = {scenario.icd_node_id}
    for c in scenario.containers:
        node_set.add(c.origin_node)
        node_set.add(c.destination_node)
    for t in scenario.trucks:
        node_set.add(t.current_node)

    node_ids = sorted(node_set)
    cache_path = _cache_key(scenario)

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if set(cached.get("node_ids", [])) == node_set:
                logger.info("Loading valid matrix cache from %s", cache_path)
                return cached["node_ids"], cached["dist_mat"], cached["time_mat"]
            logger.warning("Matrix cache node mismatch for '%s' — rebuilding.", scenario.id)
        except Exception as exc:
            logger.warning("Matrix cache read failed (%s) — rebuilding.", exc)

    logger.info("Building shortest-path matrices for scenario '%s' …", scenario.id)

    # Build the road graph
    G, _ = load_network()

    dist_float = build_distance_matrix(G, node_ids)   # km
    time_float = build_time_matrix(G, node_ids)        # minutes

    # Scale to integers for OR-Tools (distances in metres×10, time in seconds×10)
    scale_d = 10_000  # km → metres → ×10
    scale_t = 600     # min → seconds × 10

    def _to_int_mat(float_mat: dict[str, dict[str, float]], scale: int) -> list[list[int]]:
        return [
            [int(min(float_mat[src].get(dst, 999_999.0) * scale, 2_000_000_000))
             for dst in node_ids]
            for src in node_ids
        ]

    dist_mat = _to_int_mat(dist_float, scale_d)
    time_mat = _to_int_mat(time_float, scale_t)

    cache_path.write_text(
        json.dumps({"node_ids": node_ids, "dist_mat": dist_mat, "time_mat": time_mat}),
        encoding="utf-8",
    )
    logger.info("Matrix cache saved to %s", cache_path)
    return node_ids, dist_mat, time_mat


def _solution_from_routes(
    manager,
    routing,
    ortools_solution,
    node_ids: list[str],
    scenario: Scenario,
    dist_mat: list[list[int]],
    time_mat: list[list[int]],
    runtime_ms: float,
    scale_d: int = 10_000,
    scale_t: int = 600,
) -> Solution:
    """Extract Q-PORT Solution from an OR-Tools routing solution."""
    node_idx = {nid: i for i, nid in enumerate(node_ids)}
    dest_to_container: dict[str, str] = {c.destination_node: c.id for c in scenario.containers}
    truck_id_list = [t.id for t in scenario.trucks]

    assignments: list[Assignment] = []
    total_dist = 0.0
    total_time = 0.0
    trucks_used = 0

    for vehicle_idx in range(len(scenario.trucks)):
        index = routing.Start(vehicle_idx)
        route_containers: list[str] = []
        route_dist = 0.0
        route_time = 0.0

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            nid = node_ids[node]
            if nid in dest_to_container:
                route_containers.append(dest_to_container[nid])

            next_index = ortools_solution.Value(routing.NextVar(index))
            next_node = manager.IndexToNode(next_index)
            route_dist += dist_mat[node][next_node] / scale_d
            route_time += time_mat[node][next_node] / scale_t
            index = next_index

        if route_containers:
            assignments.append(Assignment(
                truck_id=truck_id_list[vehicle_idx],
                container_sequence=route_containers,
            ))
            total_dist += route_dist
            total_time += route_time
            trucks_used += 1

    # Mark all assigned containers
    assigned_ids = {cid for a in assignments for cid in a.container_sequence}
    unassigned_count = len([c for c in scenario.containers if c.id not in assigned_ids])

    total_cost = FIXED_COST_PER_TRUCK * trucks_used + PER_KM_COST * total_dist

    return Solution(
        assignments=assignments,
        total_distance_km=round(total_dist, 3),
        total_time_min=round(total_time, 3),
        total_waiting_min=0.0,   # OR-Tools slack handled internally
        total_cost=round(total_cost, 2),
        constraint_violations=unassigned_count,
        fitness=0.0,  # filled in by caller after normalization
        method="ortools",
        runtime_ms=round(runtime_ms, 1),
    )


def solve(scenario: Scenario, time_limit_s: int | None = None) -> Solution:
    """
    Run the OR-Tools CVRPTW solver on the given scenario.

    Parameters
    ----------
    scenario      : fully populated Scenario object
    time_limit_s  : override solver time limit (seconds)

    Returns
    -------
    Solution with method='ortools'
    """
    if not _ORTOOLS_AVAILABLE:
        raise RuntimeError("ortools package not installed. Run: pip install ortools")

    if time_limit_s is None:
        time_limit_s = _TIME_LIMITS.get(scenario.size, 30)

    t0 = time.perf_counter()

    # ---- Build matrices ---------------------------------------------------
    node_ids, dist_mat, time_mat = _load_or_build_matrices(scenario)
    node_idx = {nid: i for i, nid in enumerate(node_ids)}

    n_vehicles = len(scenario.trucks)
    depot_idx = node_idx.get(scenario.icd_node_id, 0)

    # ---- OR-Tools manager + model -----------------------------------------
    manager = pywrapcp.RoutingIndexManager(len(node_ids), n_vehicles, depot_idx)
    routing = pywrapcp.RoutingModel(manager)

    # ---- Distance callback ------------------------------------------------
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return dist_mat[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # ---- Time callback ----------------------------------------------------
    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return time_mat[from_node][to_node]

    time_callback_index = routing.RegisterTransitCallback(time_callback)

    # ---- Capacity dimension -----------------------------------------------
    scale_cap = 1  # weight in kg — no scaling needed
    # Map each node to demand (containers have demand at their destination node)
    node_demand: dict[int, int] = {i: 0 for i in range(len(node_ids))}
    for c in scenario.containers:
        dest_i = node_idx.get(c.destination_node)
        if dest_i is not None:
            node_demand[dest_i] = node_demand.get(dest_i, 0) + int(c.weight_kg)

    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return node_demand.get(from_node, 0)

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    vehicle_capacities = [int(t.capacity_kg) for t in scenario.trucks]

    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,                    # null capacity slack
        vehicle_capacities,   # maximum capacities
        True,                 # start cumul to zero
        "Capacity",
    )

    # ---- Time window dimension --------------------------------------------
    # Scale: time_mat is in (minutes * 600 / 60) = ×10 seconds
    # We keep time windows in the same unit (×10 seconds)
    scale_t = 600  # min → ×10 seconds

    routing.AddDimension(
        time_callback_index,
        30 * scale_t,          # 30-min slack (allows waiting)
        500 * scale_t,         # max time per vehicle
        False,                 # don't force start cumul to zero
        "Time",
    )
    time_dimension = routing.GetDimensionOrDie("Time")

    for c in scenario.containers:
        dest_i = node_idx.get(c.destination_node)
        if dest_i is None:
            continue
        index = manager.NodeToIndex(dest_i)
        time_dimension.CumulVar(index).SetRange(
            int(c.earliest_time_min * scale_t),
            int(c.latest_time_min * scale_t),
        )

    # Allow dropping nodes with a large penalty (better than infeasible)
    for c in scenario.containers:
        dest_i = node_idx.get(c.destination_node)
        if dest_i is None:
            continue
        index = manager.NodeToIndex(dest_i)
        routing.AddDisjunction([index], 100_000)

    # ---- Search parameters -----------------------------------------------
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.seconds = time_limit_s
    search_params.log_search = False

    # ---- Solve -----------------------------------------------------------
    logger.info(
        "OR-Tools solving scenario '%s' (time_limit=%ds) …", scenario.id, time_limit_s
    )
    ortools_sol = routing.SolveWithParameters(search_params)
    runtime_ms = (time.perf_counter() - t0) * 1000.0

    if ortools_sol is None or routing.status() == 0:
        logger.warning("OR-Tools found no solution within time limit.")
        # Return an empty (all-penalty) solution rather than crashing
        return Solution(
            assignments=[],
            total_distance_km=0.0,
            total_time_min=0.0,
            total_waiting_min=0.0,
            total_cost=0.0,
            constraint_violations=len(scenario.containers),
            fitness=1.0,
            method="ortools",
            runtime_ms=round(runtime_ms, 1),
        )

    sol = _solution_from_routes(
        manager, routing, ortools_sol, node_ids, scenario,
        dist_mat, time_mat, runtime_ms,
    )
    logger.info(
        "✅ OR-Tools done in %.0fms — dist=%.1fkm violations=%d",
        runtime_ms, sol.total_distance_km, sol.constraint_violations,
    )
    return sol
