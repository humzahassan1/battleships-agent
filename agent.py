"""
Battleship agent — envelope state-machine loop.

Run against real server:   py agent.py [--note "description"]
Run against simulator:     BASE_URL=http://localhost:8765 py agent.py
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import client
from strategy import choose_layout, choose_shot

NOTE_DEFAULT = "edge-biased placement + parity hunt + persistent signer"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "attempts.jsonl")


def _load_best_score() -> int | None:
    """Return the highest finalScore seen in the log, or None if the log is empty."""
    best = None
    try:
        with open(LOG_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    s = rec.get("finalScore")
                    if isinstance(s, (int, float)) and (best is None or s > best):
                        best = s
                except (json.JSONDecodeError, TypeError):
                    pass
    except FileNotFoundError:
        pass
    return best


def _log(record: dict) -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    _auto_commit(record)


def _auto_commit(record: dict) -> None:
    dq = record.get("disqualified", False)
    score = record.get("finalScore")
    wins = record.get("wins", 0)
    losses = record.get("losses", 0)
    if dq:
        reason = record.get("disqualifiedReason", "DQ")
        msg = f"attempt: DQ={reason} W={wins} L={losses}"
    else:
        msg = f"attempt: score={score} W={wins} L={losses}"
    project_dir = os.path.dirname(LOG_FILE)
    try:
        subprocess.run(
            ["git", "add", "attempts.jsonl"],
            cwd=project_dir, check=True, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=project_dir, check=True, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=project_dir, check=True, capture_output=True, timeout=30,
        )
        print(f"  (committed + pushed: {msg})")
    except Exception as e:
        print(f"  (auto-commit/push failed: {e})")


def _print_summary(r: dict, note: str, prev_best: int | None) -> None:
    score = r.get("finalScore")
    if score is not None and prev_best is not None:
        delta = score - prev_best
        cmp = f"previous best {prev_best} ({delta:+d})"
    elif score is not None:
        cmp = "first recorded attempt"
    else:
        cmp = ""
    parts = [f"finalScore {score}"]
    if cmp:
        parts.append(cmp)
    parts.append(f"W:{r.get('wins')} L:{r.get('losses')}")
    parts.append(f"shipsLost:{r.get('agentShipsLost')}  oppSunk:{r.get('opponentShipsSunk')}")
    print("  " + "  |  ".join(parts))
    print(f"  note: {note}")


def run(note: str) -> None:
    prev_best = _load_best_score()
    print("Starting attempt...")
    try:
        resp = client.create_attempt()
    except RuntimeError as exc:
        if "ACTIVE_ATTEMPT_EXISTS" not in str(exc):
            raise
        print("  (resuming existing active attempt)")
        resp = client.get_current_attempt()

    shots_this_game = 0
    wins = losses = 0

    while True:
        rt = resp.get("responseType")

        if rt == "MOVE_REQUIRED":
            state = resp["state"]
            game = state.get("gameOrdinal", "?")
            total = state.get("totalGames", "?")
            move = state["nextRequiredMove"]

            if move == "PLACE_SHIPS":
                shots_this_game = 0
                layout = choose_layout(state)
                resp = client.place_ships(layout)

            elif move == "SUBMIT_SHOT":
                shot = choose_shot(state)
                shots_this_game += 1
                resp = client.submit_shot(shot["row"], shot["col"])
                print(
                    f"\r  [Game {game}/{total}] shot {shots_this_game:3d}  "
                    f"({shot['row']},{shot['col']})   ",
                    end="", flush=True,
                )

            else:
                print(f"\nUnknown move: {move}")
                sys.exit(1)

        elif rt == "GAME_COMPLETED":
            result = resp.get("gameResult", {})
            won = result.get("agentWon")
            if won:
                wins += 1
            else:
                losses += 1
            print(f"\r  Game over — {'WIN ' if won else 'LOSS'} in {shots_this_game:3d} shots"
                  f"  (W:{wins} L:{losses})                      ")
            shots_this_game = 0
            resp = resp["next"]

        elif rt == "ATTEMPT_COMPLETED":
            r = resp.get("result", {})
            print("\n=== ATTEMPT COMPLETE ===")
            print(f"Final score:        {r.get('finalScore')}")
            print(f"Wins / Losses:      {r.get('wins')} / {r.get('losses')}")
            print(f"Hit differential:   {r.get('hitDifferential')}")
            print(f"Opp ships sunk:     {r.get('opponentShipsSunk')}")
            print(f"Agent ships lost:   {r.get('agentShipsLost')}")
            print(f"New best?           {r.get('isNewBest')}")
            print()
            _print_summary(r, note, prev_best)
            _log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "finalScore": r.get("finalScore"),
                "wins": r.get("wins"),
                "losses": r.get("losses"),
                "opponentShipsSunk": r.get("opponentShipsSunk"),
                "agentShipsLost": r.get("agentShipsLost"),
                "hitDifferential": r.get("hitDifferential"),
                "isNewBest": r.get("isNewBest"),
                "note": note,
            })
            break

        elif rt == "ATTEMPT_DISQUALIFIED":
            reason = resp.get("reason", "UNKNOWN")
            ctx = resp.get("context", {})
            print(f"\n!!! DISQUALIFIED: {reason}")
            print(f"    Game {ctx.get('gameOrdinal')}, move {ctx.get('lastRequiredMove')}")
            _log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "finalScore": None,
                "wins": wins,
                "losses": losses,
                "opponentShipsSunk": None,
                "agentShipsLost": None,
                "hitDifferential": None,
                "isNewBest": False,
                "disqualified": True,
                "disqualifiedReason": reason,
                "note": note,
            })
            sys.exit(2)

        else:
            print(f"\nUnexpected responseType: {rt}")
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", default=NOTE_DEFAULT,
                        help="Description of what changed in this run")
    args = parser.parse_args()
    run(args.note)
