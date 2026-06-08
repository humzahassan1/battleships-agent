"""
Benchmark: checkerboard hunt/target vs probability-density over N random boards.

Both strategies run against the SAME pre-generated fleets so the comparison
is apples-to-apples. Fleet randomness is seeded separately from strategy
randomness so checkerboard's random.choice calls don't corrupt the boards.

Usage:
    py benchmark.py          # 500 games each
    py benchmark.py 1000     # 1000 games each
"""

import random
import sys
import time

from strategy import (
    SHIP_LENGTHS,
    choose_shot_checkerboard,
    choose_shot_density,
)

# ── Board setup ────────────────────────────────────────────────────────────────

SHIP_CLASSES = [
    {"class": "CARRIER",    "length": 5},
    {"class": "BATTLESHIP", "length": 4},
    {"class": "CRUISER",    "length": 3},
    {"class": "SUBMARINE",  "length": 3},
    {"class": "DESTROYER",  "length": 2},
]

BOARD_TEMPLATE = {
    "gridRows": 10,
    "gridCols": 10,
    "shipClasses": SHIP_CLASSES,
    "allowAdjacency": True,
}


def _random_fleet(rng: random.Random) -> dict[str, list[tuple[int, int]]]:
    """Return {class: [(r,c), ...]} for a random legal fleet."""
    used: set[tuple[int, int]] = set()
    fleet: dict[str, list[tuple[int, int]]] = {}
    for ship in SHIP_CLASSES:
        cls, length = ship["class"], ship["length"]
        while True:
            horiz = rng.random() < 0.5
            if horiz:
                r = rng.randrange(10)
                c = rng.randrange(10 - length + 1)
                cells = [(r, c + i) for i in range(length)]
            else:
                r = rng.randrange(10 - length + 1)
                c = rng.randrange(10)
                cells = [(r + i, c) for i in range(length)]
            if any(cell in used for cell in cells):
                continue
            used.update(cells)
            fleet[cls] = cells
            break
    return fleet


def _simulate(strategy_fn, fleet: dict[str, list[tuple[int, int]]]) -> int:
    """
    Play one game using strategy_fn against the given fleet.
    Returns total shots fired to sink all ships.
    """
    cell_to_class: dict[tuple[int, int], str] = {
        cell: cls for cls, cells in fleet.items() for cell in cells
    }
    ship_hits: dict[str, set] = {cls: set() for cls in fleet}
    sunk_classes: list[str] = []
    shots: list[dict] = []
    ships_remaining = set(fleet.keys())

    state: dict = {
        "board": BOARD_TEMPLATE,
        "yourShots": shots,
        "sunkOpponentShipClasses": sunk_classes,
    }

    while ships_remaining:
        move = strategy_fn(state)
        r, c = move["row"], move["col"]

        if (r, c) in cell_to_class:
            cls = cell_to_class[(r, c)]
            ship_hits[cls].add((r, c))
            if len(ship_hits[cls]) == SHIP_LENGTHS[cls]:
                ships_remaining.discard(cls)
                sunk_classes.append(cls)
                rec = {"row": r, "col": c, "outcome": "SINK", "sunkShipClass": cls}
            else:
                rec = {"row": r, "col": c, "outcome": "HIT"}
        else:
            rec = {"row": r, "col": c, "outcome": "MISS"}

        shots.append(rec)
        # state references the same lists, so no copy needed

    return len(shots)


def _run(name: str, strategy_fn, fleets: list[dict]) -> list[int]:
    n = len(fleets)
    results: list[int] = []
    t0 = time.perf_counter()
    tick = max(1, n // 10)

    for i, fleet in enumerate(fleets):
        results.append(_simulate(strategy_fn, fleet))
        if (i + 1) % tick == 0:
            elapsed = time.perf_counter() - t0
            avg_so_far = sum(results) / len(results)
            print(f"  {name:30s}  {i+1:5d}/{n}  avg={avg_so_far:.1f}  ({elapsed:.1f}s)",
                  flush=True)

    return results


def _stats(name: str, results: list[int]) -> None:
    n = len(results)
    s = sorted(results)
    avg = sum(s) / n
    mn, mx = s[0], s[-1]
    p25 = s[n // 4]
    p50 = s[n // 2]
    p75 = s[3 * n // 4]
    p90 = s[int(n * 0.90)]

    print(f"\n{'─'*52}")
    print(f"  {name}")
    print(f"{'─'*52}")
    print(f"  n={n}    avg={avg:.2f}   min={mn}  max={mx}")
    print(f"  p25={p25}   p50={p50}   p75={p75}   p90={p90}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    # Pre-generate all boards with a fixed seed
    board_rng = random.Random(42)
    fleets = [_random_fleet(board_rng) for _ in range(N)]

    print(f"Benchmarking {N} random boards — two strategies\n")

    # Checkerboard (has randomness in hunt → use fixed seed per run for reproducibility)
    random.seed(7)
    print("Running checkerboard...")
    cb = _run("checkerboard", choose_shot_checkerboard, fleets)

    # Density (deterministic, but reset seed for fairness)
    random.seed(7)
    print("\nRunning density...")
    dn = _run("density", choose_shot_density, fleets)

    # Print stats
    _stats("Checkerboard hunt/target", cb)
    _stats("Probability density      ", dn)

    avg_cb = sum(cb) / N
    avg_dn = sum(dn) / N
    delta = avg_cb - avg_dn
    pct   = 100 * delta / avg_cb

    print(f"\n{'═'*52}")
    print(f"  Improvement: {delta:+.2f} shots/game  ({pct:+.1f}%)")
    print(f"  Checkerboard avg: {avg_cb:.2f}")
    print(f"  Density avg:      {avg_dn:.2f}")
    print(f"{'═'*52}\n")


if __name__ == "__main__":
    main()
