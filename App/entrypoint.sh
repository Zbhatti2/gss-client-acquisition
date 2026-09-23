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
set -e

if [ ! -f "instance/gss.db" ]; then
    echo "[entrypoint] No database found -- initializing (first deploy)..."
    flask --app app init-db
    flask --app app seed-tenant
    echo "[entrypoint] Database initialized and first tenant seeded."
    echo "[entrypoint] Next: run 'flask --app app create-system-admin' once to create your SystemAdmin login."
fi

exec gunicorn -w 2 -b 0.0.0.0:5000 --access-logfile - --error-logfile - app:app
