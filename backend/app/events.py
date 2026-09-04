"""
Q-PORT Event Handlers
=====================
Handles real-time disruption events and produces:
  1. A mutated Scenario (with updated state)
  2. A list of affected_container_ids (for warm-start incremental re-opt)

Entry point: handle_event(event, scenario, current_solution) -> (scenario, [ids])

Supported events
----------------
traffic_change  : updates edge traffic multiplier; affected = containers
                  whose shortest path uses that edge
truck_breakdown : marks truck unavailable; affected = all its containers
new_container   : adds a container; affected = the new container
priority_change : changes a container's priority; affected = that container
deadline_change : changes a container's latest_time_min; affected = that container
"""
from __future__ import annotations

import copy
import logging
from typing import Literal

import networkx as nx

from app.models import Assignment, Container, Event, Scenario, Solution, Truck
from app.network import load_network

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Route extraction helper
# ---------------------------------------------------------------------------

def _containers_on_truck(truck_id: str, solution: Solution) -> list[str]:
    """Return container IDs currently assigned to a truck."""
    for a in solution.assignments:
        if a.truck_id == truck_id:
            return list(a.container_sequence)
    return []


def _containers_using_edge(
    from_node: str,
    to_node: str,
    scenario: Scenario,
    solution: Solution,
) -> list[str]:
    """
    Return IDs of containers whose current delivery route passes through
    the given directed edge.

    Approach: rebuild each truck's sequence of nodes and check for the edge.
    """
    G, _ = load_network()
    container_map = {c.id: c for c in scenario.containers}
    truck_map = {t.id: t for t in scenario.trucks}
    affected: list[str] = []

    for assignment in solution.assignments:
        truck = truck_map.get(assignment.truck_id)
        if truck is None:
            continue
        current = truck.current_node
        for cid in assignment.container_sequence:
            c = container_map.get(cid)
            if c is None:
                continue
            dest = c.destination_node
            try:
                path_nodes = nx.shortest_path(G, current, dest, weight="distance_km")
                # Check if the edge (from_node, to_node) is in the path
                for i in range(len(path_nodes) - 1):
                    if (str(path_nodes[i]) == from_node
                            and str(path_nodes[i + 1]) == to_node):
                        affected.append(cid)
                        break
            except (nx.NodeNotFound, nx.NetworkXNoPath, nx.NetworkXError):
                pass
            current = dest

    return list(set(affected))


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _handle_traffic_change(
    event: Event, scenario: Scenario, solution: Solution
) -> tuple[Scenario, list[str]]:
    """
    payload: {edge: [from_node, to_node], new_multiplier: float}
    """
    payload = event.payload
    edge_pair = payload.get("edge", [None, None])
    new_mult = float(payload.get("new_multiplier", 1.0))
    from_node, to_node = str(edge_pair[0]), str(edge_pair[1])

    mutated = scenario.model_copy(deep=True)
    updated = False
    for edge in mutated.edges:
        if edge.from_node == from_node and edge.to_node == to_node:
            edge.traffic_multiplier = new_mult
            updated = True

    if not updated:
        logger.warning(
            "traffic_change: edge (%s→%s) not found in scenario edges. "
            "Proceeding with path-based affected detection only.",
            from_node, to_node,
        )

    affected = _containers_using_edge(from_node, to_node, scenario, solution)
    logger.info(
        "traffic_change: edge %s→%s multiplier=%.2f  affected_containers=%d",
        from_node, to_node, new_mult, len(affected),
    )
    return mutated, affected


def _handle_truck_breakdown(
    event: Event, scenario: Scenario, solution: Solution
) -> tuple[Scenario, list[str]]:
    """
    payload: {truck_id: str}
    """
    truck_id = str(event.payload.get("truck_id", ""))
    mutated = scenario.model_copy(deep=True)

    found = False
    for truck in mutated.trucks:
        if truck.id == truck_id:
            truck.available = False
            found = True

    if not found:
        logger.warning("truck_breakdown: truck '%s' not found in scenario.", truck_id)

    affected = _containers_on_truck(truck_id, solution)
    logger.info(
        "truck_breakdown: truck=%s  affected_containers=%d",
        truck_id, len(affected),
    )
    return mutated, affected


def _handle_new_container(
    event: Event, scenario: Scenario, solution: Solution
) -> tuple[Scenario, list[str]]:
    """
    payload: a Container-compatible dict
    """
    raw = event.payload
    new_c = Container(**raw)
    mutated = scenario.model_copy(deep=True)
    mutated.containers.append(new_c)
    # Add destination node to nodes list if not present
    existing_ids = {n.id for n in mutated.nodes}
    if new_c.destination_node not in existing_ids:
        from app.network import get_node_coords
        G, _ = load_network()
        coords = get_node_coords(G)
        if new_c.destination_node in coords:
            lat, lon = coords[new_c.destination_node]
            from app.models import Node
            mutated.nodes.append(Node(
                id=new_c.destination_node, lat=lat, lon=lon, kind="destination"
            ))

    affected = [new_c.id]
    logger.info("new_container: added container '%s'", new_c.id)
    return mutated, affected


def _handle_priority_change(
    event: Event, scenario: Scenario, solution: Solution
) -> tuple[Scenario, list[str]]:
    """
    payload: {container_id: str, new_priority: int}
    """
    cid = str(event.payload.get("container_id", ""))
    new_priority = int(event.payload.get("new_priority", 1))
    mutated = scenario.model_copy(deep=True)

    for c in mutated.containers:
        if c.id == cid:
            c.priority = new_priority

    logger.info("priority_change: container=%s new_priority=%d", cid, new_priority)
    return mutated, [cid]


def _handle_deadline_change(
    event: Event, scenario: Scenario, solution: Solution
) -> tuple[Scenario, list[str]]:
    """
    payload: {container_id: str, new_latest_time_min: int}
    """
    cid = str(event.payload.get("container_id", ""))
    new_deadline = int(event.payload.get("new_latest_time_min", 480))
    mutated = scenario.model_copy(deep=True)

    for c in mutated.containers:
        if c.id == cid:
            c.latest_time_min = new_deadline

    logger.info(
        "deadline_change: container=%s new_latest_time_min=%d", cid, new_deadline
    )
    return mutated, [cid]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_HANDLERS = {
    "traffic_change": _handle_traffic_change,
    "truck_breakdown": _handle_truck_breakdown,
    "new_container": _handle_new_container,
    "priority_change": _handle_priority_change,
    "deadline_change": _handle_deadline_change,
}


def handle_event(
    event: Event,
    scenario: Scenario,
    current_solution: Solution,
) -> tuple[Scenario, list[str]]:
    """
    Dispatch an event to its handler.

    Returns
    -------
    (mutated_scenario, affected_container_ids)
        mutated_scenario       : a deep copy of scenario with state applied
        affected_container_ids : containers needing re-routing
    """
    handler = _HANDLERS.get(event.type)
    if handler is None:
        raise ValueError(f"Unknown event type: {event.type!r}")
    return handler(event, scenario, current_solution)
