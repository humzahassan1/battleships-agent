# Battleships Agent

A Python agent that plays competitive Battleships via a REST/JWT API. Current best: **424** (13W/2L, agentShipsLost 58).

## Architecture

```
agent.py          envelope state-machine loop (MOVE_REQUIRED → GAME_COMPLETED → ATTEMPT_COMPLETED)
client.py         typed HTTP wrappers for all six API routes; retries on transient network errors
auth.py           IPC with signer.mjs; prefetch queue for submitShot tokens
signer.mjs        persistent Node.js process — signs JWTs in ~2ms, stays alive for the full run
strategy.py       ship placement (edge-biased, 1-cell buffer) + density+parity firing model
simulator.py      local 15-game opponent for offline testing, no credentials needed
benchmark.py      offline benchmarks: firing efficiency + placement survival
attempts.jsonl    append-only score log; auto-committed and pushed after every attempt
```

### Auth: persistent signer

Each API call requires a single-use JWT minted by the `@auth/agent-cli` package. The naïve approach — spawning `npx @auth/agent-cli sign …` per shot — costs ~960ms/token on Windows, totalling ~20 minutes per attempt and occasionally exceeding the server's 10-second turn timeout (TIMEOUT DQ).

`signer.mjs` starts once at the top of the run, loads the stored agent keypair, and signs tokens via `signAgentJWT` from `@auth/agent`. Subsequent mints take ~2ms. `auth.py` communicates with it over stdin/stdout (newline-delimited JSON), holding a threading lock to serialise requests. A background daemon thread pre-fills a queue of size 2 for `submitShot` tokens so the main loop never waits. A stderr-drain thread and a 5-second readline timeout ensure a hung signer is detected and restarted within the server's 10-second turn deadline.

### Firing: probability-density + parity hunt

`strategy.py::choose_shot_density` maintains a probability grid over all remaining ship placements:

- **Hunt mode** (no active hits): restricted to the even-parity checkerboard `(r+c)%2==0`. Every ship of length ≥ 2 spans at least one even-parity cell, so no ship can be missed while visiting only half the board. This roughly halves hunt-phase shots.
- **Target mode** (unresolved hits present): all placements covering a hit cell receive a 100× weight bonus, driving the model to extend along the wounded ship before resuming the hunt.

Benchmark: density+parity model sinks the opponent fleet in an average of **~40 shots** vs **56.7 shots** for a random baseline on a 10×10 board with the standard fleet.

### Placement: edge-biased with 1-cell buffer

`choose_layout` enforces an 8-directional forbidden zone around each placed ship (no adjacent ships) and biases positions toward the board edges: horizontal ships prefer rows 0/1/8/9, vertical ships prefer cols 0/1/8/9.

This exploits how density attackers work: interior cells receive higher probability mass because more ship placements pass through them. Ships at the edges have lower initial density scores, so opponents hunt the center first and waste shots. Combined with the 1-cell buffer, each ship must be fully exhausted before the next can be chain-hunted.

## Optimization story

| Attempt | Score | W/L | What changed |
|---------|-------|-----|-------------|
| Baseline | 235 | 8/7 | random placement, per-shot npx (~20 min/attempt) |
| — | DQ×2 | — | TIMEOUT: npx occasionally >10s per token |
| Spaced placement | 260 | 9/6 | 1-cell buffer between ships, persistent signer |
| — | 344 | 10/5 | variance / better opponent draw |
| Edge-biased placement | 391 | 11/4 | ships near edges, opponents hunt center first |
| **Best so far** | **424** | **13/2** | edge-biased + parity hunt firing |

**235 → diagnosed:** Sank 64 opponent ships but lost 62 of my own. Offense was already strong; defense was the bottleneck. Random placement lets opponents chain-hunt adjacent ships.

**Fix 1 — spaced placement:** Enforce 1-cell buffer so each ship must be found independently. +25 points.

**Fix 2 — persistent signer:** Two attempts DQ'd with TIMEOUT mid-game when npx took >10s. Replaced per-shot subprocess with `signer.mjs`, a persistent Node process. Per-token cost: ~960ms → ~2ms. No more timeout DQs.

**Fix 3 — edge-biased placement:** Density attackers score interior cells highest. Placing ships at the board periphery forces opponents to waste shots in the center before finding the fleet. agentShipsLost dropped 62 → 56, wins went 9 → 11. +131 points over the post-signer baseline.

**Fix 4 — parity hunt:** Restricted hunt-mode firing to the even-parity checkerboard. Every ship spans ≥1 even-parity cell so nothing is missed; hunt-phase shots roughly halved. Offense efficiency up.

## Running

```bash
# Real attempt (requires agent credentials in agent-auth-storage/)
python agent.py
python agent.py --note "description of what changed"

# Offline benchmarks (no server needed)
python benchmark.py

# Local simulator (15 games, no credentials)
python simulator.py   # terminal 1
BASE_URL=http://localhost:8765 python agent.py  # terminal 2
```

## Score log

`attempts.jsonl` is an append-only JSONL file. Every completion (scored or DQ) triggers an automatic `git commit` + `git push` so no result is ever lost.

```jsonl
{"timestamp": "...", "finalScore": 391, "wins": 11, "losses": 4,
 "opponentShipsSunk": 71, "agentShipsLost": 56, "hitDifferential": 15,
 "isNewBest": true, "note": "edge-biased placement + signer hang fix"}
```
