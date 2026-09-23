# GSS in-app help content

This folder is the source of everything shown in the in-app Help panel
(the "?" button on most forms) — see `blueprints/help.py`. It is **not**
served as a help page itself (only files inside a section subfolder are);
it's just documentation for whoever edits this content next.

## Adding a page to an existing section

Drop a `<page-name>.md` file into the section's folder, with front matter
at the top:

```markdown
---
title: Human-Readable Title
order: 2
keywords: [a, few, search, terms]
---
Your Markdown content starts here.
```

- `title` — shown in the tree and as the page heading. Optional; falls
  back to the file name, title-cased.
- `order` — controls position within the section (lower first, ties break
  alphabetically by title). Optional; defaults to last.
- `keywords` — extra terms the drawer's search box matches against,
  beyond the title itself. Optional.

The page's `help_id` — what a form's "?" button links to — is always
`<section-folder-name>/<file-name-without-.md>`. There's nothing else to
register; it appears in the tree automatically on the next request.

## Adding a new section

Create a new folder here. Optionally add a `_section.json` inside it:

```json
{"title": "Human-Readable Section Title", "order": 5}
```

Both fields are optional — without one, the folder name is title-cased
and it sorts after every explicitly-ordered section.

## Linking a form's "?" button to a page

In the template, use the `help_button` macro from `_macros.html`:

```jinja
{% from "_macros.html" import help_button %}
...
{{ help_button('organizations/new-organization') }}
```

If the `help_id` doesn't resolve to a real page, the drawer just opens to
the tree root instead of erroring — so it's safe to add a button before
its page exists, or to rename a page's file (update the button's
`help_id` to match).

## What NOT to do here

- Don't nest a section folder inside another section folder — only one
  level of folders is walked.
- Don't rely on HTML inside these Markdown files being sanitized — it
  isn't (these files are trusted, git-controlled content, not end-user
  input), so don't paste in untrusted Markdown from outside the team.
