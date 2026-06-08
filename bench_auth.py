"""
Fair comparison: sequential minting vs prefetch queue.

Both scenarios include the same simulated server delay so they measure
the same workload. Three server-delay values are tested:

  0.0s  — back-to-back (no server latency, worst case for prefetch)
  0.5s  — fast server
  1.0s  — realistic: real HTTPS + server processing (matches observed ~2s/shot
           minus the ~1s mint = ~1s server component)

No Attempt is created. Tokens are minted but never sent to the server.
"""

import time
import threading
import queue
import subprocess
import json
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(_DIR, "agent-auth-storage")
AGENT_ID_FILE = os.path.join(_DIR, "agent_id.txt")
CAP = "submitShot"


def get_agent_id() -> str:
    with open(AGENT_ID_FILE) as f:
        return f.read().strip()


def _mint_raw(agent_id: str, cap: str) -> str:
    result = subprocess.run(
        ["npx", "@auth/agent-cli", "--storage-dir", STORAGE_DIR,
         "sign", agent_id, "--capabilities", cap],
        capture_output=True, text=True, check=True, shell=True,
    )
    return json.loads(result.stdout)["token"]


def bench_sequential(agent_id: str, n: int, server_delay: float) -> float:
    """Mint n tokens one at a time, sleeping server_delay between each."""
    t0 = time.perf_counter()
    for _ in range(n):
        _mint_raw(agent_id, CAP)
        time.sleep(server_delay)
    return time.perf_counter() - t0


def _prefetcher(agent_id: str, cap: str, q: queue.Queue) -> None:
    while True:
        q.put(_mint_raw(agent_id, cap))


def bench_prefetch(agent_id: str, n: int, server_delay: float) -> tuple[float, float]:
    """
    Use prefetch queue for n tokens, sleeping server_delay between each.
    Returns (total_time, avg_queue_wait_ms).
    """
    q: queue.Queue = queue.Queue(maxsize=2)
    threading.Thread(target=_prefetcher, args=(agent_id, CAP, q), daemon=True).start()

    t0 = time.perf_counter()
    total_wait = 0.0
    for _ in range(n):
        w0 = time.perf_counter()
        q.get()
        total_wait += time.perf_counter() - w0
        time.sleep(server_delay)
    total = time.perf_counter() - t0
    return total, total_wait / n * 1000


def main() -> None:
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    agent_id = get_agent_id()
    print(f"Agent: {agent_id[:16]}...")
    print(f"N={N} tokens per scenario\n")

    print("Warming up npx cache ...", flush=True)
    t_w = time.perf_counter()
    _mint_raw(agent_id, CAP)
    mint_ms = (time.perf_counter() - t_w) * 1000
    print(f"  warm-up: {mint_ms:.0f} ms  (single mint baseline)\n")

    delays = [0.0, 0.5, 1.0]
    results: dict[str, dict] = {}

    for delay in delays:
        label = f"{delay:.1f}s server delay"
        print(f"--- {label} ---", flush=True)

        seq = bench_sequential(agent_id, N, delay)
        print(f"  sequential: {seq:.2f}s total  ({seq/N*1000:.0f} ms/shot)", flush=True)

        pf, avg_wait = bench_prefetch(agent_id, N, delay)
        print(f"  prefetch:   {pf:.2f}s total  ({pf/N*1000:.0f} ms/shot)  "
              f"avg queue_wait={avg_wait:.0f}ms\n", flush=True)

        results[label] = {"seq": seq, "pf": pf, "avg_wait_ms": avg_wait,
                          "per_seq": seq / N, "per_pf": pf / N}

    print(f"\n{'='*60}")
    print(f"  SUMMARY — {N} tokens, full-attempt projection ({N*15} shots)")
    print(f"{'='*60}")
    print(f"  {'Scenario':<22}  {'Seq':>8}  {'Prefetch':>8}  {'Saving':>8}  {'Attempt old':>12}  {'Attempt new':>12}")
    print(f"  {'-'*22}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*12}  {'-'*12}")
    for label, r in results.items():
        saving_pct = 100 * (r["per_seq"] - r["per_pf"]) / r["per_seq"]
        old_min = r["per_seq"] * N * 15 / 60
        new_min = r["per_pf"] * N * 15 / 60
        print(f"  {label:<22}  {r['per_seq']*1000:>7.0f}ms  {r['per_pf']*1000:>7.0f}ms"
              f"  {saving_pct:>+7.0f}%  {old_min:>11.1f}m  {new_min:>11.1f}m")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
