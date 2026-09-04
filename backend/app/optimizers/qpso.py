"""
Q-PORT Discrete QPSO — Core Contribution
=========================================
Implements a Quantum-behaved Particle Swarm Optimiser operating on a
priority-based random-key encoding for the heterogeneous CVRPTW.

Encoding (priority-based random-key)
--------------------------------------
Each particle's position is a real-valued vector of length 2 * n_containers:

  Block A [0 .. n-1]  : truck assignment values ∈ [0, 1]
      truck_index = floor(v * n_trucks), clamped to [0, n_trucks - 1]

  Block B [n .. 2n-1] : delivery sequence sort keys ∈ [0, 1]
      containers assigned to the same truck are sorted ascending by their
      Block-B value → that gives the delivery order.

decode() converts any position vector to a structurally valid Solution,
then evaluates it using the shared fitness function (same precomputed
shortest-path matrix as OR-Tools for a fair comparison).

QPSO Update Rule
----------------
Standard quantum delta-potential-well formulation:
    phi     ~ Uniform(0, 1)
    p       = phi * pbest[d] + (1 - phi) * gbest[d]   ("local attractor")
    u       ~ Uniform(0, 1)
    beta    = contraction-expansion coefficient (linearly decays 1.0 → 0.3)
    sign    = +1 or -1 (random)
    x[d]    = p ± beta * |mbest[d] - x[d]| * ln(1/u)

mbest = mean of all particles' personal best positions.

Convergence
-----------
Stops after max_iterations or if no improvement for `patience` iterations.
Beta decays linearly: 1.0 at iteration 0, 0.3 at max_iterations.

Warm-start (incremental re-optimisation)
-----------------------------------------
solve_incremental() accepts the previous gbest Solution. It:
  1. Encodes that solution into a base position vector.
  2. Initialises (n_particles - n_random) particles as small Gaussian
     perturbations of the base (σ = 0.05 for unaffected dimensions).
  3. For dimensions (both A and B) of affected_container_ids, uses a
     much larger perturbation (σ = 0.3) to force exploration of new
     truck assignments / orderings for those specific containers.
  4. Fills the remaining n_random slots with fully random particles.

This asymmetric initialisation lets the swarm exploit the previous
solution for stable containers while genuinely re-optimising disrupted ones.
The runtime difference vs. solve_full() on the same post-event scenario
is the empirical evidence for the "incremental is faster" claim.
"""
from __future__ import annotations

import copy
import logging
import math
import random
import time
from typing import Optional

import numpy as np

