# White Tower mobile PostgreSQL pilot

This is a separate, disposable, choice-driven episode. It runs entirely on the
hosted web service and PostgreSQL. A player's desktop is not a runtime component.
It implements a small supported subset of `notion-manual-v2`; it is not a full
freeform GM, a live-campaign importer, or the older `rules-v2` Python engine.

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
continuity, unknown state fields, sessions, recovery, private dice seeds and
exact action retries. The backup is created with mode 600 under `.runtime`;
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
