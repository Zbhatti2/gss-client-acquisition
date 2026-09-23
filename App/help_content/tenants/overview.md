---
title: Tenant Management
order: 1
keywords: [tenant, organization, new tenant, provision, suspend, system admin]
---
**System Admin only.** This is the platform-wide console for creating and
overseeing every organization (tenant) hosted on this GSS install — distinct
from System Management, which is each organization's own settings screen.

## Creating a tenant

**New Tenant** creates a brand-new, fully isolated organization: its own
data, its own encryption key, and its first Tenant Admin login. Give that
admin their temporary password directly — they'll be required to set their
own on first login, and you'll see a one-time recovery phrase to pass along
with it. From there, that Tenant Admin adds their own teammates from
Manage Users; you don't need to create every user yourself.

## Suspending a tenant

Suspending a tenant immediately blocks every one of its users from logging
in, without deleting anything — reactivate it at any time to restore
access exactly as it was. Nothing about the tenant's data changes either
way.

## What's tenant-scoped vs. platform-wide

A System Admin account has no organization of its own — it exists to run
the platform, not to hold data. Database Health and Backup & Restore (under
System Management) are System Admin actions for the same reason: the
database file underneath every tenant is one shared file, so restoring a
backup affects everyone, not just one organization.
