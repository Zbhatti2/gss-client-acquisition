---
title: Managing Your Organization's Users
order: 1
keywords: [users, teammates, add user, deactivate, reset password, role, tenant admin, temporary password]
---
**Tenant Admin only.** This is where you add, edit, and deactivate the
people in your own organization — every user you see or create here
belongs to your tenant alone; you can never see or touch another
organization's users.

## Adding a user

Give them a User ID (their login — unique across the whole system, not
just your organization), a role, and a temporary password. Pass that
password to them directly (not by email). They'll be required to choose
their own password the first time they log in, and you'll see a one-time
recovery phrase right after — pass that along too, since it's the only way
they can reset their own password later without coming back to you.

## Roles

- **User** — regular day-to-day access.
- **Tenant Admin** — everything a User can do, plus this screen, plus
  System Management's account/retention/audit-log settings.

You can't demote yourself, and GSS won't let you deactivate or demote the
last active Tenant Admin in your organization — someone always has to be
able to manage users.

## Resetting a password

If someone's forgotten both their password and their recovery phrase, reset
it here. This sets a new temporary password and a new recovery phrase
(shown once, same as when adding a user) — it does **not** touch any of
your organization's encrypted data, since login and field encryption are
kept deliberately separate (see System Management).

## Deactivating a user

Deactivated users can't log in, but their history (who created/changed what)
stays intact in the audit log. Reactivate them the same way at any time.
