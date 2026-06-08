/**
 * One-time connect script. Run once to register the agent and get an agentId.
 * Writes key material to agent-auth-storage/ in the same file format the
 * @auth/agent-cli FileStorage uses, so `npx @auth/agent-cli sign <agentId>`
 * works out of the box after this.
 *
 * Usage: node connect.mjs
 */

import { AgentAuthClient } from "@auth/agent";
import { mkdirSync, readFileSync, writeFileSync, renameSync, unlinkSync, readdirSync } from "fs";
import { writeFileSync as writeFile } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const STORAGE_DIR = join(__dirname, "agent-auth-storage");
const SERVER = "https://intern-battleship-game-server.vercel.app";

// ── FileStorage compatible with @auth/agent-cli ────────────────────────────
class FileStorage {
  constructor(dir) {
    this.dir = dir;
    mkdirSync(join(dir, "agents"), { recursive: true });
    mkdirSync(join(dir, "providers"), { recursive: true });
  }
  encode(key) {
    return encodeURIComponent(key).replace(/%/g, "_");
  }
  readJSON(p) {
    try { return JSON.parse(readFileSync(p, "utf-8")); } catch { return null; }
  }
  writeJSON(p, data, secret = false) {
    const tmp = `${p}.${Date.now()}.tmp`;
    writeFileSync(tmp, JSON.stringify(data, null, 2), {
      encoding: "utf-8", mode: secret ? 0o600 : undefined,
    });
    renameSync(tmp, p);
  }

  // Host identity
  get hostPath() { return join(this.dir, "host.json"); }
  async getHostIdentity() { return this.readJSON(this.hostPath); }
  async setHostIdentity(h) { this.writeJSON(this.hostPath, h, true); }
  async deleteHostIdentity() { try { unlinkSync(this.hostPath); } catch {} }

  // Agent connection
  _agentPath(agentId) { return join(this.dir, "agents", `${this.encode(agentId)}.json`); }
  async getAgentConnection(agentId) { return this.readJSON(this._agentPath(agentId)); }
  async setAgentConnection(agentId, conn) { this.writeJSON(this._agentPath(agentId), conn, true); }
  async deleteAgentConnection(agentId) { try { unlinkSync(this._agentPath(agentId)); } catch {} }
  async listAgentConnections() {
    const files = (() => { try { return readdirSync(join(this.dir, "agents")); } catch { return []; } })();
    return files.filter(f => f.endsWith(".json"))
      .map(f => this.readJSON(join(this.dir, "agents", f))).filter(Boolean);
  }

  // Provider config
  _provPath(issuer) { return join(this.dir, "providers", `${this.encode(issuer)}.json`); }
  async getProviderConfig(issuer) { return this.readJSON(this._provPath(issuer)); }
  async setProviderConfig(issuer, cfg) { this.writeJSON(this._provPath(issuer), cfg); }
  async listProviderConfigs() {
    const files = (() => { try { return readdirSync(join(this.dir, "providers")); } catch { return []; } })();
    return files.filter(f => f.endsWith(".json"))
      .map(f => this.readJSON(join(this.dir, "providers", f))).filter(Boolean);
  }
}

// ── Connect ────────────────────────────────────────────────────────────────
const client = new AgentAuthClient({
  storage: new FileStorage(STORAGE_DIR),
  hostName: "Battleships Agent",
  allowDirectDiscovery: true,
  onApprovalRequired(info) {
    const url = info.verification_uri_complete ?? info.verification_uri;
    console.error("\n=== APPROVAL REQUIRED ===");
    console.error("Open this URL in your browser and approve:");
    console.error(url);
    if (info.user_code) console.error(`Code: ${info.user_code}`);
    console.error("Waiting for approval...\n");
  },
  onApprovalStatusChange(status) {
    console.error(`Status: ${status}`);
  },
});

console.error("Discovering provider...");
const provider = await client.discoverProvider(SERVER);
console.error(`Provider: ${provider.issuer}`);

console.error("Connecting agent (will prompt for browser approval)...");
const connected = await client.connectAgent({
  provider: provider.issuer,
  capabilities: [
    { name: "createAttempt" },
    { name: "getCurrentAttempt" },
    { name: "placeShips" },
    { name: "submitShot" },
    { name: "abandonAttempt" },
  ],
  loginHint: "neptunesparagon@gmail.com",
  name: "Battleships Agent",
});

const agentId = connected.agentId;
console.error(`\nConnected! agentId: ${agentId}`);

writeFile(join(__dirname, "agent_id.txt"), agentId, "utf-8");
console.error(`Written to agent_id.txt and agent-auth-storage/agents/`);
console.log(JSON.stringify({ agentId }, null, 2));
