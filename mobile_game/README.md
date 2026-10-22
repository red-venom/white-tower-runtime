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
of the displayed stakes before submitting it. PostgreSQL locks the owned
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

Integration tests deliberately clear only the dedicated test database. Use a
different database for browser preview. Tests cover dice bands, scene completion,
state preservation, immutable retry results, changed-input rejection, concurrent
writers, transaction rollback, recovery codes, ownership and CSRF protection.

## Migration gate

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
