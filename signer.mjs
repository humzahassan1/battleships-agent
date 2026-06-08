/**
 * Persistent JWT signer — long-lived Node process.
 * Python auth.py sends one JSON line per token request:
 *   {"agentId": "...", "capability": "..."}
 * This process responds with one JSON line:
 *   {"token": "..."} or {"error": "..."}
 *
 * Staying alive eliminates the ~2-3s Node startup cost on every shot.
 * Storage dir is passed via AGENT_AUTH_STORAGE_DIR env var.
 */

import { signAgentJWT } from "@auth/agent";
import { readFileSync } from "fs";
import { join } from "path";
import * as readline from "readline";

const STORAGE_DIR = process.env.AGENT_AUTH_STORAGE_DIR;
if (!STORAGE_DIR) {
  process.stderr.write("ERROR: AGENT_AUTH_STORAGE_DIR not set\n");
  process.exit(1);
}

function encodeId(id) {
  return encodeURIComponent(id).replace(/%/g, "_");
}

const connCache = new Map();

function loadConn(agentId) {
  if (connCache.has(agentId)) return connCache.get(agentId);
  const p = join(STORAGE_DIR, "agents", `${encodeId(agentId)}.json`);
  const conn = JSON.parse(readFileSync(p, "utf-8"));
  connCache.set(agentId, conn);
  return conn;
}

// Process one request at a time — Python serializes with a lock anyway,
// but this queue ensures stdin bursts don't interleave responses.
let pending = Promise.resolve();

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

rl.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  pending = pending.then(async () => {
    try {
      const { agentId, capability } = JSON.parse(trimmed);
      const conn = loadConn(agentId);
      const token = await signAgentJWT({
        agentKeypair: conn.agentKeypair,
        agentId: conn.agentId,
        audience: conn.issuer,
        capabilities: [capability],
      });
      process.stdout.write(JSON.stringify({ token }) + "\n");
    } catch (err) {
      process.stdout.write(JSON.stringify({ error: String(err?.message ?? err) }) + "\n");
    }
  });
});

rl.on("close", () => pending.then(() => process.exit(0)));

process.stderr.write("signer ready\n");
