# White Tower sandbox and mobile client

The user supplies the storyteller in ChatGPT. This project supplies the persistent
world, validated rules, authoritative action receipts and phone interface. Further
work prioritises the sandbox and tools rather than authored story chapters.
No OpenAI API key or API credit is required by the sandbox runtime.

## Sandbox foundation

The new default sample is `tower-sandbox-v1`, independent of chapter scripts.
Four fixture locations form a traversable graph. Objects retain their location,
carried status and supported properties when you leave and return. Supported
operations are travel, take/drop, wait, recovery, release, supervised Spark and
Air Hand, extinguishing the practice candle, and declared mundane challenges. The saved clock determines
supervisor availability; clients cannot supply a fabricated permission or target.

This is a **disposable rules subset**, not the full Wheel of Time engine.
The map and supervisor schedule are test fixtures, not canonical geography.
Combat, Healing, opposed checks, NPC combat/channeling, curriculum progression,
advanced channeling and live character import remain unimplemented here.
Existing authored samples and their saves remain available as regression fixtures.

## Storyteller tool contract

`mobile_game.sandbox_tools` is a transport-independent, MCP-shaped dispatcher.
It receives the authenticated player identity from the transport; the model may
never provide or override that identity. Its five tools are:

- `sandbox_list()`: find this owner's sandboxes when resuming in a fresh chat.
- `sandbox_create(request_id)`: create a disposable sandbox; the same ID retries safely.
- `sandbox_read(campaign_id)`: explicit player-visible world projection and available actions.
- `sandbox_preview(campaign_id, action_id, expected_revision, command)`: validate one
  structured command; return costs, effects and the exact commit request without mutation.
- `sandbox_commit(campaign_id, request)`: use that request unchanged after the player
  chooses the action. The existing PostgreSQL transaction checks revision and
  stakes, persists one event, and returns an identical result for a repeated ID.

Example command: `{"op":"cast","weave":"W02","target":"wooden_token"}`.
Commands outside the current capabilities fail explicitly. Narration, extra keys,
invented targets, ability overrides and caller-supplied supervision cannot write
state. An uncertain reply must retry the original request, never reroll or invent
success. The storyteller owns prose; only an engine receipt establishes an action.

The deployed web adapter exposes `GET /api/sandbox/tools` and
`POST /api/sandbox/tools/<tool_name>` using the existing owner session and CSRF
protection. These web routes are separate from the MCP endpoint. The published
schemas mark reads/previews read-only and commits as idempotent writes.

The new `/mcp` endpoint implements stateless Streamable HTTP with JSON responses,
initialization, notifications, discovery and tool calls. It requires OAuth bearer
tokens on every request; browser cookies cannot authenticate it. Set
`WOT_MCP_ENABLED=1` with a canonical HTTPS `PUBLIC_ORIGIN` to enable it. With the
flag absent it fails closed. No model credentials are used.

Authlib handles the authorization-code/PKCE and refresh grants. The existing
website login identifies the owner on `/oauth/authorize`; the owner explicitly
consents through a CSRF-protected endpoint. Dynamic registration accepts only the
exact ChatGPT callback `https://chatgpt.com/connector_platform_oauth_redirect`.
Discovery advertises S256, public clients (`none`) and RFC 9207 issuer identification.
Tokens are restricted to this service's exact `/mcp` resource. Access lasts one
hour; rotating refresh tokens expire with the original grant after 30 days.
Reused codes or refresh tokens revoke their grant family. PostgreSQL row locks
serialize exchanges across workers. Only hashes of codes/tokens are stored.
`/connect` allows the owner to disconnect all ChatGPT grants without deleting saves.

