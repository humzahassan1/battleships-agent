"""
Battleship agent — envelope state-machine loop.

Run against real server:   py agent.py
Run against simulator:     BASE_URL=http://localhost:8765 py agent.py
"""

import sys
import client
from strategy import choose_layout, choose_shot


def run() -> None:
    print("Starting attempt...")
    resp = client.create_attempt()

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
            break

        elif rt == "ATTEMPT_DISQUALIFIED":
            reason = resp.get("reason", "UNKNOWN")
            ctx = resp.get("context", {})
            print(f"\n!!! DISQUALIFIED: {reason}")
            print(f"    Game {ctx.get('gameOrdinal')}, move {ctx.get('lastRequiredMove')}")
            sys.exit(2)

        else:
            print(f"\nUnexpected responseType: {rt}")
            sys.exit(1)


if __name__ == "__main__":
    run()
