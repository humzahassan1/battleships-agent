"""
Local simulator — no auth required, pure stdlib.

Implements the 6 game routes against a random-shooting opponent.
Run: py simulator.py            (default port 8765)
     PORT=9000 py simulator.py

Then test: BASE_URL=http://localhost:8765 py agent.py
"""

import json
import os
import random
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

PORT = int(os.environ.get("PORT", 8765))
COMP_ID = "295cccc9137b5335cc581d67d655d6fa3b41dac6610dad0e7ed201625523ad8c"

SHIP_CLASSES = [
    {"class": "CARRIER",    "length": 5},
    {"class": "BATTLESHIP", "length": 4},
    {"class": "CRUISER",    "length": 3},
    {"class": "SUBMARINE",  "length": 3},
    {"class": "DESTROYER",  "length": 2},
]
TOTAL_SHIP_CELLS = sum(s["length"] for s in SHIP_CLASSES)  # 17

OPPONENTS = (
    [{"opponentId": f"scout-{i}", "displayName": f"Scout {i}",
      "opponentClass": "SCOUT", "baseScore": 14} for i in range(1, 6)]
    + [{"opponentId": f"warship-{i}", "displayName": f"Warship {i}",
        "opponentClass": "WARSHIP", "baseScore": 15} for i in range(1, 11)]
)

RULES = {
    "competitionId": COMP_ID,
    "displayName": "Standard Competition v1 (simulator)",
    "boardRules": {
        "gridRows": 10, "gridCols": 10,
        "shipClasses": SHIP_CLASSES, "allowAdjacency": True,
    },
    "scoringConstants": {
        "agentHitPoints": 1,
        "sinkBonusByClass": {"CARRIER": 10, "BATTLESHIP": 8, "CRUISER": 7, "SUBMARINE": 6, "DESTROYER": 4},
        "perShipLossPenalty": 2,
        "classLossPenaltyByClass": {"CARRIER": 10, "BATTLESHIP": 8, "CRUISER": 7, "SUBMARINE": 6, "DESTROYER": 4},
    },
    "turnTimeoutSeconds": 10,
}


# ── Game state ─────────────────────────────────────────────────────────────────