from app.models import Assignment, Container, Scenario, Solution, Truck
from app.network import build_distance_matrix, build_time_matrix, load_network
from app.optimizers.fitness import (
    FIXED_COST_PER_TRUCK,
    PER_KM_COST,
    compute_fitness,
    count_violations,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default hyperparameters
# ---------------------------------------------------------------------------
DEFAULT_N_PARTICLES = 40
DEFAULT_MAX_ITER_SMALL = 150
DEFAULT_MAX_ITER_MEDIUM = 80
DEFAULT_MAX_ITER_LARGE = 50
DEFAULT_PATIENCE = 20
BETA_START = 1.0
BETA_END = 0.3

# ---------------------------------------------------------------------------
# Fraction of particles that are fully random in warm-start
# ---------------------------------------------------------------------------
WARM_START_RANDOM_FRACTION = 0.2


# ===========================================================================
# Route cost calculator (shared with GA)
# ===========================================================================

def _build_matrices_for_scenario(
    scenario: Scenario,
) -> tuple[list[str], dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Build and return (node_ids, dist_matrix, time_matrix) for a scenario."""
    node_set: set[str] = {scenario.icd_node_id}
    for c in scenario.containers:
        node_set.add(c.origin_node)
        node_set.add(c.destination_node)
    for t in scenario.trucks:
        node_set.add(t.current_node)

    node_ids = sorted(node_set)
    G, _ = load_network()
    dist_mat = build_distance_matrix(G, node_ids)
    time_mat = build_time_matrix(G, node_ids)
    return node_ids, dist_mat, time_mat


def _route_cost(
    container_sequence: list[str],
    truck: Truck,
    scenario: Scenario,
    dist_mat: dict[str, dict[str, float]],
    time_mat: dict[str, dict[str, float]],
) -> tuple[float, float, float]:
    """
    Compute (distance_km, time_min, waiting_min) for a single truck's route.
    Route starts at truck.current_node, visits each container's destination.
    """
    container_map = {c.id: c for c in scenario.containers}
    current = truck.current_node
    total_dist = 0.0
    total_time = 0.0
    total_wait = 0.0
    elapsed = 0.0

    for cid in container_sequence:
        c = container_map.get(cid)
        if c is None:
            continue
        dest = c.destination_node
        d = dist_mat.get(current, {}).get(dest, 999_999.0)
        t = time_mat.get(current, {}).get(dest, 999_999.0)

        if d >= 999_000:  # unreachable — treat as big penalty in count_violations
            d = 9999.0
            t = 9999.0

        total_dist += d
        elapsed += t
        # Waiting: truck arrives before time window opens
        wait = max(0.0, c.earliest_time_min - elapsed)
        total_wait += wait
        elapsed += wait
        total_time += t + wait
        current = dest

    return total_dist, total_time, total_wait


def _decode(
    position: np.ndarray,
    scenario: Scenario,
    dist_mat: dict[str, dict[str, float]],
    time_mat: dict[str, dict[str, float]],
    reference_solution: Optional[Solution] = None,
) -> Solution:
    """
    Decode a position vector into a Solution.

    Block A → truck assignment
    Block B → delivery sequence within truck
    """
    n = len(scenario.containers)
    n_trucks = len(scenario.trucks)

    block_a = position[:n]    # truck assignment values
    block_b = position[n:]    # sequence sort keys

    containers = scenario.containers
    trucks = scenario.trucks
    container_map = {c.id: c for c in containers}
    truck_map = {t.id: t for t in trucks}

    # ---- Assign containers to trucks --------------------------------------
    truck_containers: dict[int, list[tuple[float, str]]] = {i: [] for i in range(n_trucks)}
    for i, c in enumerate(containers):
        raw = float(np.clip(block_a[i], 0.0, 1.0 - 1e-9))
        truck_idx = int(raw * n_trucks)
        truck_idx = max(0, min(n_trucks - 1, truck_idx))
        sort_key = float(block_b[i])
        truck_containers[truck_idx].append((sort_key, c.id))

    # ---- Sort within each truck ------------------------------------------
    assignments: list[Assignment] = []
    total_dist = 0.0
    total_time = 0.0
    total_wait = 0.0
    trucks_used = 0

    for ti, truck in enumerate(trucks):
        items = sorted(truck_containers[ti], key=lambda x: x[0])
        seq = [cid for _, cid in items]
        if seq:
            d, t, w = _route_cost(seq, truck, scenario, dist_mat, time_mat)
            total_dist += d
            total_time += t
            total_wait += w
            trucks_used += 1
        assignments.append(Assignment(truck_id=truck.id, container_sequence=seq))

    total_cost = FIXED_COST_PER_TRUCK * trucks_used + PER_KM_COST * total_dist

    sol = Solution(
        assignments=assignments,
        total_distance_km=round(total_dist, 3),
        total_time_min=round(total_time, 3),
        total_waiting_min=round(total_wait, 3),
        total_cost=round(total_cost, 2),
        constraint_violations=0,  # filled below
        fitness=0.0,
        method="qpso",
        runtime_ms=0.0,
    )
    sol.constraint_violations = count_violations(sol, scenario)

    if reference_solution is not None:
        sol.fitness = compute_fitness(sol, reference_solution, scenario)

    return sol


def _encode(solution: Solution, scenario: Scenario) -> np.ndarray:
    """
    Approximate inverse of _decode: map a Solution back to a position vector.

    This does NOT need to be a perfect inverse — only needs to produce a
    position that decodes to approximately the same assignment. Used for
    warm-starting the swarm.

    Block A: truck_index / n_trucks  → gives the midpoint of the truck's bin
    Block B: sequence rank / max_seq → preserves relative ordering
    """
    n = len(scenario.containers)
    n_trucks = len(scenario.trucks)
    container_order = {c.id: i for i, c in enumerate(scenario.containers)}
    truck_order = {t.id: i for i, t in enumerate(scenario.trucks)}

    block_a = np.full(n, 0.5)
    block_b = np.full(n, 0.5)

    for assignment in solution.assignments:
        ti = truck_order.get(assignment.truck_id, 0)
        seq_len = max(len(assignment.container_sequence), 1)
        for rank, cid in enumerate(assignment.container_sequence):
            ci = container_order.get(cid)
            if ci is None:
                continue
            # Centre of truck ti's bin (width = 1/n_trucks)
            block_a[ci] = (ti + 0.5) / n_trucks
            # Rank-based sort key
            block_b[ci] = (rank + 0.5) / seq_len

    return np.concatenate([block_a, block_b])


def _random_position(n_containers: int, rng: np.random.Generator) -> np.ndarray:
    return rng.uniform(0.0, 1.0, size=2 * n_containers)


# ===========================================================================
# QPSO Solver
# ===========================================================================

class _Swarm:
    def __init__(
        self,
        n_particles: int,
        n_dim: int,
        rng: np.random.Generator,
        scenario: Scenario,
        dist_mat: dict,
        time_mat: dict,
        reference_solution: Solution,
    ):
        self.n = n_particles
        self.dim = n_dim
        self.rng = rng
        self.scenario = scenario
        self.dist_mat = dist_mat
        self.time_mat = time_mat
        self.ref = reference_solution

        self.positions = rng.uniform(0.0, 1.0, (n_particles, n_dim))
        self.pbest_pos = self.positions.copy()
        self.pbest_fit = np.full(n_particles, np.inf)
        self.gbest_pos: np.ndarray = self.positions[0].copy()
        self.gbest_fit: float = np.inf
        self.gbest_sol: Optional[Solution] = None

        # Evaluate initial population
        for i in range(n_particles):
            fit, sol = self._eval(self.positions[i])
            self.pbest_fit[i] = fit
            if fit < self.gbest_fit:
                self.gbest_fit = fit
                self.gbest_pos = self.positions[i].copy()
                self.gbest_sol = sol

    def _eval(self, pos: np.ndarray) -> tuple[float, Solution]:
        sol = _decode(pos, self.scenario, self.dist_mat, self.time_mat, self.ref)
        return sol.fitness, sol

    def _mbest(self) -> np.ndarray:
        return self.pbest_pos.mean(axis=0)

    def step(self, iteration: int, max_iter: int) -> None:
        beta = BETA_START - (BETA_START - BETA_END) * (iteration / max(max_iter - 1, 1))
        mbest = self._mbest()

        for i in range(self.n):
            phi = self.rng.uniform(0.0, 1.0, self.dim)
            p = phi * self.pbest_pos[i] + (1.0 - phi) * self.gbest_pos
            u = self.rng.uniform(0.0, 1.0, self.dim)
            sign = np.where(self.rng.uniform(0.0, 1.0, self.dim) > 0.5, 1.0, -1.0)
            delta = beta * np.abs(mbest - self.positions[i]) * np.log(1.0 / (u + 1e-12))
            new_pos = np.clip(p + sign * delta, 0.0, 1.0)
            self.positions[i] = new_pos

            fit, sol = self._eval(new_pos)
            if fit < self.pbest_fit[i]:
                self.pbest_fit[i] = fit
                self.pbest_pos[i] = new_pos.copy()
                if fit < self.gbest_fit:
                    self.gbest_fit = fit
                    self.gbest_pos = new_pos.copy()
                    self.gbest_sol = sol

    def run(self, max_iter: int, patience: int) -> Solution:
        no_improve = 0
        best_ever = self.gbest_fit

        for it in range(max_iter):
            self.step(it, max_iter)
            if self.gbest_fit < best_ever - 1e-6:
                best_ever = self.gbest_fit
                no_improve = 0
            else:
                no_improve += 1
            if no_improve >= patience:
                logger.debug("QPSO early stop at iteration %d (patience=%d)", it, patience)
                break

        # Decode the final best solution to get all fields populated
        final = _decode(self.gbest_pos, self.scenario, self.dist_mat, self.time_mat, self.ref)
        return final


def _get_max_iter(scenario: Scenario) -> int:
    return {
        "small": DEFAULT_MAX_ITER_SMALL,
        "medium": DEFAULT_MAX_ITER_MEDIUM,
        "large": DEFAULT_MAX_ITER_LARGE,
    }.get(scenario.size, DEFAULT_MAX_ITER_SMALL)


def solve_full(
    scenario: Scenario,
    reference_solution: Solution,
    n_particles: int = DEFAULT_N_PARTICLES,
    max_iter: Optional[int] = None,
    patience: int = DEFAULT_PATIENCE,
    seed: int = 0,
) -> Solution:
    """
    Run QPSO from scratch (fully random initial swarm).

    Parameters
    ----------
    scenario           : the routing scenario
    reference_solution : OR-Tools solution for fitness normalisation
    n_particles        : swarm size
    max_iter           : iteration limit (None → use size-based default)
    patience           : early-stop patience (no-improvement iterations)
    seed               : numpy RNG seed for reproducibility

    Returns
    -------
    Best Solution found
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    mi = max_iter or _get_max_iter(scenario)

    node_ids, dist_mat, time_mat = _build_matrices_for_scenario(scenario)
    n_dim = 2 * len(scenario.containers)

    swarm = _Swarm(n_particles, n_dim, rng, scenario, dist_mat, time_mat, reference_solution)
    sol = swarm.run(mi, patience)

    runtime_ms = (time.perf_counter() - t0) * 1000.0
    sol.method = "qpso"
    sol.runtime_ms = round(runtime_ms, 1)
    logger.info(
        "✅ QPSO (full) done in %.0fms — fitness=%.4f dist=%.1fkm violations=%d",
        runtime_ms, sol.fitness, sol.total_distance_km, sol.constraint_violations,
    )
    return sol


def solve_incremental(
    scenario: Scenario,
    reference_solution: Solution,
    previous_solution: Solution,
    affected_container_ids: list[str],
    n_particles: int = DEFAULT_N_PARTICLES,
    max_iter: Optional[int] = None,
    patience: int = DEFAULT_PATIENCE,
    seed: int = 1,
) -> Solution:
    """
    Run QPSO with a warm-started swarm biased toward the previous solution.

    Unaffected containers get small perturbations (σ=0.05).
    Affected containers get large perturbations (σ=0.3) to force re-exploration.

    Parameters
    ----------
    previous_solution      : gbest from the last solve (before the event)
    affected_container_ids : containers whose routing may have changed

    Returns
    -------
    Best Solution found (method='qpso')
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    mi = max_iter or _get_max_iter(scenario)

    node_ids, dist_mat, time_mat = _build_matrices_for_scenario(scenario)
    n = len(scenario.containers)
    n_dim = 2 * n
    n_trucks = len(scenario.trucks)

    # Base position from previous solution
    base_pos = _encode(previous_solution, scenario)

    # Map affected container ids to their indices in scenario.containers
    container_idx = {c.id: i for i, c in enumerate(scenario.containers)}
    affected_indices = set()
    for cid in affected_container_ids:
        ci = container_idx.get(cid)
        if ci is not None:
            affected_indices.add(ci)          # Block A dim
            affected_indices.add(ci + n)      # Block B dim

    n_random = max(1, int(n_particles * WARM_START_RANDOM_FRACTION))
    n_warm = n_particles - n_random

    init_positions = np.zeros((n_particles, n_dim))

    # Warm particles: perturb base position
    for i in range(n_warm):
        perturbed = base_pos.copy()
        for d in range(n_dim):
            sigma = 0.3 if d in affected_indices else 0.05
            perturbed[d] = np.clip(
                perturbed[d] + rng.normal(0.0, sigma), 0.0, 1.0
            )
        init_positions[i] = perturbed

    # Random particles
    for i in range(n_warm, n_particles):
        init_positions[i] = rng.uniform(0.0, 1.0, n_dim)

    # Build swarm with custom initial positions
    swarm = _Swarm(n_particles, n_dim, rng, scenario, dist_mat, time_mat, reference_solution)
    swarm.positions = init_positions.copy()
    swarm.pbest_pos = init_positions.copy()

    # Evaluate warm-start initial population
    swarm.gbest_fit = np.inf
    for i in range(n_particles):
        fit, sol = swarm._eval(init_positions[i])
        swarm.pbest_fit[i] = fit
        if fit < swarm.gbest_fit:
            swarm.gbest_fit = fit
            swarm.gbest_pos = init_positions[i].copy()
            swarm.gbest_sol = sol

    sol = swarm.run(mi, patience)

    runtime_ms = (time.perf_counter() - t0) * 1000.0
    sol.method = "qpso"
    sol.runtime_ms = round(runtime_ms, 1)
    logger.info(
        "✅ QPSO (incremental) done in %.0fms — fitness=%.4f dist=%.1fkm violations=%d",
        runtime_ms, sol.fitness, sol.total_distance_km, sol.constraint_violations,
    )
    return sol


# ===========================================================================
# Public aliases
# ===========================================================================
encode = _encode
decode_position = lambda pos, scenario, dist_mat, time_mat, ref: _decode(
    pos, scenario, dist_mat, time_mat, ref
)
build_matrices = _build_matrices_for_scenario
