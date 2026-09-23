---
title: Table Maintenance Overview
order: 1
keywords: [lookup, picklist, dropdown, category, type]
---
Table Maintenance is where every dropdown/picklist used throughout GSS —
Contact Categories, Organization Types, Knowledge Domains, and the rest —
gets managed. Pick a table from the list to see its entries.

## What's on each table's list

Every table shows the same shape: Code (optional), Label, Description,
Sort order, Status, and how many records currently use each entry. Lists
sort alphabetically by Label, so a freshly added entry appears in place
immediately.

## Editing vs. deleting

- **Editing** a label updates it everywhere that entry is already
  used — instantly, with no other action needed, since every record
  stores a link to the entry, not a copy of its text.
- **Deleting** an entry that's still in use isn't allowed outright — GSS
  sends you to **Merge into...** instead, so you can move those records to
  a different entry first (or just deactivate it, which hides it from new
  selections without touching anything already using it).

## Nested tables

Some tables (like SubDomains, nested under Domains) require picking a
parent when adding or editing an entry — the parent list itself only
shows active parents, so you can't accidentally nest something under a
deactivated one.
