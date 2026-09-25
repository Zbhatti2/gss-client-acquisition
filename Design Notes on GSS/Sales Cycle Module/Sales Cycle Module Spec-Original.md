# Sales Cycle Module — Simplified & Template-able Design

## Design Principle
Separate the **Engine** (fixed, universal — build this once) from the **Content** (industry-specific — configurable per template, no code changes needed).

- **Engine** = the stages, the interaction log, the dashboards.
- **Content** = the labels, the checklists, the "what good looks like" per industry — stored as data, not hardcoded.

This means a landscaping company and a B2B SaaS company run on the *same tables and dashboards*, just with different template data loaded in.

---

## Part 1: The Universal Engine — 5 Stages (not 9)

The original doc's 9 steps collapse cleanly into 5 stages. Nothing is lost — the sub-steps become **checklist items inside a stage**, not separate stages.

| # | Stage | Replaces (from original doc) | Core Question Answered |
|---|-------|-------------------------------|--------------------------|
| 1 | **Discover** | ICP Refinement, Lead Gen, Research & Trigger Events | Is this a real, qualified target? |
| 2 | **Engage** | Multi-Channel Cadence | Have we earned a conversation? |
| 3 | **Qualify** | Discovery Call, Mutual Action Plan | Do they have a real problem, budget, and timeline? |
| 4 | **Present** | Demo/POC, War Room/Stakeholder Mapping | Have we proven we solve their specific pain? |
| 5 | **Close** | Commercial Proposal & Closure | Signed and handed to delivery/success? |

Every deal also carries one of two side-states at any time:
- **Nurture** (flowed back — not dead, just not active right now)
- **Lost/Disqualified** (with a required reason code)

This directly preserves your "sieve, not a line" insight from the oraaS) |
| stage_checklist | What "done" looks like at each stage (configurable list) |
| default_cadence | Suggested touchpoint sequence for Engage stage |
| win_criteria_prompt | e.g. "Reduce load time 40%" vs "Quote accepted" |

### `deals` (or `opportunities`)
One row per prospective sale, linked to a client/company record you already have.
| Field | Notes |
|---|---|
| deal_id | |
| client_id | FK to your existing Client table |
| template_id | which industry template this deal follows |
| current_stage | 1–5, or Nurture/Lost |
| stage_entered_date | drives "days in stage" |
| economic_buyer_contact_id | who signs |
| champion_contact_id | who advocates internally |
| deal_value | |
| probability | auto or manual % |
| next_action | free text |
| next_action_date | |
| lost_reason | populated only if status = Lost |

### `interactions` (the heart of your "how/when/what" requirement)
One row per touchpoint — this is your universal log, works identically for a phone call, an email, a Loom video, or a mailed postcard.
| Field | Notes |
|---|---|
| interaction_id | |
| deal_id | FK |
| date | |
| channel | call / email / LinkedIn / text / in-person / mail / video |
| direction | outbound / inbound |
| summary | free text — what was said/asked |
| material_shared | e.g. "ROI one-pager," "MAP PDF," "brochure" — could be a file link |
| outcome | e.g. "booked next call," "no response," "objection: price" |
| logged_by | user/rep |

### `stage_checklist_progress`
Tracks which checklist items (from the template) are done for a given deal, so a stage isn't just a label — it's a set of completed sub-tasks.
| Field | Notes |
|---|---|
| deal_id | |
| checklist_item | pulled from template |
| is_complete | bool |
| completed_date | |

---

## Part 3: Per-Client Dashboard (what you see on one deal)

A single-deal view should show, top to bottom:

1. **Header**: Client name, current stage (as a progress bar: Discover → Engage → Qualify → Present → Close), days in current stage, deal value, probability.
2. **Next Action** panel: what to do next and when — pulled straight from `next_action` / `next_action_date`.
3. **Stage Checklist**: the industry-template checklist for the current stage, with checkboxes.
4. **Interaction Timeline**: reverse-chronological feed from the `interactions` table — every call, email, meeting, material sent, with outcome tags. This is your "how, when, what material" requirement, fully satisfied by one table.
5. **Stakeholders**: Economic Buyer / Champion, contact info, pulled from your existing Client/Contact tables.
6. **Risk flags** (auto-generated, not manually entered):
   - Stalled: no interaction logged in X days
   - Aging: in current stage longer than template's typical window
   - Ghosted: last 2+ outreach attempts show no response

---

## Part 4: Main Dashboard (the big picture across all deals)

1. **Funnel view**: count and $ value of deals in each of the 5 stages (a simple horizontal bar or funnel chart).
2. **Conversion rates**: % of deals moving stage-to-stage (Discover→Engage, Engage→Qualify, etc.) — tells you where your process leaks.
3. **This week's actions**: every deal with a `next_action_date` in the next 7 days, sorted by date.
4. **Stalled/At-risk list**: auto-flagged deals from Part 3, item 6, aggregated.
5. **By template/industry filter**: if you run multiple templates, let this dashboard filter/segment by `template_id`.
6. **Time-in-cycle stat**: average days from Discover to Close, compared against the template's target (your original doc's "30–90 days, disqualify past 90" rule becomes a configurable field per template, not a hardcoded rule).

---

## Part 5: How Templating Actually Works Day-to-Day

When you onboard a new industry (say, a plumbing business vs. a marketing agency), you don't touch the engine. You just fill in a new `pipeline_templates` row:

- Rename the 5 stages to fit their language (e.g., "Present" might become "Quote/Estimate" for a trades business).
- Swap the stage checklists (a plumber's "Qualify" checklist might be "confirm address, confirm urgency, confirm budget range" instead of SPIN-framework questions).
- Adjust the default cadence (a local service business might do 3 touches over 5 days instead of 12–15 touches over 3 weeks).
- Set the win-criteria prompt and the disqualify-after-X-days rule.

Everything downstream — the deal table, interaction log, both dashboards — works unchanged.

---

## What This Simplification Preserves From Your Original Doc
- The "sieve, not a straight line" flow-back logic (Nurture / re-quantify-value loop)
- The distinction between Economic Buyer and Champion
- The idea of a documented "win criteria" before evaluation starts
- The disqualify-after-N-days rule (now configurable per template instead of fixed at 90 days)

## What Got Cut (intentionally, as content not engine)
- Specific channels (LinkedIn, Loom, ZoomInfo) — these live as *suggested defaults* in a template's cadence field, not as required steps
- SPIN framework specifics — becomes a stage checklist item for templates that want it
- CFO/CTO one-pagers — becomes a "material_shared" entry logged like anything else
