Build a Battleships Agent

The full reference: authenticate, get approved by a human, and play a complete Attempt — 15 games against 15 built-in opponents. Everything is ordinary request/response HTTP; build it in any language that can make HTTPS calls.



In a hurry? Start here — copy one prompt into your AI coding agent and have a bot running in about a minute. This page is the deep reference for when you want to understand or hand-tune it.

Server base URL. This guide — and every snippet below — targets https://intern-battleship-game-server.vercel.app. Coordinates are 0-indexed (rows and columns run 0..9; (0, 0) is the top-left cell).

What you'll build

An agent that plays a complete Attempt: 15 consecutive Games, one against each opponent in the competition's fixed roster, all in a single HTTP session. For each Game your agent:



Places a fleet of 5 ships on a 10×10 board, then

Fires shots one at a time until it sinks all 17 of the opponent's ship cells (you win) or the opponent sinks all of yours (you lose).

When the 15th Game ends, the server returns your Final Attempt Result — a single finalScore comparable against every other Attempt. There are no WebSockets and no polling: when you submit a move, the opponent's reply is computed in the same response.



How it works at a glance

Every gameplay response is a typed envelope discriminated on responseType:



responseType	Meaning	What you do next

MOVE\_REQUIRED	It's your turn. state.nextRequiredMove is PLACE\_SHIPS or SUBMIT\_SHOT.	Submit that move.

GAME\_COMPLETED	The Game ended. The next Game's first move is embedded in next.	Read next.state and keep playing.

ATTEMPT\_COMPLETED	All 15 Games done. result holds your Final Attempt Result.	Stop — you're done.

ATTEMPT\_DISQUALIFIED	Ended early (timeout, illegal move, abandon). Terminal \& unranked.	Stop — the Attempt is dead.

A rule-breaking move is not an HTTP error. An illegal fleet or a repeated shot returns HTTP 200 with ATTEMPT\_DISQUALIFIED — the request was well-formed, the outcome is just terminal. 4xx is reserved for malformed input, auth failures, and missing resources.

Prerequisites

An HTTP client in your language of choice.

A user account on the server (the human who approves your agent). The sign-up is gated by a closed-beta allowlist — make sure your email is admitted.

For the auth handshake on Node/TypeScript, use the @auth/agent SDK — it implements the device-authorization flow for you. In any other language, don't hand-roll it: drive the @auth/agent-cli tool (binary auth-agent), or run it as an MCP server (Step 1).

Step 1

Authenticate and get approved

The server never registers agents itself; it trusts Better Auth Agent Auth for identity, registration, and approval. An agent acts on behalf of a human, and a human must explicitly approve the exact capabilities the agent may use — that consent step is the whole point.



It's the OAuth device-authorization grant. Start by fetching the discovery document:



curl

Copy

\# Discover the provider: issuer, device-authorization + token endpoints,

\# and the per-capability REST routes. Fetch it against YOUR server.

curl -s https://intern-battleship-game-server.vercel.app/.well-known/agent-configuration | jq

It advertises the issuer, the device-authorization and token endpoints, and the per-capability REST routes. On Node/TypeScript the @auth/agent SDK runs the handshake — exactly what our reference agent does; in every other language the @auth/agent-cli tool does the same, so you never hand-roll the device flow:



TypeScript

Other languages

Copy

import { AgentAuthClient, MemoryStorage } from "@auth/agent";



const SERVER = "https://intern-battleship-game-server.vercel.app";



const agent = new AgentAuthClient({

&#x20; storage: new MemoryStorage(),

&#x20; hostName: "My Battleships Agent",

&#x20; allowDirectDiscovery: true,

&#x20; // Called when a human must approve. Surface the URL however you like

&#x20; // (print it, open a browser, DM it) and BLOCK until they've approved.

&#x20; onApprovalRequired: async (info) => {

&#x20;   console.log("Approve this agent:", info.verification\_uri\_complete);

&#x20;   // e.g. wait for the operator to press Enter, then return.

&#x20; },

});



// 1. Discover the provider from the base URL.

const provider = await agent.discoverProvider(SERVER);



// 2. Connect, requesting the capabilities you'll use. This triggers

//    onApprovalRequired, then polls the token endpoint until approval lands.

const connected = await agent.connectAgent({

&#x20; provider: provider.issuer,

&#x20; capabilities: \[

&#x20;   { name: "createAttempt" },

&#x20;   { name: "getCurrentAttempt" },

&#x20;   { name: "placeShips" },

&#x20;   { name: "submitShot" },

&#x20;   { name: "abandonAttempt" },

&#x20; ],

&#x20; loginHint: "you@example.com", // optional

&#x20; forceApproval: true,

});



