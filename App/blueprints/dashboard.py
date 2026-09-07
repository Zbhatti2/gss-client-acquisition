from flask import Blueprint, g, render_template

from auth.decorators import login_required
from db import get_db

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    """GSS's home page: quick-links into each of the six Initial Modules
    plus a bar of at-a-glance counts. Unlike TMS's dashboard (which still
    had several not-yet-built tourism modules behind "coming soon" pages),
    every module GSS ships is real, so every tile here links straight to
    its own module rather than a placeholder."""
    db = get_db()
    tenant_id = g.tenant_id
    counts = {
        "organizations": db.execute(
            "SELECT COUNT(*) c FROM organizations WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()["c"],
        "contacts": db.execute(
            "SELECT COUNT(*) c FROM contacts WHERE tenant_id = ? AND is_deleted = 0", (tenant_id,)
        ).fetchone()["c"],
        "documents": db.execute(
            "SELECT COUNT(*) c FROM content WHERE tenant_id = ? AND is_deleted = 0", (tenant_id,)
        ).fetchone()["c"],
        "pending_batches": db.execute(
            "SELECT COUNT(*) c FROM import_batches WHERE tenant_id = ? AND status NOT IN ('Committed', 'Rejected')",
            (tenant_id,),
        ).fetchone()["c"],
    }
    return render_template("dashboard.html", counts=counts)
