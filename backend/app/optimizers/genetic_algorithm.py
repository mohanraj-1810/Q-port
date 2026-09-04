"""
Q-PORT Genetic Algorithm Baseline
===================================
Uses the EXACT same encoding as QPSO (priority-based random-key) so the
benchmark comparison isolates search strategy, not representation.

No external GA libraries (no DEAP). Hand-rolled tournament selection,
single-point crossover, Gaussian mutation, and elitism.

Parameters
----------
population_size : 60 (default)
tournament_k    : 3
crossover_rate  : 0.8
mutation_rate   : 0.1 (per-dimension)
elitism         : top 2 individuals carried over unchanged each generation
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np

from app.models import Scenario, Solution
from app.optimizers.fitness import compute_fitness, count_violations
from app.optimizers.qpso import (
    DEFAULT_MAX_ITER_LARGE,
    DEFAULT_MAX_ITER_MEDIUM,
    DEFAULT_MAX_ITER_SMALL,
    _build_matrices_for_scenario,
    _decode,
    _get_max_iter,
    _random_position,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default hyperparameters
# ---------------------------------------------------------------------------
DEFAULT_POP_SIZE = 60
TOURNAMENT_K = 3
CROSSOVER_RATE = 0.8
MUTATION_RATE = 0.1      # probability per dimension
MUTATION_SIGMA = 0.15    # Gaussian std dev for mutation
ELITISM_COUNT = 2


def _tournament_select(
    population: np.ndarray,
    fitnesses: np.ndarray,
    rng: np.random.Generator,
    k: int = TOURNAMENT_K,
) -> np.ndarray:
    """Return the best individual from a random tournament of size k."""
    indices = rng.choice(len(population), size=k, replace=False)
    best_idx = indices[np.argmin(fitnesses[indices])]
    return population[best_idx].copy()


def _single_point_crossover(
    parent1: np.ndarray,
    parent2: np.ndarray,
    rng: np.random.Generator,
    crossover_rate: float = CROSSOVER_RATE,
) -> tuple[np.ndarray, np.ndarray]:
    """Single-point crossover. Returns two children."""
    if rng.uniform() > crossover_rate:
        return parent1.copy(), parent2.copy()
    point = rng.integers(1, len(parent1))
    child1 = np.concatenate([parent1[:point], parent2[point:]])
    child2 = np.concatenate([parent2[:point], parent1[point:]])
    return child1, child2


def _gaussian_mutate(
    individual: np.ndarray,
    rng: np.random.Generator,
    mutation_rate: float = MUTATION_RATE,
    sigma: float = MUTATION_SIGMA,
) -> np.ndarray:
    """Apply Gaussian mutation per-dimension with probability mutation_rate."""
    mask = rng.uniform(0.0, 1.0, len(individual)) < mutation_rate
    noise = rng.normal(0.0, sigma, len(individual))
    individual = individual + mask * noise
    return np.clip(individual, 0.0, 1.0)


def solve(
    scenario: Scenario,
    reference_solution: Solution,
    population_size: int = DEFAULT_POP_SIZE,
    max_iter: Optional[int] = None,
    crossover_rate: float = CROSSOVER_RATE,
    mutation_rate: float = MUTATION_RATE,
    seed: int = 42,
) -> Solution:
    """
    Run the Genetic Algorithm on the given scenario.

    Uses the same iteration budget as QPSO for a fair runtime comparison.

    Parameters
    ----------
    scenario           : routing scenario
    reference_solution : OR-Tools solution for fitness normalisation
    population_size    : number of individuals
    max_iter           : generation limit (None → size-based default)
    crossover_rate     : probability of crossover per pair
    mutation_rate      : probability of mutation per dimension
    seed               : numpy RNG seed

    Returns
    -------
    Best Solution found (method='ga')
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    mi = max_iter or _get_max_iter(scenario)

    node_ids, dist_mat, time_mat = _build_matrices_for_scenario(scenario)
    n_dim = 2 * len(scenario.containers)

    # ---- Initialise population -------------------------------------------
    population = rng.uniform(0.0, 1.0, (population_size, n_dim))
    fitnesses = np.full(population_size, np.inf)

    def _eval_all(pop: np.ndarray) -> tuple[np.ndarray, list[Solution]]:
        fits = np.zeros(len(pop))
        sols = []
        for i, ind in enumerate(pop):
            sol = _decode(ind, scenario, dist_mat, time_mat, reference_solution)
            fits[i] = sol.fitness
            sols.append(sol)
        return fits, sols

    fitnesses, solutions = _eval_all(population)
    best_idx = int(np.argmin(fitnesses))
    best_sol = solutions[best_idx]
    best_fit = fitnesses[best_idx]

    logger.info(
        "GA starting: pop=%d max_iter=%d initial_best_fit=%.4f",
        population_size, mi, best_fit,
    )

    # ---- Evolution loop --------------------------------------------------
    for gen in range(mi):
        # Elitism: carry top-k unchanged
        elite_indices = np.argsort(fitnesses)[:ELITISM_COUNT]
        elites = population[elite_indices].copy()

        # Build new generation
        new_pop = list(elites)
        while len(new_pop) < population_size:
            p1 = _tournament_select(population, fitnesses, rng)
            p2 = _tournament_select(population, fitnesses, rng)
            c1, c2 = _single_point_crossover(p1, p2, rng, crossover_rate)
            c1 = _gaussian_mutate(c1, rng, mutation_rate)
            c2 = _gaussian_mutate(c2, rng, mutation_rate)
            new_pop.append(c1)
            if len(new_pop) < population_size:
                new_pop.append(c2)

        population = np.array(new_pop[:population_size])
        fitnesses, solutions = _eval_all(population)

        gen_best_idx = int(np.argmin(fitnesses))
        if fitnesses[gen_best_idx] < best_fit:
            best_fit = fitnesses[gen_best_idx]
            best_sol = solutions[gen_best_idx]

    runtime_ms = (time.perf_counter() - t0) * 1000.0
    best_sol.method = "ga"
    best_sol.runtime_ms = round(runtime_ms, 1)

    logger.info(
        "✅ GA done in %.0fms — fitness=%.4f dist=%.1fkm violations=%d",
        runtime_ms, best_sol.fitness, best_sol.total_distance_km,
        best_sol.constraint_violations,
    )
    return best_sol
