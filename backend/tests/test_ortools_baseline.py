"""
Tests: OR-Tools baseline on a small fixed scenario.
"""
import pytest

from app.optimizers.ortools_baseline import solve as ortools_solve
from app.scenario_generator import generate_scenario


def test_ortools_small_zero_violations():
    """OR-Tools must return a feasible solution (0 violations) for a small scenario."""
    scenario = generate_scenario(size="small", seed=42)
    sol = ortools_solve(scenario, time_limit_s=30)

    assert sol.constraint_violations == 0, (
        f"Expected 0 constraint violations, got {sol.constraint_violations}"
    )


def test_ortools_all_containers_assigned():
    """Every container must appear in exactly one truck's sequence."""
    scenario = generate_scenario(size="small", seed=42)
    sol = ortools_solve(scenario, time_limit_s=30)

    assigned = [cid for a in sol.assignments for cid in a.container_sequence]
    expected_ids = {c.id for c in scenario.containers}
    assigned_set = set(assigned)

    assert assigned_set == expected_ids, (
        f"Missing containers: {expected_ids - assigned_set}\n"
        f"Extra: {assigned_set - expected_ids}"
    )
    assert len(assigned) == len(scenario.containers), "Duplicate assignments detected"


def test_ortools_returns_solution_model():
    """OR-Tools result must be a valid Solution pydantic model."""
    scenario = generate_scenario(size="small", seed=1)
    sol = ortools_solve(scenario, time_limit_s=15)

    assert sol.method == "ortools"
    assert sol.runtime_ms >= 0
    assert sol.total_distance_km >= 0
    assert sol.total_time_min >= 0
    assert sol.total_cost >= 0


def test_ortools_valid_truck_ids():
    """All truck IDs in the solution must exist in the scenario."""
    scenario = generate_scenario(size="small", seed=3)
    sol = ortools_solve(scenario, time_limit_s=15)

    valid_ids = {t.id for t in scenario.trucks}
    for a in sol.assignments:
        assert a.truck_id in valid_ids, f"Unknown truck id: {a.truck_id!r}"
