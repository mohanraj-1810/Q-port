"""
Tests: Event handlers — correct mutation + affected container detection.
"""
import pytest

from app.events import handle_event
from app.models import Container, Event
from app.optimizers.ortools_baseline import solve as ortools_solve
from app.scenario_generator import generate_scenario


def _base_scenario():
    return generate_scenario(size="small", seed=42)


def _base_solution(scenario):
    return ortools_solve(scenario, time_limit_s=15)


# ---------------------------------------------------------------------------
# 1. truck_breakdown: affected containers match the truck's assignment exactly
# ---------------------------------------------------------------------------

def test_truck_breakdown_affected_containers():
    scenario = _base_scenario()
    solution = _base_solution(scenario)

    # Pick a truck that has containers assigned
    truck_with_containers = None
    expected_affected = []
    for a in solution.assignments:
        if a.container_sequence:
            truck_with_containers = a.truck_id
            expected_affected = list(a.container_sequence)
            break

    if truck_with_containers is None:
        pytest.skip("No truck has containers assigned — solver produced empty routes")

    event = Event(
        type="truck_breakdown",
        timestamp_min=30,
        payload={"truck_id": truck_with_containers},
    )
    mutated, affected = handle_event(event, scenario, solution)

    assert set(affected) == set(expected_affected), (
        f"Expected affected={set(expected_affected)}, got={set(affected)}"
    )


def test_truck_breakdown_marks_truck_unavailable():
    scenario = _base_scenario()
    solution = _base_solution(scenario)

    target_truck = scenario.trucks[0].id
    event = Event(
        type="truck_breakdown",
        timestamp_min=10,
        payload={"truck_id": target_truck},
    )
    mutated, affected = handle_event(event, scenario, solution)

    broken = next((t for t in mutated.trucks if t.id == target_truck), None)
    assert broken is not None
    assert broken.available is False, "Broken-down truck should be marked unavailable"


def test_truck_breakdown_other_trucks_unchanged():
    scenario = _base_scenario()
    solution = _base_solution(scenario)

    target_truck = scenario.trucks[0].id
    event = Event(
        type="truck_breakdown",
        timestamp_min=10,
        payload={"truck_id": target_truck},
    )
    mutated, affected = handle_event(event, scenario, solution)

    # Containers on OTHER trucks must NOT appear in affected
    other_containers = set()
    for a in solution.assignments:
        if a.truck_id != target_truck:
            other_containers.update(a.container_sequence)

    overlap = set(affected) & other_containers
    assert not overlap, (
        f"Containers from other trucks incorrectly marked as affected: {overlap}"
    )


# ---------------------------------------------------------------------------
# 2. priority_change: only the target container is affected
# ---------------------------------------------------------------------------

def test_priority_change_affected():
    scenario = _base_scenario()
    solution = _base_solution(scenario)

    target_cid = scenario.containers[0].id
    event = Event(
        type="priority_change",
        timestamp_min=5,
        payload={"container_id": target_cid, "new_priority": 3},
    )
    mutated, affected = handle_event(event, scenario, solution)

    assert affected == [target_cid]
    changed = next((c for c in mutated.containers if c.id == target_cid), None)
    assert changed is not None
    assert changed.priority == 3


# ---------------------------------------------------------------------------
# 3. deadline_change: only the target container is affected
# ---------------------------------------------------------------------------

def test_deadline_change_affected():
    scenario = _base_scenario()
    solution = _base_solution(scenario)

    target_cid = scenario.containers[1].id
    new_deadline = 60
    event = Event(
        type="deadline_change",
        timestamp_min=0,
        payload={"container_id": target_cid, "new_latest_time_min": new_deadline},
    )
    mutated, affected = handle_event(event, scenario, solution)

    assert affected == [target_cid]
    changed = next((c for c in mutated.containers if c.id == target_cid), None)
    assert changed.latest_time_min == new_deadline


# ---------------------------------------------------------------------------
# 4. new_container: affected is the new container
# ---------------------------------------------------------------------------

def test_new_container_affected():
    scenario = _base_scenario()
    solution = _base_solution(scenario)

    new_c = Container(
        id="C_NEW",
        origin_node=scenario.icd_node_id,
        destination_node=scenario.containers[0].destination_node,
        weight_kg=5000.0,
        priority=2,
        earliest_time_min=0,
        latest_time_min=300,
        status="pending",
    )
    event = Event(
        type="new_container",
        timestamp_min=20,
        payload=new_c.model_dump(),
    )
    mutated, affected = handle_event(event, scenario, solution)

    assert "C_NEW" in affected
    assert any(c.id == "C_NEW" for c in mutated.containers)