class GameState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.game_ordinal = 1
        self.ships_placed = False
        self.attempt_done = False
        self.disqualified = False
        self.disq_reason = None

        # Per-game state
        self._new_game()

    def _random_fleet(self) -> list[dict]:
        R, C = 10, 10
        used: set = set()
        placements = []
        for ship in SHIP_CLASSES:
            length = ship["length"]
            while True:
                horiz = random.random() < 0.5
                if horiz:
                    r = random.randrange(R)
                    c = random.randrange(C - length + 1)
                    cells = [(r, c + i) for i in range(length)]
                else:
                    r = random.randrange(R - length + 1)
                    c = random.randrange(C)
                    cells = [(r + i, c) for i in range(length)]
                if any(cell in used for cell in cells):
                    continue
                for cell in cells:
                    used.add(cell)
                placements.append({
                    "shipClass": ship["class"], "length": length,
                    "cells": cells, "sunk": False,
                })
                break
        return placements

    def _new_game(self):
        self.agent_fleet: list[dict] = []  # filled by place_ships
        self.opponent_fleet: list[dict] = self._random_fleet()
        self.agent_shots: list[dict] = []
        self.opponent_shots: list[dict] = []
        self.opp_untried = [(r, c) for r in range(10) for c in range(10)]
        random.shuffle(self.opp_untried)
        self.ships_placed = False

    def opponent_fire(self) -> dict:
        r, c = self.opp_untried.pop()
        # Check if it hits any of the agent's ship cells
        outcome = "MISS"
        sunk_class = None
        for ship in self.agent_fleet:
            if (r, c) in ship["cells"]:
                ship["hits"] = ship.get("hits", set()) | {(r, c)}
                if len(ship["hits"]) == ship["length"]:
                    ship["sunk"] = True
                    outcome = "SINK"
                    sunk_class = ship["shipClass"]
                else:
                    outcome = "HIT"
                break
        shot = {"row": r, "col": c, "outcome": outcome}
        if sunk_class:
            shot["sunkShipClass"] = sunk_class
        self.opponent_shots.append(shot)
        return shot

    def agent_fire(self, row: int, col: int) -> dict:
        tried = {(s["row"], s["col"]) for s in self.agent_shots}
        if (row, col) in tried or not (0 <= row < 10 and 0 <= col < 10):
            self.disqualified = True
            self.disq_reason = "ILLEGAL_MOVE"
            return {}
        outcome = "MISS"
        sunk_class = None
        for ship in self.opponent_fleet:
            if (row, col) in [tuple(cell) for cell in ship["cells"]]:
                ship["hits"] = ship.get("hits", set()) | {(row, col)}
                if len(ship["hits"]) == ship["length"]:
                    ship["sunk"] = True
                    outcome = "SINK"
                    sunk_class = ship["shipClass"]
                else:
                    outcome = "HIT"
                break
        shot = {"row": row, "col": col, "outcome": outcome}
        if sunk_class:
            shot["sunkShipClass"] = sunk_class
        self.agent_shots.append(shot)
        return shot

    @property
    def opponent_sunk_classes(self) -> list[str]:
        return [s["shipClass"] for s in self.opponent_fleet if s["sunk"]]

    @property
    def agent_sunk_classes(self) -> list[str]:
        return [s["shipClass"] for s in self.agent_fleet if s["sunk"]]

    @property
    def agent_won(self) -> bool:
        return len(self.opponent_sunk_classes) == len(SHIP_CLASSES)

    @property
    def agent_lost(self) -> bool:
        return len(self.agent_sunk_classes) == len(SHIP_CLASSES)

    def public_state(self) -> dict:
        opponent = OPPONENTS[self.game_ordinal - 1]
        return {
            "competitionId": COMP_ID,
            "gameOrdinal": self.game_ordinal,
            "totalGames": 15,
            "opponent": opponent,
            "nextRequiredMove": "PLACE_SHIPS" if not self.ships_placed else "SUBMIT_SHOT",
            "nextMoveDeadlineAt": "2099-01-01T00:00:10.000Z",
            "board": RULES["boardRules"],
            "yourFleet": [
                {"shipClass": s["shipClass"], "sunk": s["sunk"],
                 "placements": [{"row": r, "col": c} for r, c in s["cells"]]}
                for s in self.agent_fleet
            ],
            "yourShots": self.agent_shots,
            "incomingShots": self.opponent_shots,
            "sunkOpponentShipClasses": self.opponent_sunk_classes,
        }


_state = GameState()


