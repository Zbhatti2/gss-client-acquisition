# Granite Signal Systems website

Static marketing / lead-capture site for `www.granitesignalsystems.com`.
Six plain HTML pages, Bootstrap 5 (CDN), a green brand palette, and a
contact form that POSTs directly to the GSS platform's public lead-intake
API (`js/config.js` + `js/contact-form.js`) -- no backend of its own.

## Before this goes live

`js/config.js` ships with a placeholder token:

```js
const GSS_LEAD_INTAKE_TOKEN = "REPLACE_WITH_LEAD_INTAKE_TOKEN";
```

Replace it with the real one from the GSS app: **System Management ->
Config -> Lead Intake Config -> Intake token**. That page also has a
ready-to-paste snippet with your actual token already filled in.

## Regenerating the pages

The six `.html` files (plus `404.html`) are generated, not hand-edited --
their source lives in `src/` (`generate.py` + `pages_*.py`, one file per
page's content, assembled through `build.py`'s shared nav/header/footer).
To make a content change:

1. Edit the relevant `src/pages_*.py`.
2. From this directory: `python3 src/generate.py`
3. Commit the regenerated `.html` files (the source `src/` files too, so
   the next edit starts from the same place).

`src/` itself is never deployed (see `.dockerignore`) -- only the
generated `.html`/`css`/`js`/`images` files are.

## Deploying

Same flow as the main GSS app: push to this repo's `main` branch, Coolify
(the "Granite Signal Systems" project, same VPS2 Ubuntu box as
`app.ipromise.com`) rebuilds and redeploys automatically. The `Dockerfile`
here just serves these static files with nginx -- no database, no
persistent volume, no environment variables needed.
