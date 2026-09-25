#!/bin/sh
# GSS container entrypoint.
#
# * Schema migrations for an EXISTING database already run automatically
#   every time the app is imported (app.py's create_app() calls
#   db_module.run_pending_migrations()) -- that covers gunicorn below too,
#   nothing extra needed here for upgrades.
# * A database that doesn't exist yet (the very first deploy, before the
#   persistent volume has anything in it) needs `init-db` + `seed-tenant`
#   run once -- this script does that automatically so a fresh deploy comes
#   up usable without a manual step, but ONLY if instance/gss.db is
#   genuinely missing (never touches an existing database).
# * Creating the first SystemAdmin login is NOT automated here on purpose
#   (it needs a password chosen interactively, hidden, confirmed twice --
#   see db.py's create-system-admin command). Run it once after the first
#   deploy via Coolify's "Execute Command" / a shell into the running
#   container:
#       flask --app app create-system-admin
# * Exactly ONE gunicorn worker, on purpose -- see security/session_keys.py.
#   The logged-in tenant's decrypted field-encryption key is deliberately
#   kept OUT of the session cookie (it's cached server-side, in plain
#   process memory, keyed by an opaque token) and is never written to disk.
#   That cache is a single Python dict local to one process. With more than
#   one gunicorn worker, a request can land on a worker that never saw that
#   dict entry, and login_required() (auth/decorators.py) treats that as
#   "not really logged in" and bounces back to /login -- intermittently,
#   depending on which worker handled that particular request. Fine for this
#   MVP's traffic (a couple of small tenants); before scaling beyond one
#   process, move that cache to a shared store (e.g. Redis, or a
#   short-lived DB table keyed by a hashed token) rather than raising -w.
# * --timeout 300 (gunicorn's default is 30s) -- Import Ads/Flyers
#   (blueprints/data_exchange.py's import_ads_flyers_extract) makes one
#   blocking Claude vision API call PER uploaded image, sequentially, all
#   inside a single request before it returns the review page. A batch of
#   more than a handful of images easily runs past 30s, which used to make
#   gunicorn's master kill the worker mid-batch (WORKER TIMEOUT in the log)
#   -- and because there's only the one worker above, that also made the
#   whole app briefly unreachable for every other user until a replacement
#   worker booted. 300s comfortably covers a full MAX_BATCH_AD_IMAGES=40
#   batch; still worth uploading a handful of images at a time rather than
#   the full 40 in one go, since nothing else can be served while a batch
#   this size is being processed (the single-worker trade-off above).
#   Same real fix as the multi-worker note above: move this to background
#   processing (return immediately, process the batch async) before this
#   feature sees meaningfully heavier use.
set -e

if [ ! -f "instance/gss.db" ]; then
    echo "[entrypoint] No database found -- initializing (first deploy)..."
    flask --app app init-db
    flask --app app seed-tenant
    echo "[entrypoint] Database initialized and first tenant seeded."
    echo "[entrypoint] Next: run 'flask --app app create-system-admin' once to create your SystemAdmin login."
fi

exec gunicorn -w 1 -b 0.0.0.0:5000 --timeout 300 --access-logfile - --error-logfile - app:app
