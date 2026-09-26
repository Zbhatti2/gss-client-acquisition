---
title: Pipeline Templates
order: 3
keywords: [pipeline template, stage, checklist, cadence, master template, system admin, win criteria]
---
A Pipeline Template is the named sequence of stages an Opportunity moves
through. Each stage has a **typical window** (days, used to flag an
Opportunity as aging), a **win probability %**, a **checklist** of
required/optional actions, and an **outreach cadence** (day offset +
action + channel) that auto-generates tasks when an Opportunity enters
that stage.

## Your own templates

Reach this from **Pipeline Templates** on the Client Acquisition
dashboard. Every tenant gets its own copy of GSS's starter template(s)
automatically when the tenant is created — editing your copy here only
ever affects your own organization's Opportunities.

- **New Template** — start a fresh one; give it a name and (optionally) a
  win-criteria note.
- **Add Stage** — name, typical window in days, and win probability %.
- **Checklist** (per stage) — add an item and mark it required or
  optional; a required item blocks advancing past that stage without an
  explicit override.
- **Outreach Cadence** (per stage) — a day offset, an action label, and a
  channel (Call, Email, LinkedIn, etc.); these become auto-generated tasks
  the moment an Opportunity enters that stage.
- **Delete Template** — removes the template and everything under it
  (stages, checklist, cadence). This doesn't touch Opportunities already
  using it; they keep their own already-snapshotted stage/checklist
  history.

## Master templates (System Admin)

**Master Pipeline Templates** (visible only to System Admin) edits the
platform-wide master copies that new tenants clone from when they're
first provisioned. Editing a master template shapes what *future* tenants
start with — it never reaches back and changes any tenant's own,
already-cloned copy.
