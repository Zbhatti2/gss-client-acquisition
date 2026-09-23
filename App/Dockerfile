# GSS -- Client Acquisition Maximizing Platform
# Production image for the Hostinger VPS2 / Coolify deployment.
#
# Local development is UNCHANGED by this file -- start_gss_*.bat still runs
# the app directly with `flask run` on your machine. This Dockerfile is only
# used by Coolify to build and run the container on the VPS.
FROM python:3.12-slim

WORKDIR /app

# Install Python deps first (separate layer) so `docker build` doesn't
# reinstall everything just because application code changed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code. See .dockerignore for what's deliberately left out
# (instance/, venv/, .env, .git, __pycache__).
COPY . .

RUN chmod +x entrypoint.sh

ENV FLASK_APP=app \
    PYTHONUNBUFFERED=1

# instance/ (gss.db, secret_key, tenant_master.key, uploads/, backups/) is
# where a Coolify persistent volume MUST be mounted -- see
# GSS_Deployment_Hosting_Plan_v1.md. Without that volume, every redeploy
# starts from an empty database and a fresh (incompatible) encryption key.
VOLUME ["/app/instance"]

EXPOSE 5000

ENTRYPOINT ["./entrypoint.sh"]
