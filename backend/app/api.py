"""
Q-PORT FastAPI Application
===========================
All HTTP endpoints for the Q-PORT prototype.

Endpoints
---------
POST /scenario/generate         Generate + persist a scenario
GET  /scenario/{id}             Load a persisted scenario
GET  /scenario/{id}/network     Road network + current route polylines for Leaflet
POST /solve                     Run a solver (qpso | ortools | ga | all)
POST /event                     Inject a disruption event + run incremental re-opt
GET  /benchmark/{scenario_id}   Run all three solvers and return comparison table
GET  /scenarios                 List all persisted scenario IDs
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.events import handle_event
from app.models import (
    BenchmarkResult,
    Container,
    Edge,
    Event,
    EventResponse,
    NetworkResponse,
    Node,
    Scenario,
    Solution,
)
from app.network import get_node_coords, get_route_coords, load_network
from app.optimizers import genetic_algorithm as ga_mod
from app.optimizers import ortools_baseline as ortools_mod
from app.optimizers import qpso as qpso_mod
from app.scenario_generator import generate_scenario, list_scenarios, load_scenario

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Q-PORT API",
    description="Quantum-Inspired Dynamic Container Routing & Fleet Optimization",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Thread pool for CPU-bound solver work (keeps the event loop free)
_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# In-memory cache: scenario_id → last Solution per method
_solution_cache: dict[str, dict[str, Solution]] = {}


# ===========================================================================
# Request/Response models
# ===========================================================================

class GenerateRequest(BaseModel):
    size: Literal["small", "medium", "large"] = "small"
    seed: int = 42
    container_count: Optional[int] = None
    truck_count: Optional[int] = None


class SolveRequest(BaseModel):
    scenario_id: str
    method: Literal["qpso", "ortools", "ga", "all"] = "all"
    time_limit_s: Optional[int] = None


class EventRequest(BaseModel):
    scenario_id: str
    event: Event


# ===========================================================================
# Helpers
# ===========================================================================

TRUCK_COLORS = [
    "#4ade80", "#60a5fa", "#f472b6", "#fb923c", "#a78bfa",
    "#34d399", "#fbbf24", "#38bdf8", "#f87171", "#c084fc",
    "#86efac", "#93c5fd", "#f9a8d4", "#fdba74", "#c4b5fd",
    "#6ee7b7", "#fcd34d", "#7dd3fc", "#fca5a5", "#d8b4fe",
]


def _get_scenario_or_404(scenario_id: str) -> Scenario:
    scenario = load_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found.")
    return scenario


def _get_or_compute_ortools(scenario: Scenario, time_limit_s: Optional[int] = None) -> Solution:
    cache = _solution_cache.setdefault(scenario.id, {})
    if "ortools" not in cache:
        cache["ortools"] = ortools_mod.solve(scenario, time_limit_s=time_limit_s)
    return cache["ortools"]


def _solve_qpso(scenario: Scenario, ref: Solution) -> Solution:
    return qpso_mod.solve_full(scenario, ref)


def _solve_ga(scenario: Scenario, ref: Solution) -> Solution:
    return ga_mod.solve(scenario, ref)


# ===========================================================================
# Endpoints
# ===========================================================================

@app.get("/health")
async def health():
    return {"status": "ok", "service": "Q-PORT"}


@app.get("/scenarios")
async def list_all_scenarios():
    return {"scenario_ids": list_scenarios()}


@app.post("/scenario/generate", response_model=Scenario)
async def api_generate_scenario(req: GenerateRequest):
    loop = asyncio.get_event_loop()
    try:
        scenario = await loop.run_in_executor(
            _EXECUTOR,
            lambda: generate_scenario(
                size=req.size,
                seed=req.seed,
                container_count=req.container_count,
                truck_count=req.truck_count,
            ),
        )
    except Exception as exc:
        logger.exception("Scenario generation failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return scenario


@app.get("/scenario/{scenario_id}", response_model=Scenario)
async def api_get_scenario(scenario_id: str):
    return _get_scenario_or_404(scenario_id)


@app.get("/scenario/{scenario_id}/network", response_model=NetworkResponse)
async def api_get_network(scenario_id: str, method: str = "qpso"):
    scenario = _get_scenario_or_404(scenario_id)
    G, _ = load_network()
    coords = get_node_coords(G)

    # Build Node list for response
    nodes = [
        Node(
            id=n.id,
            lat=n.lat,
            lon=n.lon,
            kind=n.kind,
        )
        for n in scenario.nodes
    ]

    # Current best solution for the requested method
    cache = _solution_cache.get(scenario_id, {})
    solution = cache.get(method) or cache.get("ortools") or cache.get("qpso")

    routes = []
    if solution:
        truck_map = {t.id: t for t in scenario.trucks}
        container_map = {c.id: c for c in scenario.containers}

        for idx, assignment in enumerate(solution.assignments):
            if not assignment.container_sequence:
                continue
            truck = truck_map.get(assignment.truck_id)
            if truck is None:
                continue

            # Build node sequence: truck start → destinations in order
            node_seq = [truck.current_node] + [
                container_map[cid].destination_node
                for cid in assignment.container_sequence
                if cid in container_map
            ]
            polyline = get_route_coords(G, node_seq)
            routes.append({
                "truck_id": assignment.truck_id,
                "color": TRUCK_COLORS[idx % len(TRUCK_COLORS)],
                "polyline": [[lat, lon] for lat, lon in polyline],
            })

    return NetworkResponse(
        nodes=nodes,
        edges=scenario.edges,
        routes=routes,
    )


@app.post("/solve")
async def api_solve(req: SolveRequest):
    scenario = _get_scenario_or_404(req.scenario_id)
    loop = asyncio.get_event_loop()

    # OR-Tools is always computed first (used as fitness reference)
    ref = await loop.run_in_executor(
        _EXECUTOR,
        lambda: _get_or_compute_ortools(scenario, req.time_limit_s),
    )

    cache = _solution_cache.setdefault(req.scenario_id, {})
    cache["ortools"] = ref

    if req.method == "ortools":
        return ref

    if req.method == "qpso":
        sol = await loop.run_in_executor(_EXECUTOR, lambda: _solve_qpso(scenario, ref))
        cache["qpso"] = sol
        return sol

    if req.method == "ga":
        sol = await loop.run_in_executor(_EXECUTOR, lambda: _solve_ga(scenario, ref))
        cache["ga"] = sol
        return sol

    if req.method == "all":
        # Run QPSO and GA concurrently
        qpso_fut = loop.run_in_executor(_EXECUTOR, lambda: _solve_qpso(scenario, ref))
        ga_fut = loop.run_in_executor(_EXECUTOR, lambda: _solve_ga(scenario, ref))
        qpso_sol, ga_sol = await asyncio.gather(qpso_fut, ga_fut)
        cache["qpso"] = qpso_sol
        cache["ga"] = ga_sol
        return [ref, qpso_sol, ga_sol]

    raise HTTPException(status_code=422, detail=f"Unknown method: {req.method!r}")


@app.post("/event", response_model=EventResponse)
async def api_inject_event(req: EventRequest):
    scenario = _get_scenario_or_404(req.scenario_id)
    cache = _solution_cache.get(req.scenario_id, {})

    # Need a current solution to determine affected containers
    before_sol = cache.get("qpso") or cache.get("ortools") or cache.get("ga")
    if before_sol is None:
        raise HTTPException(
            status_code=422,
            detail="No solution exists for this scenario yet. Run /solve first.",
        )

    loop = asyncio.get_event_loop()

    # Handle event → get mutated scenario + affected IDs
    mutated_scenario, affected_ids = await loop.run_in_executor(
        _EXECUTOR,
        lambda: handle_event(req.event, scenario, before_sol),
    )

    # Get reference solution for mutated scenario (recompute with updated edges)
    ref = await loop.run_in_executor(
        _EXECUTOR,
        lambda: ortools_mod.solve(mutated_scenario),
    )

    # Incremental re-optimisation (warm-start)
    t_incr_start = time.perf_counter()
    after_sol = await loop.run_in_executor(
        _EXECUTOR,
        lambda: qpso_mod.solve_incremental(
            mutated_scenario, ref, before_sol, affected_ids
        ),
    )
    runtime_incremental = (time.perf_counter() - t_incr_start) * 1000.0

    # Full re-plan for comparison (background — this is the "proof" number)
    t_full_start = time.perf_counter()
    _ = await loop.run_in_executor(
        _EXECUTOR,
        lambda: qpso_mod.solve_full(mutated_scenario, ref, seed=99),
    )
    runtime_full = (time.perf_counter() - t_full_start) * 1000.0

    # Update cache with new scenario solution
    _solution_cache[req.scenario_id]["qpso"] = after_sol

    return EventResponse(
        before=before_sol,
        after=after_sol,
        affected_container_ids=affected_ids,
        runtime_ms_incremental=round(runtime_incremental, 1),
        runtime_ms_full_replan=round(runtime_full, 1),
    )


@app.get("/benchmark/{scenario_id}", response_model=BenchmarkResult)
async def api_benchmark(scenario_id: str, time_limit_s: Optional[int] = None):
    scenario = _get_scenario_or_404(scenario_id)
    loop = asyncio.get_event_loop()

    # OR-Tools first (reference)
    ref = await loop.run_in_executor(
        _EXECUTOR,
        lambda: ortools_mod.solve(scenario, time_limit_s=time_limit_s),
    )
    cache = _solution_cache.setdefault(scenario_id, {})
    cache["ortools"] = ref

    # QPSO and GA concurrently
    qpso_fut = loop.run_in_executor(_EXECUTOR, lambda: _solve_qpso(scenario, ref))
    ga_fut = loop.run_in_executor(_EXECUTOR, lambda: _solve_ga(scenario, ref))
    qpso_sol, ga_sol = await asyncio.gather(qpso_fut, ga_fut)
    cache["qpso"] = qpso_sol
    cache["ga"] = ga_sol

    return BenchmarkResult(
        scenario_id=scenario_id,
        results=[ref, qpso_sol, ga_sol],
    )
