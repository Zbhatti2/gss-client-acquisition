---
title: Data Exchange Overview
order: 1
keywords: [import, export, csv, vcard, json, business card, ads]
---
Data Exchange is where bulk data moves in and out of GSS.

## Importing

- **Import Contacts / Organizations from CSV** — uploaded files are staged
  and validated first; nothing reaches your live data until you review
  the results and commit. A rejected or partially-erroring batch never
  half-applies itself.
- **Import Business Card (AI)** and **Import Ads/Flyers (AI)** — reads a
  photo and pre-fills a form for you to review before saving, rather than
  creating a record automatically. These need an Anthropic API key
  configured by a Tenant Admin; if that isn't set up yet, the button tells
  you what's missing rather than failing silently.

Every import batch you've run is listed under **Recent import batches**,
with a **Review** link back into it.

## Exporting

Choose a module (Contacts, Organizations, or Documents) and a format —
available formats depend on the module, since not every shape fits every
format (Documents, for instance, only exports as JSON). Exported files
contain **decrypted, plaintext data** — treat them as carefully as any
other sensitive export, and delete them once you no longer need them.

Past exports stay listed under **Recent exports** so you can download
one again without re-running it.