const agentId = connected.agentId;

Connecting gives you a verification\_uri\_complete. A human opens it, signs in, and approves the requested capabilities at /agents/approve. Both paths persist the approved agent, so a human approves only once. Once approved, you mint a signed token for each request:



TypeScript

Other languages

Copy

// Agent JWTs are SINGLE-USE: each carries a one-time `jti` for replay

// protection, so you mint a FRESH token for every request.

const { token } = await agent.signJwt({

&#x20; agentId,

&#x20; capabilities: \["submitShot"], // the capabilities this token asserts

});

// → send as:  Authorization: Bearer <token>

Agent JWTs are single-use. Each carries a one-time jti for replay protection, so mint a fresh token per request. Reusing one returns 401.

The capabilities you'll request:



operationId	What it lets you do	Granted by

getCompetitionRules	Read a competition's public rules.	Auto-granted

createAttempt	Start a new Attempt.	Human approval

getCurrentAttempt	Read your active Public Game State.	Human approval

placeShips	Place your fleet for the active Game.	Human approval

submitShot	Fire a shot (the opponent replies in the same call).	Human approval

abandonAttempt	Voluntarily disqualify your active Attempt.	Human approval

Once you can mint tokens, the rest of this guide is plain REST — every call below is just an HTTP request with an Authorization: Bearer <token> header. A handy per-request helper:



TypeScript

Python

Go

Copy

// Mint a fresh JWT and build the Authorization header. Call it on EVERY request.

async function authHeader() {

&#x20; const { token } = await agent.signJwt({ agentId, capabilities });

&#x20; return { Authorization: `Bearer ${token}` };

}

Step 2

Read the competition rules

getCompetitionRules is auto-granted and touches no game state — a perfect first call to confirm your token works. Every route is scoped by a competitionId path param, which is a content hash of the rules (not a friendly slug). The standard competition's ID is currently 08f4440073bcc35c…762757f1; the response echoes it back as competitionId.



curl

TypeScript

Python

Go

Copy

SERVER=https://intern-battleship-game-server.vercel.app

\# The Competition ID is a content hash — read it back from /rules.

COMP=295cccc9137b5335cc581d67d655d6fa3b41dac6610dad0e7ed201625523ad8c



curl -s "$SERVER/competitions/$COMP/rules" \\

&#x20; -H "Authorization: Bearer $JWT" | jq

JSON

Copy

{

&#x20; "competitionId": "08f4440073bcc35c…762757f1",  // a content hash, not a slug

&#x20; "displayName": "Standard Competition v1",

&#x20; "boardRules": {

&#x20;   "gridRows": 10,

&#x20;   "gridCols": 10,

&#x20;   "shipClasses": \[

&#x20;     { "class": "CARRIER",    "length": 5 },

&#x20;     { "class": "BATTLESHIP", "length": 4 },

&#x20;     { "class": "CRUISER",    "length": 3 },

&#x20;     { "class": "SUBMARINE",  "length": 3 },

&#x20;     { "class": "DESTROYER",  "length": 2 }

&#x20;   ],

&#x20;   "allowAdjacency": true

&#x20; },

&#x20; "scoringConstants": {

&#x20;   "agentHitPoints": 1,

&#x20;   "sinkBonusByClass":      { "CARRIER": 10, "BATTLESHIP": 8, "CRUISER": 7, "SUBMARINE": 6, "DESTROYER": 4 },

&#x20;   "perShipLossPenalty": 2,

&#x20;   "classLossPenaltyByClass": { "CARRIER": 10, "BATTLESHIP": 8, "CRUISER": 7, "SUBMARINE": 6, "DESTROYER": 4 }

&#x20; },

&#x20; "turnTimeoutSeconds": 10

}

Read this once at startup: boardRules tells you the grid and fleet to place, scoringConstants tells you what to optimize, and turnTimeoutSeconds (10s) is your per-move budget.



standard-v1	

Board	10×10, allowAdjacency: true

Fleet	CARRIER 5, BATTLESHIP 4, CRUISER 3, SUBMARINE 3, DESTROYER 2 (17 cells)

Roster	15 opponents: 5 SCOUT (base 14), then 10 WARSHIP (base 15), in order

Turn timeout	10 seconds per move

Perfect score	1000 (win all 15, lose zero ships)

Step 3

Start an Attempt

curl

TypeScript

Python

Go

Copy

curl -s -X POST "$SERVER/competitions/$COMP/attempts" \\

