"""
GSS — Client Acquisition Maximizing Platform — Flask app factory / entry point.

Run locally with:
    flask --app app init-db        # creates instance/gss.db from schema.sql
    flask --app app seed-tenant    # creates the first tenant + its Tenant Admin
    flask --app app run --debug    # http://127.0.0.1:5000

UI/navigation model cloned from the Tourism Management System (TMS): a
data-driven sidebar (see templates/base.html) built from the MODULES list
below, with "Utilities" nesting Table Maintenance and Data Exchange under
one collapsible group — the same {"children": [...]} pattern TMS used for
its own "Tables & Utilities" group.
"""
from dotenv import load_dotenv
from flask import Flask, render_template

# Loads App/.env into the environment before anything else runs, so
# ANTHROPIC_API_KEY (used by business_card_import.py's lazily-imported
# Anthropic client) is set without anyone having to configure it at the OS
# level -- same convention as the Book to Movie Studio app's main.py /
# run_webapp.py. A real environment variable of the same name still wins
# over .env (load_dotenv's default), so a system-wide setting keeps working
# unchanged. No-op, not an error, if App/.env doesn't exist.
load_dotenv()

import db as db_module
from security import csrf
from utils import basename, format_date, format_phone, linkify, orblank

# "roles": [...] restricts a module (or child) to those roles; omitted means
# every logged-in user sees it. base.html filters on this — see its {% for
# m in modules %} loop. SystemAdmin accounts have no tenant_id of their own
# (schema.sql MODULE T), so everything tenant-scoped (Organizations,
# Contacts, Documents, Utilities, and System Management's own
# backups/health, which moved to system_admin_required for a different
# reason — see blueprints/system_mgmt.py) is hidden from them; Tenant
# Management is the mirror image, SystemAdmin-only.
MODULES = [
    {"key": "dashboard", "label": "Dashboard", "icon": "speedometer2", "endpoint": "dashboard.index",
     "roles": ["TenantAdmin", "User"]},
    {"key": "organizations", "label": "Organizations", "icon": "building", "endpoint": "organizations.list_organizations",
     "roles": ["TenantAdmin", "User"]},
    {"key": "contacts", "label": "Contacts", "icon": "people", "endpoint": "contacts.list_contacts",
     "roles": ["TenantAdmin", "User"]},
    {"key": "documents", "label": "Documents & Knowledge Base", "icon": "folder2-open", "endpoint": "documents.index",
     "roles": ["TenantAdmin", "User"]},
    {"key": "utilities", "label": "Utilities", "icon": "gear-wide-connected", "roles": ["TenantAdmin", "User"], "children": [
        {"key": "data_exchange", "label": "Data Exchange", "icon": "arrow-left-right", "endpoint": "data_exchange.index"},
        {"key": "table_maintenance", "label": "Table Maintenance", "icon": "table", "endpoint": "table_maintenance.index"},
        {"key": "geography_admin", "label": "Geography Maintenance", "icon": "globe-americas", "endpoint": "geography_admin.index"},
        {"key": "agents", "label": "Agents Library", "icon": "robot", "endpoint": "agents.index"},
        {"key": "billing", "label": "Agent Billing", "icon": "credit-card", "endpoint": "billing.usage"},
    ]},
    {"key": "users", "label": "Manage Users", "icon": "people-fill", "endpoint": "users.list_users",
     "roles": ["TenantAdmin"]},
    {"key": "system_mgmt", "label": "System Management", "icon": "gear", "endpoint": "system_mgmt.index",
     "roles": ["TenantAdmin", "User"]},
    {"key": "tenants_admin", "label": "Tenant Management", "icon": "diagram-3", "endpoint": "tenants_admin.list_tenants",
     "roles": ["SystemAdmin"]},
    {"key": "agents_admin", "label": "Agent Requests", "icon": "robot", "endpoint": "agents.admin_index",
     "roles": ["SystemAdmin"]},
    {"key": "billing_admin", "label": "Agent Billing", "icon": "credit-card", "endpoint": "billing.admin_catalog",
     "roles": ["SystemAdmin"]},
]


def create_app():
    app = Flask(__name__, instance_relative_config=False)

    from config import Config
    app.config["SECRET_KEY"] = Config.get_secret_key()
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # See config.py: False for local dev (plain http://), set to True via
    # the SESSION_COOKIE_SECURE env var once served over real HTTPS.
    app.config["SESSION_COOKIE_SECURE"] = Config.SESSION_COOKIE_SECURE
    # Generous cap covering the largest legitimate upload: a bulk zip of ad
    # photos for Data Exchange > Import Business Card / Organizations >
    # Import Ads in Bulk (up to MAX_BATCH_IMAGES real phone photos per zip,
    # a few MB each -- see ad_import.py/business_card_import.py), plus the
    # smaller cases (a profile photo, a single business card or ad photo,
    # CSV imports).
    app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024

    db_module.init_app(app)
    csrf.init_app(app)

    # Upgrade an existing tenant's database with any schema changes shipped
    # since they first installed - automatic, additive, no data loss, no
    # manual command. A no-op if the database isn't initialized yet (the
    # very first `flask init-db` run) or is already fully up to date.
    with app.app_context():
        db_module.run_pending_migrations()

    from auth.routes import auth_bp
    from blueprints.dashboard import dashboard_bp
    from blueprints.organizations import organizations_bp
    from blueprints.contacts import contacts_bp
    from blueprints.documents import documents_bp
    from blueprints.data_exchange import data_exchange_bp
    from blueprints.table_maintenance import table_maintenance_bp
    from blueprints.system_mgmt import system_mgmt_bp
    from blueprints.geography import geography_bp
    from blueprints.geography_admin import geography_admin_bp
    from blueprints.help import help_bp
    from blueprints.agents import agents_bp
    from blueprints.billing import billing_bp
    from blueprints.users import users_bp
    from blueprints.tenants_admin import tenants_admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(organizations_bp, url_prefix="/organizations")
    app.register_blueprint(contacts_bp, url_prefix="/contacts")
    app.register_blueprint(documents_bp, url_prefix="/documents")
    app.register_blueprint(data_exchange_bp, url_prefix="/data-exchange")
    app.register_blueprint(table_maintenance_bp, url_prefix="/table-maintenance")
    app.register_blueprint(system_mgmt_bp, url_prefix="/system")
    app.register_blueprint(geography_bp, url_prefix="/geography")
    app.register_blueprint(geography_admin_bp, url_prefix="/geography-admin")
    app.register_blueprint(help_bp, url_prefix="/help")
    app.register_blueprint(agents_bp, url_prefix="/agents")
    app.register_blueprint(billing_bp, url_prefix="/billing")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(tenants_admin_bp, url_prefix="/platform/tenants")

    app.jinja_env.globals["modules"] = MODULES
    app.jinja_env.filters["format_phone"] = format_phone
    app.jinja_env.filters["format_date"] = format_date
    app.jinja_env.filters["linkify"] = linkify
    app.jinja_env.filters["basename"] = basename
    app.jinja_env.filters["orblank"] = orblank

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="You don't have access to that page"), 403

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("error.html", code=500, message="Something went wrong"), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
