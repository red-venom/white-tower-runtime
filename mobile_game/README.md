# White Tower mobile PostgreSQL pilot

This is a separate, disposable, choice-driven episode. It runs entirely on the
hosted web service and PostgreSQL. A player's desktop is not a runtime component.
It implements a small supported subset of `notion-manual-v2`; it is not a full
freeform GM, a live-campaign importer, or the older `rules-v2` Python engine.

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
2. Implement and evaluate the desired freeform GM with an authenticated model
   service and an explicit hosting/model cost configuration.
3. Map all current manual rules, character fields, history, original dice policy
   and private continuity data without resetting or reconstructing a character.
4. Rehearse the migration using a disposable copy and compare complete states.
5. Only then activate the authorised real campaign, retaining the Notion origin.

Passing a small episode is evidence for that episode and storage path; it is not
proof that the full campaign or narrative experience is ready.
