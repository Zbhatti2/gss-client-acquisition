---
title: Domains & Sub-Domains
order: 3
keywords: [domain, subdomain, sub-domain, industry, sector, classification]
---
**Domain** and **SubDomain** classify what industry/sector an organization
operates in — Domain is the broad category (e.g. "Software & Technology"),
SubDomain is the specific slice within it (e.g. "Cloud Infrastructure").

## The Domain -> SubDomain relationship

Every SubDomain belongs to exactly one Domain. On the New/Edit
Organization form, picking a Domain narrows the SubDomain dropdown to only
the SubDomains under it — so a SubDomain always makes sense for the Domain
it's paired with.

## Managing the lists themselves

Domains and SubDomains are both managed from **Utilities > Table
Maintenance**, under "Organization Classification Group." Adding a new
SubDomain requires choosing its parent Domain — that pairing is what
drives the cascading dropdown on the Organization form. Both lists sort
alphabetically, so a newly added entry shows up in its place right away.

## Merging near-duplicates

If two SubDomains turn out to mean the same thing (e.g. "Cloud" and "Cloud
Computing"), use **Merge into...** from the Table Maintenance list for
that table — it moves every organization pointing at the old entry over
to the one you keep, then optionally deletes the old one.
