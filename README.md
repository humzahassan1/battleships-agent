# Battleships Agent

A Python agent that plays competitive Battleships via a REST/JWT API. Scored **260** (9W/6L) in the most recent complete attempt, up from a 235 baseline.

## Architecture

```
agent.py          envelope state-machine loop (MOVE_REQUIRED → GAME_COMPLETED → ATTEMPT_COMPLETED)
client.py         typed HTTP wrappers for all six API routes; retries on transient network errors
auth.py           IPC with signer.mjs; prefetch queue for submitShot tokens
signer.mjs        persistent Node.js process — signs JWTs in ~2ms, stays alive for the full run
strategy.py       ship placement (spaced, 1-cell buffer) + density-based firing model
simulator.py      local 15-game opponent for offline testing, no credentials needed
benchmark.py      offline benchmarks: firing efficiency + placement survival
attempts.jsonl    append-only score log; auto-committed after every attempt
```

### Auth: persistent signer

Each API call requires a single-use JWT (`submitShot`, `placeShips`, etc.) minted by the `@auth/agent-cli` package. The naïve approach — spawning `npx @auth/agent-cli sign …` per shot — costs ~960ms/token on Windows (process startup), totalling ~20 minutes per attempt and occasionally exceeding the server's 10-second turn timeout.

`signer.mjs` starts once at the top of the run, loads the stored agent keypair, and signs tokens via `signAgentJWT` from `@auth/agent`. Subsequent mints take ~2ms. `auth.py` communicates with it over stdin/stdout (newline-delimited JSON), holding a threading lock to serialise requests. A background daemon thread pre-fills a queue of size 2 for `submitShot` tokens so the main loop never waits.

### Firing: probability-density model

`strategy.py::choose_shot_density` maintains a probability grid. Each unsunk ship class contributes probability mass to every cell it could legally occupy given current hits and misses. On a hit, the model floods weight along the hit's row/column. This produces aggressive hunt-then-target behaviour without hardcoded rules.

Benchmark: density model sinks the opponent fleet in an average of **47.9 shots** vs **56.7 shots** for a random baseline on a 10×10 board with the standard fleet.

### Placement: spaced with 1-cell buffer

`choose_layout` enforces an 8-directional forbidden zone around each placed ship so no two ships can be adjacent or diagonal. This forces the opponent's density attacker to fully exhaust each hunt cycle before finding the next ship.

Offline survival benchmark: spaced placement requires **50.3 shots** to sink (vs **47.9** for random — ~5% harder to hunt), with the minimum floor rising from 26 to 31 shots. Small but consistent.

## Optimization story

| Attempt | Score | W/L | Notes |
|---------|-------|-----|-------|
| Baseline | 235 | 8/7 | random placement, per-shot npx (~20 min/attempt) |
| — | DQ×2 | — | TIMEOUT: npx occasionally >10s per token |
| Current | **260** | 9/6 | spaced placement + persistent signer |

**Diagnosis after 235:** Sank 64 opponent ships but lost 62 of my own — offense was already strong, defense was the bottleneck. Random placement lets opponents chain-hunt adjacent ships.

**Fix 1 — placement:** Offline survival benchmark confirmed spaced placement is consistently harder to hunt. Implemented with a 2000-retry per-ship loop and a no-buffer fallback.

**Fix 2 — token minting:** Two attempts DQ'd with `TIMEOUT` at mid-game shots when npx took >10s. Replaced the subprocess approach with `signer.mjs`, a persistent Node process that signs via the SDK directly. Per-token cost dropped from ~960ms to ~2ms; no timeout risk.

## Running

```bash
# Real attempt (requires agent credentials in agent-auth-storage/)
python agent.py
python agent.py --note "description of what changed"

# Offline benchmarks (no server needed)
python benchmark.py

# Local simulator (15 games, no credentials)
python simulator.py   # terminal 1
python agent.py       # terminal 2 (BASE_URL=http://localhost:8765)
```

## Score log

`attempts.jsonl` is an append-only JSONL file with one record per attempt. Every completion (win or DQ) triggers an automatic `git commit` so no result is ever lost.

```jsonl
{"timestamp": "...", "finalScore": 260, "wins": 9, "losses": 6,
 "opponentShipsSunk": 65, "agentShipsLost": 61, "hitDifferential": 15,
 "isNewBest": true, "note": "spaced placement +1-cell buffer, persistent signer"}
```
