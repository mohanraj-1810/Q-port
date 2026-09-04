"""
Tests: Fitness function correctness.
"""
import pytest

from app.models import Assignment, Solution
from app.optimizers.fitness import (
    VIOLATION_PENALTY,
    _normalise,
    compute_fitness,
    count_violations,
)
from app.scenario_generator import generate_scenario


def _make_sol(**kwargs) -> Solution:
    defaults = dict(
        assignments=[],
        total_distance_km=100.0,
        total_time_min=200.0,
        total_waiting_min=10.0,
        total_cost=5000.0,
        constraint_violations=0,
        fitness=0.0,
        method="qpso",
        runtime_ms=0.0,
    )
    defaults.update(kwargs)
    return Solution(**defaults)


def _ref_sol() -> Solution:
    return _make_sol(
        total_distance_km=200.0,
        total_time_min=400.0,
        total_waiting_min=20.0,
        total_cost=8000.0,
    )


# ---------------------------------------------------------------------------
# 1. _normalise stays in [0, 1] for a wide range of inputs
# ---------------------------------------------------------------------------

def test_normalise_in_bounds():
    reference = 100.0
    for value in [-50, 0, 50, 100, 150, 200, 1000]:
        result = _normalise(float(value), reference)
        assert 0.0 <= result <= 1.0, f"_normalise({value}, {reference}) = {result} out of [0,1]"


def test_normalise_zero_reference():
    # Should not crash; return 0.0 when reference is 0
    result = _normalise(10.0, 0.0)
    assert result == 0.0


def test_normalise_value_at_ceiling():
    # value = reference * 1.5 should give exactly 1.0
    ref = 100.0
    result = _normalise(ref * 1.5, ref)
    assert result == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 2. Fitness components are in a sensible range for feasible solution
# ---------------------------------------------------------------------------

def test_feasible_fitness_is_finite_and_positive():
    ref = _ref_sol()
    sol = _make_sol(
        total_distance_km=150.0,
        total_time_min=300.0,
        total_waiting_min=15.0,
        total_cost=6000.0,
        constraint_violations=0,
    )
    f = compute_fitness(sol, ref)
    assert 0.0 <= f < VIOLATION_PENALTY, (
        f"Feasible fitness {f} should be < VIOLATION_PENALTY={VIOLATION_PENALTY}"
    )


# ---------------------------------------------------------------------------
# 3. A capacity-violating solution ALWAYS scores worse than the feasible one
# ---------------------------------------------------------------------------

def test_violation_dominates_fitness():
    ref = _ref_sol()
    feasible = _make_sol(
        total_distance_km=1.0,   # best possible metrics
        total_time_min=1.0,
        total_waiting_min=0.0,
        total_cost=1.0,
        constraint_violations=0,
    )
    infeasible = _make_sol(
        total_distance_km=1.0,   # same great metrics
        total_time_min=1.0,
        total_waiting_min=0.0,
        total_cost=1.0,
        constraint_violations=1,  # one violation
    )
    f_feas = compute_fitness(feasible, ref)
    f_inf = compute_fitness(infeasible, ref)
    assert f_inf > f_feas, (
        f"Infeasible fitness ({f_inf:.4f}) should exceed feasible ({f_feas:.4f})"
    )


# ---------------------------------------------------------------------------
# 4. count_violations: capacity exceeded is detected
# ---------------------------------------------------------------------------

def test_count_violations_capacity():
    scenario = generate_scenario(size="small", seed=42)
    # Build a solution that overloads the first truck (sum weight > capacity)
    truck = scenario.trucks[0]
    # Assign all containers to one truck regardless of capacity
    all_cids = [c.id for c in scenario.containers]
    sol = _make_sol(
        assignments=[Assignment(truck_id=truck.id, container_sequence=all_cids)],
        constraint_violations=0,
    )
    violations = count_violations(sol, scenario)
    total_weight = sum(c.weight_kg for c in scenario.containers)
    if total_weight > truck.capacity_kg:
        assert violations >= 1, "Expected at least 1 capacity violation"


# ---------------------------------------------------------------------------
# 5. count_violations: unassigned containers are counted
# ---------------------------------------------------------------------------

def test_count_violations_unassigned():
    scenario = generate_scenario(size="small", seed=5)
    # Solution with no assignments at all
    sol = _make_sol(assignments=[])
    violations = count_violations(sol, scenario)
    assert violations == len(scenario.containers), (
        "All containers unassigned → violations should equal container count"
    )
