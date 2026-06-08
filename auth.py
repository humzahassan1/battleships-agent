"""
Auth wrapper: shells out to @auth/agent-cli to mint single-use JWTs.
Each call produces a fresh token (jti replay protection requires it).
"""

import json
import os
import subprocess

_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(_DIR, "agent-auth-storage")
AGENT_ID_FILE = os.path.join(_DIR, "agent_id.txt")


def get_agent_id() -> str:
    with open(AGENT_ID_FILE) as f:
        return f.read().strip()


def mint_token(agent_id: str, capability: str) -> str:
    """Return a fresh signed JWT asserting the given capability."""
    # On Windows, npx resolves to npx.cmd (a batch script). CreateProcess
    # can't run .cmd files directly — shell=True routes through cmd.exe.
    result = subprocess.run(
        [
            "npx", "@auth/agent-cli",
            "--storage-dir", STORAGE_DIR,
            "sign", agent_id,
            "--capabilities", capability,
        ],
        capture_output=True,
        text=True,
        check=True,
        shell=True,
    )
    return json.loads(result.stdout)["token"]


def auth_header(agent_id: str, capability: str) -> dict:
    return {"Authorization": f"Bearer {mint_token(agent_id, capability)}"}
