"""
Two shot strategies:

  choose_shot_checkerboard  — baseline: parity-grid hunt + orthogonal-neighbour target
  choose_shot_density       — upgraded: probability-density model

For each remaining (unsunk) ship, slide it across every legal position
(no cell on a known miss). Placements that cover an unresolved HIT cell
receive a heavy bonus weight so the model automatically extends along a hit
ship before hunting fresh cells. Fire at the untried cell with the highest
cumulative weighted count.

choose_shot is aliased to choose_shot_density so agent.py picks it up.
"""

import random

SHIP_LENGTHS: dict[str, int] = {
    "CARRIER": 5, "BATTLESHIP": 4, "CRUISER": 3, "SUBMARINE": 3, "DESTROYER": 2,
}


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _edge_biased(n: int, strength: int = 4) -> int:
    """Sample from [0, n) with `strength`× weight on the outermost 2 positions.

    Placing ships near the edge exploits a property of density-based attackers:
    interior cells receive higher probability mass because more ship placements
    pass through them. Edge cells have fewer valid placements, so the opponent
    hunts the center first — wasting shots while our fleet hides at the margins.
    """
    if n <= 4:
        return random.randrange(n)
    pool = (
        [0, 1, n - 2, n - 1] * strength        # edges: boosted weight
        + list(range(2, n - 2))                  # interior: weight 1
    )
    return random.choice(pool)


def choose_layout(state: dict) -> list[dict]:
    """Fleet placement: 1-cell buffer between ships + edge-biased positions.

    Horizontal ships are biased toward rows 0/1/8/9 (top/bottom edges).
    Vertical ships are biased toward cols 0/1/8/9 (left/right edges).
    This forces density-based opponents to waste shots hunting the center
    while our ships sit at the periphery.
    Falls back to uniform placement if edge-biased fails (rare).
    """
    rules = state["board"]
    R, C = rules["gridRows"], rules["gridCols"]

    def _try_place(use_buffer: bool, edge_bias: bool) -> "list[dict] | None":
        ship_cells: set[tuple[int, int]] = set()
        forbidden: set[tuple[int, int]] = set()
        result: list[dict] = []
        for ship in rules["shipClasses"]:
            length = ship["length"]
            placed = False
            for _ in range(2000):
                horiz = random.random() < 0.5
                if horiz:
                    r = _edge_biased(R) if edge_bias else random.randrange(R)
                    c = random.randrange(C - length + 1)
                    cells = [(r, c + i) for i in range(length)]
                else:
                    r = random.randrange(R - length + 1)
                    c = _edge_biased(C) if edge_bias else random.randrange(C)
                    cells = [(r + i, c) for i in range(length)]
                blocked = forbidden if use_buffer else ship_cells
                if any(cell in blocked for cell in cells):
                    continue
                ship_cells.update(cells)
                for cr, cc in cells:
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            forbidden.add((cr + dr, cc + dc))
                result.append({
                    "shipClass": ship["class"],
                    "orientation": "HORIZONTAL" if horiz else "VERTICAL",
                    "startRow": r,
                    "startCol": c,
                })
                placed = True
                break
            if not placed:
                return None
        return result

    return (
        _try_place(use_buffer=True,  edge_bias=True)
        or _try_place(use_buffer=False, edge_bias=True)
        or _try_place(use_buffer=True,  edge_bias=False)
        or _try_place(use_buffer=False, edge_bias=False)  # type: ignore[return-value]
    )


def _find_sunk_cells(shots: list[dict]) -> set[tuple[int, int]]:
    """
    Identify which HIT/SINK cells belong to already-sunk ships.

    For each SINK shot we know the ship class (and its length). We search for a
    contiguous run of hit cells through the SINK cell (in the horizontal or
    vertical direction) of exactly that length. When a run is longer than the
    ship (adjacent ships both hit), we take the window closest to the SINK cell.
    Already-claimed cells are removed from consideration so later SINKs don't
    steal cells from earlier ones.
    """
    hit_set = {(s["row"], s["col"]) for s in shots if s["outcome"] in ("HIT", "SINK")}
    sunk: set[tuple[int, int]] = set()

    for s in shots:
        if s["outcome"] != "SINK":
            continue
        r, c = s["row"], s["col"]
        length = SHIP_LENGTHS.get(s.get("sunkShipClass", ""), 1)
        available = hit_set - sunk  # unclaimed cells

        claimed: set[tuple[int, int]] = set()
        for dr, dc in ((0, 1), (1, 0)):
            # Walk backward to find run start
            sr, sc = r, c
            while (sr - dr, sc - dc) in available:
                sr -= dr
                sc -= dc
            # Collect the full run forward
            run: list[tuple[int, int]] = []
            nr, nc = sr, sc
            while (nr, nc) in available:
                run.append((nr, nc))
                nr += dr
                nc += dc

            if (r, c) not in run:
                continue

            sink_idx = run.index((r, c))
            # Try windows of `length` that include sink_idx, nearest first
            for start in range(
                max(0, sink_idx - length + 1),
                min(sink_idx + 1, len(run) - length + 1),
            ):
                window = run[start : start + length]
                if len(window) == length:
                    claimed = set(window)
                    break
            if claimed:
                break

        sunk |= claimed or {(r, c)}

    return sunk


