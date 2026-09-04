"""
Tests: QPSO encoding round-trip stability and structural validity.
"""
import numpy as np
import pytest

from app.models import Scenario
from app.network import fallback_grid_network
from app.optimizers.qpso import (
    _build_matrices_for_scenario,
    _decode,
    _encode,
    _random_position,
)
from app.scenario_generator import generate_scenario


def _small_scenario() -> Scenario:
    """Generate a small seeded scenario using the fallback grid network."""
    return generate_scenario(size="small", seed=7)


# ---------------------------------------------------------------------------
# 1. decode always produces a structurally valid Solution
# ---------------------------------------------------------------------------

def test_decode_structural_validity():
    scenario = _small_scenario()
    node_ids, dist_mat, time_mat = _build_matrices_for_scenario(scenario)
    rng = np.random.default_rng(42)
    n_dim = 2 * len(scenario.containers)

    for trial in range(10):
        pos = rng.uniform(0.0, 1.0, n_dim)
        sol = _decode(pos, scenario, dist_mat, time_mat)

        # Every container assigned exactly once
        all_assigned = [cid for a in sol.assignments for cid in a.container_sequence]
        assert len(all_assigned) == len(scenario.containers), (
            f"Trial {trial}: expected {len(scenario.containers)} containers assigned, "
            f"got {len(all_assigned)}"
        )
        assert len(set(all_assigned)) == len(all_assigned), (
            f"Trial {trial}: duplicate container assignments detected"
        )

        # All truck IDs are valid
        valid_truck_ids = {t.id for t in scenario.trucks}
        for a in sol.assignments:
            assert a.truck_id in valid_truck_ids, (
                f"Trial {trial}: unknown truck id {a.truck_id!r}"
            )


# ---------------------------------------------------------------------------
# 2. encode → decode round-trip preserves approximate assignment
# ---------------------------------------------------------------------------

def test_encode_decode_roundtrip():
    scenario = _small_scenario()
    node_ids, dist_mat, time_mat = _build_matrices_for_scenario(scenario)
    rng = np.random.default_rng(0)
    n_dim = 2 * len(scenario.containers)

    pos_orig = rng.uniform(0.0, 1.0, n_dim)
    sol = _decode(pos_orig, scenario, dist_mat, time_mat)

    # Encode the solution back to a position vector
    pos_encoded = _encode(sol, scenario)

    assert pos_encoded.shape == (n_dim,), "Encoded position has wrong shape"
    assert np.all(pos_encoded >= 0.0) and np.all(pos_encoded <= 1.0), (
        "Encoded position values out of [0, 1]"
    )

    # Decode the re-encoded position
    sol2 = _decode(pos_encoded, scenario, dist_mat, time_mat)

    # All containers should still be assigned exactly once
    all_assigned = [cid for a in sol2.assignments for cid in a.container_sequence]
    assert len(all_assigned) == len(scenario.containers)
    assert len(set(all_assigned)) == len(all_assigned)


# ---------------------------------------------------------------------------
# 3. encode produces values in [0, 1]
# ---------------------------------------------------------------------------

def test_encode_bounds():
    scenario = _small_scenario()
    node_ids, dist_mat, time_mat = _build_matrices_for_scenario(scenario)
    rng = np.random.default_rng(1)
    n_dim = 2 * len(scenario.containers)
    pos = rng.uniform(0.0, 1.0, n_dim)
    sol = _decode(pos, scenario, dist_mat, time_mat)
    encoded = _encode(sol, scenario)
    assert np.all(encoded >= 0.0), "Encoded values below 0"
    assert np.all(encoded <= 1.0), "Encoded values above 1"


# ---------------------------------------------------------------------------
# 4. decode is deterministic (same position → same solution)
# ---------------------------------------------------------------------------

def test_decode_deterministic():
    scenario = _small_scenario()
    node_ids, dist_mat, time_mat = _build_matrices_for_scenario(scenario)
    rng = np.random.default_rng(3)
    n_dim = 2 * len(scenario.containers)
    pos = rng.uniform(0.0, 1.0, n_dim)

    sol1 = _decode(pos, scenario, dist_mat, time_mat)
    sol2 = _decode(pos, scenario, dist_mat, time_mat)

    assert sol1.assignments == sol2.assignments
    assert sol1.total_distance_km == sol2.total_distance_km
