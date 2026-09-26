---
title: System Management Overview
order: 1
keywords: [account, retention, purge, backup, audit log, health, lead intake, website, token, notification email]
---
System Management covers your organization's account settings, not any
one record — most of it (retention, backups) is restricted to Tenant
Admins.

## Retention & purge

Set **data retention days** to have deleted records permanently erased
(archive snapshot and all) that many days after their original date of
entry — leave it blank for indefinite retention. This runs automatically
once a day at login; **Run purge now** runs it on demand instead of
waiting.

## Lead Intake Config

**Tenant Admin only.** Click **Config** on the Account card to connect
your organization's own public website's contact form directly into
Client Acquisition — a submission there creates an Opportunity here with
no one on your team re-typing it in.

- **Notification email** — where a "new lead" email is sent when someone
  submits the form (leave blank and leads still save, you just won't get
  an email about them).
- **Intake token** — a long random value that authenticates the
  website's submissions as belonging to your organization specifically.
  This page shows a ready-to-paste snippet with your real token already
  filled in, for whoever maintains your website. It's meant to live in
  that site's public JavaScript — it can only ever create one Opportunity
  per submission, nothing more, so that exposure is by design, not a
  mistake.
- **Regenerate** — issues a brand-new token and immediately invalidates
  the old one, if you ever need to cut off a website's access (e.g. it's
  been retired or the value leaked somewhere it shouldn't have).

## Database health

A one-click SQLite integrity check plus table counts and file size —
worth running if something seems off, before assuming there's a bigger
problem. **System Admin only** — the database file is shared by every
tenant, so this isn't something any one tenant's admin can run.

## Audit log

Every create/update/delete/login/import/export/purge in your own tenant is
recorded here, searchable and filterable — this is what to check first
when you need to know who changed something and when.

## Backup & restore

Create an on-demand backup of the whole database, review past backups, or
restore from one. GSS also takes an automatic safety backup right before
any restore, so a restore can itself be undone. **System Admin only** —
restoring a backup replaces every tenant's data, not just yours, so this
lives with the platform-wide admin rather than any one tenant's admin. If
you need something backed up or restored, contact your System Admin.