def _unresolved_hits(shots: list[dict]) -> set[tuple[int, int]]:
    """HIT cells whose ship has not yet been fully sunk."""
    sunk = _find_sunk_cells(shots)
    return {(s["row"], s["col"]) for s in shots if s["outcome"] == "HIT"} - sunk


# ── Strategy 1: checkerboard hunt / orthogonal-neighbour target ────────────────

def choose_shot_checkerboard(state: dict) -> dict:
    """
    Baseline strategy.
    TARGET: try all four orthogonal neighbours of every unresolved HIT.
    HUNT:   fire at a random even-parity cell (checkerboard).
    """
    R = state["board"]["gridRows"]
    C = state["board"]["gridCols"]
    shots = state.get("yourShots", [])
    tried = {(s["row"], s["col"]) for s in shots}

    for r, c in _unresolved_hits(shots):
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < R and 0 <= nc < C and (nr, nc) not in tried:
                return {"row": nr, "col": nc}

    # Hunt: checkerboard parity
    candidates = [
        (r, c) for r in range(R) for c in range(C)
        if (r + c) % 2 == 0 and (r, c) not in tried
    ]
    if not candidates:
        candidates = [(r, c) for r in range(R) for c in range(C) if (r, c) not in tried]

    r, c = random.choice(candidates)
    return {"row": r, "col": c}


# ── Strategy 2: probability-density model ─────────────────────────────────────

def choose_shot_density(state: dict, hit_weight: float = 100.0) -> dict:
    """
    Probability-density firing model.

    Algorithm
    ---------
    1. Build a 10×10 density grid, initialised to 0.
    2. For each ship class still afloat, enumerate every horizontal and
       vertical placement that does not overlap a known MISS.
       • Placement weight = `hit_weight` if it covers ≥1 unresolved HIT cell;
         otherwise 1.
    3. Add each placement's weight to every cell it covers.
    4. Fire at the untried cell with the highest density.

    In TARGET mode the heavy weight on placements that include an existing HIT
    cell forces the model to extend along the wounded ship and naturally
    constrains to the correct orientation once two collinear hits exist.
    In HUNT mode the gradient from centre > edge means the model prefers
    mid-board cells that more ships can reach.
    """
    R = state["board"]["gridRows"]
    C = state["board"]["gridCols"]
    shots = state.get("yourShots", [])
    tried = {(s["row"], s["col"]) for s in shots}
    misses = {(s["row"], s["col"]) for s in shots if s["outcome"] == "MISS"}
    unresolved = _unresolved_hits(shots)

    # Remaining ships: one of each class minus sunk ones
    sunk_pool: dict[str, int] = {}
    for cls in state.get("sunkOpponentShipClasses", []):
        sunk_pool[cls] = sunk_pool.get(cls, 0) + 1

    remaining: list[int] = []  # lengths only (class name not needed for density)
    for ship in state["board"]["shipClasses"]:
        cls = ship["class"]
        if sunk_pool.get(cls, 0) > 0:
            sunk_pool[cls] -= 1
        else:
            remaining.append(ship["length"])

    # Density accumulator
    density = [[0.0] * C for _ in range(R)]

    for length in remaining:
        for r in range(R):
            c_limit_h = C - length + 1
            r_limit_v = R - length + 1

            # Horizontal placements
            for c in range(c_limit_h):
                cells = [(r, c + i) for i in range(length)]
                if any(cell in misses for cell in cells):
                    continue
                w = hit_weight if any(cell in unresolved for cell in cells) else 1.0
                for r2, c2 in cells:
                    density[r2][c2] += w

            # Vertical placements
            if r < r_limit_v:
                for c in range(C):
                    cells = [(r + i, c) for i in range(length)]
                    if any(cell in misses for cell in cells):
                        continue
                    w = hit_weight if any(cell in unresolved for cell in cells) else 1.0
                    for r2, c2 in cells:
                        density[r2][c2] += w

    # In pure hunt mode (no active hits), restrict to a parity/checkerboard grid.
    # Every ship of length >= 2 spans at least one even-parity cell, so we are
    # guaranteed to hit every remaining ship while visiting only half the board.
    # This roughly halves hunt-phase shots and never misses a target.
    min_remaining = min(remaining) if remaining else 1
    use_parity = (not unresolved) and (min_remaining >= 2)

    best_r = best_c = 0
    best_score = -1.0
    for r in range(R):
        for c in range(C):
            if (r, c) in tried:
                continue
            if use_parity and (r + c) % 2 != 0:
                continue
            if density[r][c] > best_score:
                best_score = density[r][c]
                best_r, best_c = r, c

    if best_score < 0:
        # Parity grid exhausted (only destroyer left and we've covered all parity cells)
        # or no density signal at all — fall back to any untried cell.
        candidates = [
            (r, c) for r in range(R) for c in range(C)
            if (r, c) not in tried
        ]
        best_r, best_c = random.choice(candidates)

    return {"row": best_r, "col": best_c}


# Default used by agent.py
choose_shot = choose_shot_density