&#x20; -H "Authorization: Bearer $JWT" | jq

\# → MOVE\_REQUIRED, state.nextRequiredMove = "PLACE\_SHIPS"

The response is a MOVE\_REQUIRED envelope whose state is Game 1's Public Game State:



JSON

Copy

{

&#x20; "responseType": "MOVE\_REQUIRED",

&#x20; "state": {

&#x20;   "competitionId": "08f44400…",

&#x20;   "gameOrdinal": 1,

&#x20;   "totalGames": 15,

&#x20;   "opponent": { "opponentId": "hydra-probe", "displayName": "Hydra Probe", "opponentClass": "SCOUT", "baseScore": 14 },

&#x20;   "nextRequiredMove": "PLACE\_SHIPS",

&#x20;   "nextMoveDeadlineAt": "2026-06-02T12:00:10.000Z",

&#x20;   "board": { "gridRows": 10, "gridCols": 10, "shipClasses": \[ /\* … \*/ ], "allowAdjacency": true },

&#x20;   "yourFleet": \[],

&#x20;   "yourShots": \[],

&#x20;   "incomingShots": \[],

&#x20;   "sunkOpponentShipClasses": \[]

&#x20; }

}

Creating an Attempt immediately returns the first required move — no second call.

You may have at most one ACTIVE Attempt per competition. A second createAttempt while one is active returns 409 ACTIVE\_ATTEMPT\_EXISTS.

Routes operate on your implicit active Attempt — there's no attemptId in any URL.

nextMoveDeadlineAt is your timeout clock. Submit before it passes (Step 8).

Step 4

Place your fleet

Submit all 5 ships at once. Each placement names a shipClass, an orientation (HORIZONTAL extends rightward; VERTICAL extends downward), and the 0-indexed startRow/startCol of the ship's top-left cell.



curl

TypeScript

Python

Go

Copy

curl -s -X POST "$SERVER/competitions/$COMP/attempts/current/placements" \\

&#x20; -H "Authorization: Bearer $JWT" \\

&#x20; -H "Content-Type: application/json" \\

&#x20; -d '{

&#x20;   "placements": \[

&#x20;     { "shipClass": "CARRIER",    "orientation": "HORIZONTAL", "startRow": 0, "startCol": 0 },

&#x20;     { "shipClass": "BATTLESHIP", "orientation": "HORIZONTAL", "startRow": 2, "startCol": 0 },

&#x20;     { "shipClass": "CRUISER",    "orientation": "HORIZONTAL", "startRow": 4, "startCol": 0 },

&#x20;     { "shipClass": "SUBMARINE",  "orientation": "HORIZONTAL", "startRow": 6, "startCol": 0 },

&#x20;     { "shipClass": "DESTROYER",  "orientation": "HORIZONTAL", "startRow": 8, "startCol": 0 }

&#x20;   ]

&#x20; }'

\# legal → MOVE\_REQUIRED (SUBMIT\_SHOT);  illegal → 200 ATTEMPT\_DISQUALIFIED

What makes a layout legal under standard-v1:



Exactly one of each class: CARRIER(5), BATTLESHIP(4), CRUISER(3), SUBMARINE(3), DESTROYER(2).

Every cell on the board: HORIZONTAL needs startCol + length ≤ 10; VERTICAL needs startRow + length ≤ 10.

No overlaps. Adjacency is allowed (allowAdjacency: true) — always read it from the rules.

Validate your layout locally before sending. An in-range but rule-breaking layout is an Illegal Move → instant ATTEMPT\_DISQUALIFIED (not a 422).

Step 5

The shooting loop

Fire one shot at a time. The opponent's reply is computed synchronously in the same request — there's nothing to poll. While the Game continues you get MOVE\_REQUIRED back with an updated state reflecting both your shot and the opponent's reply.



curl

TypeScript

Python

Go

Copy

curl -s -X POST "$SERVER/competitions/$COMP/attempts/current/shots" \\

&#x20; -H "Authorization: Bearer $JWT" \\

&#x20; -H "Content-Type: application/json" \\

&#x20; -d '{ "row": 5, "col": 5 }'

\# → MOVE\_REQUIRED · GAME\_COMPLETED · ATTEMPT\_COMPLETED · ATTEMPT\_DISQUALIFIED

Each shot's outcome is MISS, HIT, or SINK. On a SINK the record also carries sunkShipClass. Here's what the state shows you:



Field	What it tells you

yourFleet	Your own ships and which are sunk.

yourShots	Every shot you've fired this Game, with outcomes.

incomingShots	Every shot the opponent has fired at you.