The server supports `sandbox:read` and `sandbox:write`; writes require both.
These grants cover disposable sandbox tools only. They cannot import live saves,
access other owners, edit login credentials, or enable provider spending.
The authorization server is hosted here using Authlib rather than an external
identity service, so operating and testing this flow remains our responsibility.
No public unauthenticated campaign endpoint or shared master token is provided.
See the official
[OpenAI MCP authentication requirements](https://developers.openai.com/plugins/build/auth)
and [MCP server guide](https://developers.openai.com/plugins/build/mcp-server).
The deployed connection was verified in ChatGPT web on 24 October 2026: sample
creation/readback, a previewed action, identical-request retry without duplicate
costs, independent browser/export validation, and recovery in a separate chat
without supplying its campaign ID or state. Native iPhone availability remains
unverified. `chatgpt_connection_ready` reports whether this server's OAuth MCP
transport is enabled; it does not prove the current browser owner has connected
ChatGPT or that a particular client exposes the tools.

## Persistent world preparation

The existing preview/commit tools now accept an `establish` command with 1–12
public records. This permits a storyteller to build a traversable world rather
than repeatedly replaying the four-room fixture. For example:

```json
{"op":"establish","changes":[
  {"kind":"place","id":"workroom","name":"Small workroom","description":"A quiet room used for sorting ordinary supplies."},
  {"kind":"route","from":"library","to":"workroom","seconds":90},
  {"kind":"object","id":"ribbon","name":"Blue ribbon","location":"workroom","weight_kg":0.01},
  {"kind":"person","id":"sera","name":"Sera","location":"workroom","description":"An adult clerk sorting blank paper."},
  {"kind":"fact","id":"paper_delivery","text":"Blank paper for the workroom arrived this morning."}
]}
```

Places, reciprocal routes, ordinary portable props, people and established facts
persist in the same revisioned checkpoint and immutable event chain. Preparation
costs no fictional time and changes no character field. Existing records and
routes cannot be overwritten; identities/names cannot replace the PC or duplicate
an existing object. Props must start in a known place and be acquired through
normal actions. Carrying them, leaving them elsewhere and returning use the same
world operations. Preparation and player actions share revision locking, retry
identity, rollback, export and recovery. The returned preparation commit request
includes its canonical command; do not omit or modify it.

All authored records are explicitly `campaign_invention`, never source-verified
canon. Use only public, established material within the agreed premise; no secrets,
PC speech/decisions, retcons, claims that unperformed checks succeeded, abilities,
rewards or item effects. Text never grants mechanics: calling an NPC a supervisor
does not enable casting, and describing a magical object grants no power. These
are safe ordinary places/routes and props; hazards, access locks, economic items,
NPC conflict, hazardous interactions and encounters need their own future mechanical operations.
The server enforces structure, append-only identities and mechanical isolation;
it cannot establish the truth or lore accuracy of natural-language facts.

Old saves keep their original fixture graph until a preparation is committed.
Existing saves and Aveline are not migrated by this feature. Current bounds are
100 places, 200 objects, 100 people, 300 public facts and 200 challenges per disposable sandbox;
the HTTP body limit remains 16 KiB. Broader campaign mechanics and native phone
verification remain required before live-character migration.

## Reusable mundane challenges

`establish` also accepts immutable public `challenge` records. The schema declares
a stable ID and scene ID, location, goal, method, uncertainty, alternative,
Attribute, supported mundane Skill, difficulty, help/obstacle fact references and
all three outcomes (`clean`, `costly`, `setback`). Each outcome specifies a summary,
10–3600 seconds, 0–6 Supply cost and 0–100 silver cost. See
`tests_mobile/test_challenges.py` for a complete disposable example. No arbitrary
patch, reward, injury, ability grant, channeling or combat operation is accepted.

Attempt a saved challenge with `{"op":"attempt","target":"challenge_id"}`.
The normal preview returns the exact saved ratings, single +2/−2 situational
modifier, achievable totals, difficulty, bands and declared consequences. It
never generates dice. Commit generates server 2d10 using the existing unbiased,
action-bound generator and writes one result plus its costs atomically. Totals at
least the difficulty are clean; 1–3 below are costly; 4+ below are setbacks.
A null difficulty means safe routine work with identical outcome branches and no
roll. Normal, hard and exceptional difficulties are 14, 18 and 22. These numbers
implement the agreed `notion-manual-v2` house rules, not novel canon.

All possible costs and durations must be affordable before the attempt is offered.
A challenge resolves once; the same scene/location/goal/method cannot be inserted
under another ID. At most three rolled checks can resolve per declared scene;
routine work does not consume that allowance. Existing identities and definitions
cannot be overwritten. Failed requests roll back; identical committed retries
return the original dice/result without paying again. Results persist in
`sandbox.challenge_results`, the mobile world panel and the complete export.

The storyteller still must judge fictional uncertainty, alternative methods,
source access and modifier relevance. It must honour completed goals, keep scene
identity stable and never paraphrase an unchanged test to bypass the cap. The
engine checks structure and arithmetic; it cannot prove that outcome prose is
consistent with lore, that a declared setback changes the fiction, or that a
costly result achieves useful progress. The limit is not an automatic victory.
Combat, opposed checks, Medicine/Healing, progression and live-character imports
remain separate work. No migration is performed by adding these operations.

## NPC activity on the shared clock

The storyteller can commit a public ordinary errand through the same tools:

```json
{"op":"npc_plan","id":"paper_delivery","actor":"sera",
 "purpose":"Carry the paper parcel to the reading room.",
 "steps":[{"op":"take","target":"parcel"},
          {"op":"move","target":"library"},
          {"op":"drop","target":"parcel"}]}
```

The actor, objects and every route must already exist. One to eight steps are
validated as a complete sequence before scheduling. The server derives movement
time from the saved route; pickup/drop each take ten seconds. An NPC has one
active plan. Competing NPC reservations for the same prop are rejected; this
adapter does not adjudicate conflicts. The 5 kg total carrying bound is an
explicit limit of this ordinary-errand adapter, not a claim about canonical
strength or a general NPC character sheet.

Scheduling costs no fictional time. The actions settle at their recorded due
seconds during later player actions, inside that action's existing PostgreSQL
transaction. A ten-minute wait containing a 140-second delivery still costs ten
minutes, not twelve minutes twenty seconds. Reads and real-world time never
advance the game. Preview reports the background events each action would settle;
uncertain checks preview them separately for each declared outcome without dice.

Object custody uses a unique `person:<id>` location. A carried object follows its
NPC, cannot also be in player inventory and cannot be picked up or targeted as
unheld. During a move, the saved location denotes departure until arrival; inspect
`activity` for the destination and due time. If the player takes a parcel before
the NPC's pickup completes, the player's immediate pickup wins and the errand
blocks. No item is taken from the player, duplicated or silently recreated.
Preconditions are rechecked at each step; failure stops the remaining plan.

`{"op":"cancel_npc_plan","target":"paper_delivery"}` finishes the current
step, then stops. It does not teleport a travelling NPC, undo a pickup or erase
prior events. A later genuinely new errand needs a new ID. Retry an uncertain
response with the same action ID and request, as with all other operations.

All plans are public, non-conflict background activity. They cannot act for the
PC, spend player resources, grant permissions, cast, fight, conceal information,
force a conversation or create an interaction requiring a new player decision.
Those situations need distinct mechanics with interruptible time. The storyteller
must not encode them as ordinary errands. `sandbox.known_people` reports public
locations/activity, `sandbox.npc_plans` contains active and ten recent plans, and
`sandbox.npc_events` contains twelve recent step results. Full results remain in
the saved plans and complete action export. The mobile world panel shows recent
NPC results and local custody/activity. Current capacity is 400 plans per
sandbox; no existing live campaign or old checkpoint is migrated.

## Connected chapters: highest-leverage development pass

Assessment: cloud persistence, recovery and an authored first episode are working.
The largest playable gap was a completed episode leading only to repeated downtime
or a new character. A freeform GM remains blocked on funded live evaluation;
more notebook or visual polish would not address this continuity gap.

The selected improvement is **connected play with the same character**. After the
gallery chapter finishes (including refusal), `Continue with the same character`
opens **A Seat in the Garden**, an original social chapter with four distinct
approaches. The transition explicitly advances to the next free afternoon; it
never grants training or recovery, silently releases channeling, or reopens the
completed search. Active channeling must be released before skipping ahead.

The same campaign ID, character, resources, learning, NPC memories, personal notes,
immutable event history and original dice are retained. The gallery's stored
result remains complete. The notebook lists both chapters and the library shows
the current scene. The new chapter supports listening through an entire exchange,
privacy, welcoming another novice, one-to-one company and a respected refusal.
No social roll is required and no PC dialogue or future promise is invented.

Evaluation covers all routes, both with and without hearing the initial exchange,
no repeated conversation prompt, actual closure, clock boundaries, active-working
protection, state preservation, duplicate requests, ownership and fresh-browser
recovery. This is still a finite authored sample, not unrestricted roleplay or
proof of a satisfying long campaign. Live Aveline migration remains disabled.

## Personal notebook

Each campaign has an owner-only notebook saved separately from game state.
Notes never advance the turn or change dice, time, resources or NPC knowledge.
Explicit saves persist online and appear in the player export. Drafts are kept
on the current device, separately for each owner and campaign. Version checks
reject conflicting edits from another device; the player reviews the saved copy
before merging or replacing it. Retrying the same saved text is harmless.

## Playable authored adventure (v4)

New stories default to **The Letter in the Gallery**, a separate original
disposable adventure. The original garden rehearsal remains available, and
existing saved campaigns retain their original episode and history.

The gallery supports authored conversation, reliable observation, several
methods, one disclosed uncertain check, a respected refusal and an actual
ending. NPC memories, discoveries, practice evidence and twenty-minute theory
blocks persist with the character. The tutor's teaching period ends on the
saved clock; quiet time stops at that boundary and supervision does not persist
indefinitely. Optional follow-up activities do not reopen the completed task.

Supported typed intentions use a local, conservative interpreter with no model
credential or API cost. Clear routine actions proceed through the same durable
action system as buttons. Questions are read-only; risky actions show their
complete stakes before a roll. Ambiguous inputs, different targets and unsupported
methods do not silently become another action. This is **not general natural
language understanding or an unrestricted AI GM**. The finite authored dialogue
does not yet respond to arbitrary player speech.

The new safe-casting module validates learned Spark and Air Hand, supervision,
handling prerequisites, range, Air Hand's weight limit, existing load and held
slots, and Strain limits before charging. It includes ordinary embrace and release
of the specific brief working; no extra safe-practice roll is introduced. Combat,
Healing, tying, circles, the complete curriculum and chapter advancement still
require their own implementations and evaluations before live-campaign migration.

The phone interface includes owner/campaign-specific unsent drafts and reading
position, night reading, larger story text, a resume card, a character/weave
reference, known people and memories, learning evidence, and a searchable paged
journal. Private fields are excluded from the companion and journal projections.
Drafts never submit themselves; a pending committed action retains its exact ID.

The authored adventure works with the paid GM disabled. New paid requests to this
episode are rejected before reserving budget; the older optional interpreter
continues to support only the original garden rehearsal.

## Run

Install `mobile_game/requirements.txt` in a Python 3.13 environment. Set
`DATABASE_URL` to PostgreSQL. Run `gunicorn mobile_game.wsgi:application`.
For a local preview only, set `WOT_LOCAL_DEV=1`; production cookies are Secure,
HttpOnly, SameSite=Strict. `PUBLIC_ORIGIN` may pin the exact HTTPS origin.

On Railway, create a separate service from the `mobile-postgres-pilot` branch.
Use `mobile_game/Dockerfile`, `/health`, and a private reference to
`${{Postgres.DATABASE_URL}}`. The database requires persistent storage. Set
`sleepApplication=false` for predictable first-request behaviour. Enable volume
backups before real campaign use; a successful restore drill is a separate gate.
Do not expose PostgreSQL publicly to serve the game.

## Save semantics

The browser retains the exact action ID, expected revision, choice ID and hash
of the displayed stakes, bound to its original player identity, before submitting
it. A read-only session check prevents pending requests from being replayed under
a replacement account after cookie loss. Invalid recovery input creates no owner.
PostgreSQL locks the owned
campaign, detects identical retries, rejects altered retries and stale choices,
and commits the immutable event and updated checkpoint in one transaction.
Only committed results produce a saved receipt. Lost replies can retry the same
request without another roll. Dice use rejection sampling from a private seeded
HMAC, bound to the campaign and action ID; the seed is never sent to the browser.

Sessions use random HttpOnly cookie tokens. A separately generated recovery code
restores the same player in another browser; only its hash is stored. The code
is shown once and can be saved. An authenticated browser can replace a lost code
through Recovery; replacing it invalidates the previous code. It grants access to the disposable player's
stories and should be kept private. There is no dependency on Notion, Sites,
ChatGPT, a local file path, or a desktop process during hosted play.

The public API exposes only an explicit player projection. The download endpoint
provides the complete disposable state and event history, with a corruption
checksum, but no authentication credentials or private dice seed. It is an audit
export, not a file-import feature. It does not substitute for database backups.

## Checks

Set `TEST_DATABASE_URL` to a dedicated database named `mobile_pilot_test`, then:

```
python -m pytest tests_mobile -q
```

Keep Node available to include the shipped browser-script retry regressions.

Integration tests deliberately clear only the dedicated test database. Use a
different database for browser preview. Tests cover dice bands, scene completion,
state preservation, immutable retry results, changed-input rejection, concurrent
writers, transaction rollback, recovery codes, ownership and CSRF protection.

## Bounded scene interpreter — offline integration

The optional text box interprets a request about the disposable scene. It can
explain the visible situation, ask for clarification, or propose one existing
choice. It cannot resolve an action, roll dice, advance time, alter resources,
invent a new ability, or run a live campaign. A proposal uses the normal action
button and disclosed stakes; a risky action still requires confirmation.

The feature is **disabled by default**. A key alone cannot enable paid calls.
`WOT_GM_ENABLED=1`, `OPENAI_API_KEY`, positive `WOT_GM_MAX_REQUESTS`, and
`WOT_GM_BUDGET_MICRO_USD` must all be configured by the server operator. The fixed
model is `gpt-5.4-mini`; another `WOT_GM_MODEL` fails closed. Env files are not
automatically loaded, and the browser never receives the credential. Keep this
feature disabled until funded live testing is explicitly resumed.

Each request reserves 23,700 micro-USD ($0.0237) before its single provider call.
The conservative reservation uses the complete serialized request byte bound
plus framing headroom (25,600 input tokens), 1,000 output tokens including
reasoning, and documented prices of $0.75/M input and $4.50/M output. It is a
local application allowance, not an OpenAI account-wide billing limit or a
guarantee against future price changes. Recheck pricing before enabling the
feature. The app sends no tools, uses `store=false`, and gives the provider only
the explicit public scene projection. User requests are limited to 2,000
characters; the complete API payload is capped at 24,576 bytes.

The PostgreSQL allowance counts requests and reserved cost for the lifetime of
this pilot across all users and worker restarts. Reservations are never refunded,
including failed or uncertain calls. An old request ID always returns its saved
status/result; it cannot charge again. Altering its input is rejected. The
provider call holds no campaign transaction open and has a 14-second deadline
with no automatic retries. An abandoned reservation becomes terminal after
45 seconds. A timeout may still have incurred provider cost, so it stays counted.

The phone retains the original owner, request ID, revision and prompt before
submission. After an interrupted reply, recovery polls the saved request; it
does not start another model call. Only an explicit retry after a confirmed
missing request can resend the identical ID. Proposals are bound to their
original revision and canonical choice hash, and are checked again before
being offered to the ordinary action endpoint. Model replies themselves leave
the campaign and its journal unchanged.

`test_gm.py`, the store/HTTP integration tests, and `frontend_gm_probe.cjs` use
synthetic responses with no paid calls. They verify error handling, hard limits,
agency backstops, request recovery and state safety. **They do not establish live
model response quality, live model latency, or complete manual-v2 gameplay.**
API credit exhaustion currently prevents live evaluation. This offline work
does not enable the feature on Railway or move a real character.

### Disposable backup rehearsal

`tests_mobile/backup_probe.py` exercises real `pg_dump`/`pg_restore` against two
new local databases. From `mobile-runtime`, with its Python dependencies and
compatible PostgreSQL utilities on `PATH`, run:

```sh
mkdir -p ../.runtime
chmod 700 ../.runtime
PYTHONPATH=. python tests_mobile/backup_probe.py \
  --source-database mobile_pilot_backup_source \
  --restore-database mobile_pilot_backup_restore \
  --host 127.0.0.1 --port 55432 --user mobile_test \
  --backup-file ../.runtime/mobile-pilot-backup.dump
```

Start a dedicated local PostgreSQL cluster first; the role must be allowed to
create databases. The probe refuses non-loopback hosts, different database
names, existing databases, and existing backup files. It does not start or stop
PostgreSQL or delete test artifacts. Use a fresh disposable cluster for each CI
run, invoke this command explicitly, and stop/remove that cluster afterward.
It is not collected by the ordinary pytest run. `--report-file` optionally saves
the redacted result to a new file; failures exit nonzero without printing SQL,
subprocess error text, credentials, or campaign content.

The rehearsal checks all mobile table rows and schema, full checkpoint/event
continuity, unknown state fields, sessions, recovery, private dice seeds,
exact action retries, and completed/uncertain interpreter requests with their
lifetime allowance. Restoring those requests must not recall the provider or
reset spending limits. The backup is created with mode 600 under `.runtime`;
keep it private and never publish it as a CI artifact. It contains security and
gameplay state that the player-facing JSON export deliberately omits.

This proves local logical backup/restore capability. **Hosted scheduled backups
remain unverified.** It does not establish Railway backup scheduling, retention,
off-site storage, encryption, database roles/grants, point-in-time recovery, or
a restore from an actual hosted backup. Those need separate verification before
moving a real campaign. The utility intentionally restores without ownership or
ACL changes into the isolated local database.

## Migration gate

`mobile_game.migration` can validate and preserve a local manual-v2 checkpoint,
its committed head, and a separate private GM page in a checksummed offline
capsule. It checks structural consistency and retains all source fields without
converting them to the sample's different schema. Synthetic tests cover mismatch
rejection, exact round trips and private-data exclusion from its redacted report.

A capsule is explicitly `STAGED_NOT_PLAYABLE`. It is a private archive containing
GM material, not a phone save or player-facing download. It does not establish
source freshness, authenticity, complete historical-journal coverage or correct
adjudication. No HTTP import route or database activation is provided.

No Aveline or other live campaign import endpoint exists. Before adding one:

1. Prove the deployed phone workflow, restart recovery and backup restoration.
2. Connect and evaluate the user-supplied ChatGPT storyteller through the
   authenticated MCP adapter, including action previews and authoritative receipts.
3. Map all current manual rules, character fields, history, original dice policy
   and private continuity data without resetting or reconstructing a character.
4. Rehearse the migration using a disposable copy and compare complete states.
5. Only then activate the authorised real campaign, retaining the Notion origin.

Passing a small episode is evidence for that episode and storage path; it is not
proof that the full campaign or narrative experience is ready.
