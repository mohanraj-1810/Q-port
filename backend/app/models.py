"""
Q-PORT Data Models (Pydantic v2)
All shared data structures used across the backend.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class Node(BaseModel):
    id: str
    lat: float
    lon: float
    kind: Literal["icd", "destination", "waypoint"]


class Edge(BaseModel):
    from_node: str
    to_node: str
    distance_km: float
    base_time_min: float
    traffic_multiplier: float = 1.0  # mutable: simulates real-time congestion


class Container(BaseModel):
    id: str
    origin_node: str          # usually the ICD node
    destination_node: str
    weight_kg: float
    priority: int              # 1 (low) – 3 (urgent)
    earliest_time_min: int     # minutes from scenario start
    latest_time_min: int       # hard delivery deadline
    status: Literal["pending", "assigned", "delivered", "unassignable"] = "pending"


class Truck(BaseModel):
    id: str
    capacity_kg: float
    current_node: str
    available: bool = True
    speed_kmph: float = 35.0


class Event(BaseModel):
    type: Literal[
        "traffic_change",
        "truck_breakdown",
        "new_container",
        "priority_change",
        "deadline_change",
    ]
    timestamp_min: int
    payload: dict  # shape depends on type; validated inside event handlers


class Assignment(BaseModel):
    truck_id: str
    container_sequence: list[str]  # ordered container ids (delivery order)


class Solution(BaseModel):
    assignments: list[Assignment]
    total_distance_km: float
    total_time_min: float
    total_waiting_min: float
    total_cost: float
    constraint_violations: int
    fitness: float
    method: Literal["qpso", "ortools", "ga"]
    runtime_ms: float


class Scenario(BaseModel):
    """Full scenario persisted to disk. Loaded by all solvers."""
    id: str
    size: Literal["small", "medium", "large"]
    seed: int
    nodes: list[Node]
    edges: list[Edge]
    containers: list[Container]
    trucks: list[Truck]
    icd_node_id: str


class BenchmarkResult(BaseModel):
    scenario_id: str
    results: list[Solution]


class EventResponse(BaseModel):
    before: Solution
    after: Solution
    affected_container_ids: list[str]
    runtime_ms_incremental: float
    runtime_ms_full_replan: float


class NetworkResponse(BaseModel):
    nodes: list[Node]
    edges: list[Edge]
    routes: list[dict]  # [{truck_id, color, polyline: [[lat,lon], ...]}]