# ── HTTP handler ───────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  [{self.command}] {self.path} -> {fmt % args}")

    def _send(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("x-request-id", f"sim-{int(time.time()*1000)}")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _disq(self, reason: str) -> dict:
        return {
            "responseType": "ATTEMPT_DISQUALIFIED",
            "reason": reason,
            "ranked": False,
            "attemptId": "sim-attempt",
            "context": {
                "lastRequiredMove": "SUBMIT_SHOT",
                "gameOrdinal": _state.game_ordinal,
                "opponentId": OPPONENTS[_state.game_ordinal - 1]["opponentId"],
                "deadlineAt": "2099-01-01T00:00:10.000Z",
            },
        }

    def do_GET(self):
        path = urlparse(self.path).path
        base = f"/competitions/{COMP_ID}"

        if path == f"{base}/rules":
            self._send(200, RULES)
        elif path == f"{base}/attempts/current":
            if _state.attempt_done or _state.disqualified:
                self._send(404, {"code": "NO_ACTIVE_ATTEMPT", "message": "No active attempt."})
            else:
                self._send(200, {"responseType": "MOVE_REQUIRED", "state": _state.public_state()})
        else:
            self._send(404, {"code": "NOT_FOUND", "message": "Route not found."})

    def do_POST(self):
        path = urlparse(self.path).path
        base = f"/competitions/{COMP_ID}"

        if path == f"{base}/attempts":
            if _state.disqualified or _state.attempt_done:
                _state.reset()
            else:
                # Fresh start if no active attempt
                pass
            self._send(200, {"responseType": "MOVE_REQUIRED", "state": _state.public_state()})

        elif path == f"{base}/attempts/current/placements":
            body = self._read_body()
            placements = body.get("placements", [])
            # Validate and store fleet
            used: set = set()
            fleet = []
            ok = True
            classes_seen = set()
            for p in placements:
                sc = p.get("shipClass")
                length = next((s["length"] for s in SHIP_CLASSES if s["class"] == sc), None)
                if length is None or sc in classes_seen:
                    ok = False; break
                classes_seen.add(sc)
                r, c = p.get("startRow", 0), p.get("startCol", 0)
                horiz = p.get("orientation") == "HORIZONTAL"
                cells = [(r, c + i) for i in range(length)] if horiz else [(r + i, c) for i in range(length)]
                for cell in cells:
                    if cell in used or not (0 <= cell[0] < 10 and 0 <= cell[1] < 10):
                        ok = False; break
                    used.add(cell)
                if not ok:
                    break
                fleet.append({"shipClass": sc, "length": length, "cells": cells, "sunk": False, "hits": set()})

            if not ok or len(fleet) != len(SHIP_CLASSES):
                _state.disqualified = True
                _state.disq_reason = "ILLEGAL_MOVE"
                self._send(200, self._disq("ILLEGAL_MOVE"))
            else:
                _state.agent_fleet = fleet
                _state.ships_placed = True
                self._send(200, {"responseType": "MOVE_REQUIRED", "state": _state.public_state()})

        elif path == f"{base}/attempts/current/shots":
            body = self._read_body()
            row, col = body.get("row"), body.get("col")

            if _state.disqualified:
                self._send(200, self._disq(_state.disq_reason or "ILLEGAL_MOVE"))
                return

            # Agent fires
            shot = _state.agent_fire(row, col)
            if _state.disqualified:
                self._send(200, self._disq("ILLEGAL_MOVE"))
                return

            # Opponent fires back
            _state.opponent_fire()

            game_over = _state.agent_won or _state.agent_lost

            if not game_over:
                self._send(200, {"responseType": "MOVE_REQUIRED", "state": _state.public_state()})
            else:
                game_result = {
                    "agentWon": _state.agent_won,
                    "opponentSunkClasses": _state.opponent_sunk_classes,
                    "agentSunkClasses": _state.agent_sunk_classes,
                }
                if _state.game_ordinal < 15:
                    _state.game_ordinal += 1
                    _state._new_game()
                    next_env = {"responseType": "MOVE_REQUIRED", "state": _state.public_state()}
                    self._send(200, {
                        "responseType": "GAME_COMPLETED",
                        "gameResult": game_result,
                        "next": next_env,
                    })
                else:
                    _state.attempt_done = True
                    self._send(200, {
                        "responseType": "ATTEMPT_COMPLETED",
                        "result": {
                            "attemptId": "sim-attempt",
                            "finalScore": 0,
                            "wins": 0,
                            "losses": 0,
                            "hitDifferential": 0,
                            "opponentShipsSunk": 0,
                            "agentShipsLost": 0,
                            "isNewBest": False,
                            "completionMessage": "Simulator complete.",
                        },
                    })
        else:
            self._send(404, {"code": "NOT_FOUND", "message": "Route not found."})

    def do_DELETE(self):
        path = urlparse(self.path).path
        base = f"/competitions/{COMP_ID}"
        if path == f"{base}/attempts/current":
            _state.disqualified = True
            _state.disq_reason = "ABANDONED"
            self._send(200, self._disq("ABANDONED"))
        else:
            self._send(404, {"code": "NOT_FOUND", "message": "Route not found."})


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Simulator running at http://127.0.0.1:{PORT}")
    print(f"Competition ID: {COMP_ID}")
    print(f"Run agent with: BASE_URL=http://127.0.0.1:{PORT} py agent.py")
    print("Ctrl-C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