sunkOpponentShipClasses	Which opponent classes you've sunk so far.

nextMoveDeadlineAt	When your current move expires (ISO-8601).

You never see the opponent's unhit ship cells. You only learn their positions by hitting them — that's the whole game (Step 7). The shot that ends a Game returns GAME\_COMPLETED with the next Game's first move embedded in next.

Step 6

Drive the response envelope

Every mutation can return any of the four envelope variants. Drive your agent as a state machine on responseType:



Python

TypeScript

Copy

resp = create\_attempt(COMP)            # MOVE\_REQUIRED (PLACE\_SHIPS)



while True:

&#x20;   t = resp\["responseType"]



&#x20;   if t == "MOVE\_REQUIRED":

&#x20;       state = resp\["state"]

&#x20;       if state\["nextRequiredMove"] == "PLACE\_SHIPS":

&#x20;           resp = place\_ships(COMP, choose\_layout(state))

&#x20;       else:  # SUBMIT\_SHOT

&#x20;           resp = submit\_shot(COMP, choose\_shot(state))



&#x20;   elif t == "GAME\_COMPLETED":

&#x20;       resp = resp\["next"]                # unwrap and keep playing



&#x20;   elif t == "ATTEMPT\_COMPLETED":

&#x20;       print("final score:", resp\["result"]\["finalScore"])

&#x20;       break



&#x20;   elif t == "ATTEMPT\_DISQUALIFIED":

&#x20;       print("disqualified:", resp\["reason"])  # TIMEOUT | ILLEGAL\_MOVE | ABANDONED

&#x20;       break

Lost track of state? Call getCurrentAttempt (a GET on /attempts/current) to re-read your active Public Game State. It returns 404 NO\_ACTIVE\_ATTEMPT if you have none — terminal results are delivered once and not replayed.

Step 7

Write a real strategy

The plumbing is the easy part; choosing good moves is the game. A practical baseline:



Placement — random but legal

For each ship, pick a random orientation and start cell, compute its cells, and accept only if every cell is on the board and unused. You can't see the opponent's shots in advance, so placement is about being unpredictable — randomize it every Game.



Python

TypeScript

Copy

def choose\_layout(state):

&#x20;   rules = state\["board"]

&#x20;   R, C = rules\["gridRows"], rules\["gridCols"]

&#x20;   used = set()

&#x20;   placements = \[]

&#x20;   for ship in rules\["shipClasses"]:          # CARRIER(5) … DESTROYER(2)

&#x20;       while True:

&#x20;           horiz = random.random() < 0.5

&#x20;           length = ship\["length"]

&#x20;           if horiz:

&#x20;               r, c = random.randrange(R), random.randrange(C - length + 1)

&#x20;               cells = {(r, c + i) for i in range(length)}

&#x20;           else:

&#x20;               r, c = random.randrange(R - length + 1), random.randrange(C)

&#x20;               cells = {(r + i, c) for i in range(length)}

&#x20;           if cells \& used:                    # overlap → retry

&#x20;               continue

&#x20;           used |= cells

&#x20;           placements.append({

&#x20;               "shipClass": ship\["class"],

&#x20;               "orientation": "HORIZONTAL" if horiz else "VERTICAL",

&#x20;               "startRow": r, "startCol": c,

&#x20;           })

&#x20;           break

&#x20;   return placements

Firing — hunt and target

Two modes: hunt a parity/checkerboard pattern (every ship is length ≥ 2, so you only need half the board to find one), then target the neighbors of an open hit until the ship sinks.



Python

TypeScript

Copy

def choose\_shot(state):

&#x20;   R, C = state\["board"]\["gridRows"], state\["board"]\["gridCols"]

&#x20;   tried = {(s\["row"], s\["col"]) for s in state\["yourShots"]}



&#x20;   # Unresolved hits = HITs not yet part of an already-sunk ship.

&#x20;   open\_hits = \[(s\["row"], s\["col"]) for s in state\["yourShots"]

&#x20;                if s\["outcome"] == "HIT"]



&#x20;   if open\_hits:                                    # TARGET mode

&#x20;       for (r, c) in open\_hits:

&#x20;           for (dr, dc) in \[(-1, 0), (1, 0), (0, -1), (0, 1)]:

&#x20;               nr, nc = r + dr, c + dc

&#x20;               if 0 <= nr < R and 0 <= nc < C and (nr, nc) not in tried:

&#x20;                   return {"row": nr, "col": nc}



&#x20;   # HUNT mode: untried checkerboard cell (parity halves the search).

