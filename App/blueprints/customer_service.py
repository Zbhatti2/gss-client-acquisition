"""
Module — Customer Service (placeholder).

Client Acquisition (blueprints/client_acquisition.py) is the sales pipeline
that turns a prospect into a client. Customer Service is deliberately a
SEPARATE module for what happens after that — complaints, tickets, issues,
delivery tasks, notifying a delivery team — per the user's explicit
decision when this module was scoped (see the GSS_Data_Model_Decisions_v1.md
project doc's Client Acquisition addendum). None of that is built yet; this
is just the "coming soon" placeholder the nav entry needs to point at so the
menu item is real from day one instead of a dead link.
"""
from flask import Blueprint, render_template

from auth.decorators import login_required

customer_service_bp = Blueprint("customer_service", __name__)


@customer_service_bp.route("/")
@login_required
def coming_soon():
    return render_template("customer_service/coming_soon.html")
