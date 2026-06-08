"""
Auth wrapper: persistent Node.js signer process for single-use JWTs.
signer.mjs stays alive for the duration of the run — no per-token process
startup cost (~2-3s on Windows) on the critical path.

A background daemon thread for submitShot pre-mints tokens into a small queue
to overlap signing with server round-trips.  All other capabilities mint
directly (called at most once per game, no expiry risk from queueing).

Reliability:
  - stderr drain thread prevents Node's event loop from blocking on a full pipe
  - Warm spare: a second signer process is always pre-started in the background.
    On hang (detected in 2s), we swap in the spare instantly and start a new spare.
    This removes the ~3s Node cold-start from the recovery critical path.
"""
import json
import os
import queue
import subprocess
import threading

_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(_DIR, "agent-auth-storage")
AGENT_ID_FILE = os.path.join(_DIR, "agent_id.txt")
_SIGNER_JS = os.path.join(_DIR, "signer.mjs")

_signer_proc: "subprocess.Popen | None" = None
_signer_lock = threading.Lock()   # serializes all stdin/stdout IPC

_spare_proc: "subprocess.Popen | None" = None
_spare_lock = threading.Lock()

_queues: "dict[str, queue.Queue]" = {}
_queues_lock = threading.Lock()


def get_agent_id() -> str:
    with open(AGENT_ID_FILE) as f:
        return f.read().strip()


def _drain_stderr(proc: subprocess.Popen) -> None:
    """Drain Node's stderr so the pipe never fills and blocks its event loop."""
    try:
        while proc.poll() is None:
            proc.stderr.read(4096)
    except Exception:
        pass


def _start_signer() -> subprocess.Popen:
    env = {**os.environ, "AGENT_AUTH_STORAGE_DIR": STORAGE_DIR}
    proc = subprocess.Popen(
        ["node", _SIGNER_JS],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=_DIR,
        env=env,
    )
    ready = proc.stderr.readline()
    if not ready:
        raise RuntimeError("signer.mjs exited before signalling ready")
    threading.Thread(target=_drain_stderr, args=(proc,), daemon=True).start()
    return proc


def _warm_spare() -> None:
    """Start a fresh signer and cache it as the spare. Runs in background thread."""
    global _spare_proc
    try:
        proc = _start_signer()
        with _spare_lock:
            if _spare_proc is not None:
                try:
                    _spare_proc.kill()
                except Exception:
                    pass
            _spare_proc = proc
    except Exception:
        pass


def _get_fresh_signer() -> subprocess.Popen:
    """Return the warm spare instantly (if ready), else cold-start. Always replenishes spare."""
    global _spare_proc
    with _spare_lock:
        if _spare_proc is not None:
            proc = _spare_proc
            _spare_proc = None
            threading.Thread(target=_warm_spare, daemon=True).start()
            return proc
    # No spare ready — cold-start synchronously and kick off a new spare
    proc = _start_signer()
    threading.Thread(target=_warm_spare, daemon=True).start()
    return proc


def _read_line_with_timeout(stream, timeout: float) -> "bytes | None":
    """readline() with a wall-clock timeout. Returns None if timeout expires."""
    result: list[bytes] = []
    done = threading.Event()

    def _reader() -> None:
        try:
            result.append(stream.readline())
        except Exception:
            result.append(b"")
        done.set()

    threading.Thread(target=_reader, daemon=True).start()
    done.wait(timeout)
    return result[0] if result else None


def _mint_raw(agent_id: str, capability: str) -> str:
    global _signer_proc
    with _signer_lock:
        for attempt in range(2):
            if _signer_proc is None or _signer_proc.poll() is not None:
                _signer_proc = _get_fresh_signer()

            req = json.dumps({"agentId": agent_id, "capability": capability}) + "\n"
            _signer_proc.stdin.write(req.encode())
            _signer_proc.stdin.flush()

            resp_bytes = _read_line_with_timeout(_signer_proc.stdout, timeout=2.0)

            if not resp_bytes or not resp_bytes.strip():
                # Hung — swap in the warm spare (instant) and retry
                try:
                    _signer_proc.kill()
                except Exception:
                    pass
                _signer_proc = None
                continue

            resp = json.loads(resp_bytes.decode().strip())
            if "error" in resp:
                raise RuntimeError(f"signer error: {resp['error']}")
            return resp["token"]

    raise RuntimeError("signer failed to respond after restart")


def _prefetcher(agent_id: str, capability: str, q: queue.Queue) -> None:
    while True:
        token = _mint_raw(agent_id, capability)
        q.put(token)  # blocks when full (maxsize=2), preventing wasted mints


def mint_token(agent_id: str, capability: str) -> str:
    """Return a signed JWT for the given capability.

    submitShot is called ~50x per game so it uses a prefetch queue.
    All other capabilities mint directly — queueing them risks expiry between games.
    """
    if capability != "submitShot":
        return _mint_raw(agent_id, capability)

    key = f"{agent_id}:{capability}"
    with _queues_lock:
        if key not in _queues:
            q: queue.Queue = queue.Queue(maxsize=2)
            _queues[key] = q
            threading.Thread(
                target=_prefetcher, args=(agent_id, capability, q), daemon=True
            ).start()
    return _queues[key].get()


def auth_header(agent_id: str, capability: str) -> dict:
    return {"Authorization": f"Bearer {mint_token(agent_id, capability)}"}


# Pre-warm a spare signer at import time so it's ready before the first hang.
threading.Thread(target=_warm_spare, daemon=True).start()