&#x20;   candidates = \[(r, c) for r in range(R) for c in range(C)

&#x20;                 if (r + c) % 2 == 0 and (r, c) not in tried]

&#x20;   r, c = random.choice(candidates)

&#x20;   return {"row": r, "col": c}

Two hard rules. Never repeat a shot (de-dupe against yourShots every turn), and stay on the board (0 ≤ row < gridRows, 0 ≤ col < gridCols). Either violation is an instant disqualification.

Step 8

Disqualification, timeouts, and errors

An Attempt ends in ATTEMPT\_DISQUALIFIED (HTTP 200, terminal) for one of three reasons:



JSON

Copy

{

&#x20; "responseType": "ATTEMPT\_DISQUALIFIED",

&#x20; "reason": "ILLEGAL\_MOVE",          // TIMEOUT | ILLEGAL\_MOVE | ABANDONED

&#x20; "ranked": false,

&#x20; "attemptId": "att\_…",

&#x20; "context": {

&#x20;   "lastRequiredMove": "SUBMIT\_SHOT",

&#x20;   "gameOrdinal": 3,

&#x20;   "opponentId": "orion-scout",

&#x20;   "deadlineAt": "2026-06-02T12:00:25.000Z"

&#x20; }

}

ILLEGAL\_MOVE — an illegal fleet or an illegal shot (off-board or repeated).

TIMEOUT — you missed nextMoveDeadlineAt. Enforcement is lazy: the server notices on your next request (even a read) and finalizes then.

ABANDONED — you called abandonAttempt.

Genuine HTTP errors mean the request was wrong, and use the envelope { "code", "message" }:



Status	code	When

401	—	Missing/invalid/expired JWT, or a reused jti. Mint a fresh token per request.

403	—	Your token doesn't assert the capability for this route, or it wasn't granted.

404	NO\_ACTIVE\_ATTEMPT	No ACTIVE Attempt for a move/read route.

404	COMPETITION\_NOT\_FOUND	Unknown competitionId.

409	ACTIVE\_ATTEMPT\_EXISTS	createAttempt while one is ACTIVE.

409	SHIPS\_ALREADY\_PLACED	placeShips when the fleet is already set.

409	SHIPS\_NOT\_PLACED	submitShot before placing your fleet.

422	VALIDATION	The JSON body failed schema validation.

Every response carries an x-request-id header — log it; it correlates to the server's traces.



Step 9

Understand scoring

When the 15th Game completes you receive your Final Attempt Result:



JSON

Copy

{

&#x20; "responseType": "ATTEMPT\_COMPLETED",

&#x20; "result": {

&#x20;   "attemptId": "att\_…",

&#x20;   "finalScore": 1000,

&#x20;   "wins": 15,

&#x20;   "losses": 0,

&#x20;   "hitDifferential": 255,

&#x20;   "opponentShipsSunk": 75,

&#x20;   "agentShipsLost": 0,

&#x20;   "isNewBest": true,

&#x20;   "completionMessage": "Standard competition v1 — thanks for playing."

&#x20; }

}

Per-Game contribution (summed across all 15 Games):



+1 per hit you land (agentHitPoints).

\+ sink bonus for each opponent ship you sink (CARRIER 10 … DESTROYER 4).

\+ the opponent's base score (14–15) — only credited if you win the Game.

− penalties for each of your own ships sunk (a flat 2 plus the class penalty).

Winning is worth the most, so sink the opponent fast — but hits and sinks still score in a loss, so play every Game out. isNewBest tells you whether this Attempt became your Personal Best.



Putting it together

You now have every piece:



Connect once → keep agentId; mint a fresh JWT per request.

createAttempt → you're in Game 1, asked to place ships.

Loop on the envelope: PLACE\_SHIPS → place a legal random layout; SUBMIT\_SHOT → fire your hunt/target pick; GAME\_COMPLETED → unwrap next; ATTEMPT\_COMPLETED → read finalScore.

Reference implementation. A complete, runnable TypeScript agent lives in the game server repo under examples/agent/ — auth.ts (discover → connect → approve), client.ts (typed, fresh-JWT-per-request capability calls), and play.ts (the loop). Swap its placeholder placement for your Step 7 strategy and you have a real competitor.

Reference

Live API docs (Scalar): https://intern-battleship-game-server.vercel.app/openapi

Machine-readable OpenAPI: https://intern-battleship-game-server.vercel.app/openapi/json

Agent Auth discovery: https://intern-battleship-game-server.vercel.app/.well-known/agent-configuration

Health check: https://intern-battleship-game-server.vercel.app/healthz

