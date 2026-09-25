#!/usr/bin/env python3
"""Assembles the static Granite Signal Systems site from shared nav/footer
partials + per-page content. Not part of the deployed site itself -- run
once to produce the final flat .html files, matching how a static site
generator would work, minus any actual dependency."""
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

PAGES = [
    ("index.html", "Home"),
    ("why-you-need-this.html", "Why You Need This"),
    ("legal-compliance.html", "Legal &amp; Compliance"),
    ("how-it-works.html", "How It Works"),
    ("ai-stack.html", "The AI Stack"),
    ("contact.html", "Contact"),
]

NAV_LABELS = {
    "index.html": "Home",
    "why-you-need-this.html": "Why You Need This",
    "legal-compliance.html": "Legal &amp; Compliance",
    "how-it-works.html": "How It Works",
    "ai-stack.html": "The AI Stack",
    "contact.html": "Contact",
}


def nav_html(current):
    links = []
    for href, label in NAV_LABELS.items():
        active = " active" if href == current else ""
        aria = ' aria-current="page"' if href == current else ""
        links.append(f'<li class="nav-item"><a class="nav-link{active}" href="{href}"{aria}>{label}</a></li>')
    return "\n            ".join(links)


HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | Granite Signal Systems</title>
<meta name="description" content="{description}">
<link rel="icon" type="image/svg+xml" href="images/favicon.svg">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css" rel="stylesheet">
<link href="css/style.css" rel="stylesheet">
</head>
<body>
"""

HEADER = """<nav class="navbar navbar-expand-lg gss-navbar sticky-top py-3">
  <div class="container">
    <a class="navbar-brand" href="index.html">
      <span class="gss-logo-mark">GSS</span>
      <span>Granite Signal Systems</span>
    </a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#gssNav" style="border-color: rgba(255,255,255,0.4);">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="gssNav">
      <ul class="navbar-nav ms-auto align-items-lg-center gap-lg-1">
            {nav_links}
        <li class="nav-item ms-lg-3 mt-2 mt-lg-0">
          <a class="btn btn-login btn-sm px-3" href="https://app.ipromise.com/login">
            <i class="bi bi-box-arrow-in-right"></i> Client Login
          </a>
        </li>
      </ul>
    </div>
  </div>
</nav>
"""

FOOTER = """<footer class="gss-footer mt-5">
  <div class="container">
    <div class="row gy-4">
      <div class="col-md-5">
        <div class="d-flex align-items-center gap-2 mb-2">
          <span class="gss-logo-mark">GSS</span>
          <strong class="text-white">Granite Signal Systems</strong>
        </div>
        <p class="small mb-0">Managed AI lead response for New Hampshire's field-service contractors.</p>
      </div>
      <div class="col-md-3">
        <div class="text-white fw-semibold mb-2 small text-uppercase" style="letter-spacing:0.06em;">Site</div>
        <ul class="list-unstyled small">
          <li class="mb-1"><a href="index.html">Home</a></li>
          <li class="mb-1"><a href="why-you-need-this.html">Why You Need This</a></li>
          <li class="mb-1"><a href="legal-compliance.html">Legal &amp; Compliance</a></li>
          <li class="mb-1"><a href="how-it-works.html">How It Works</a></li>
          <li class="mb-1"><a href="ai-stack.html">The AI Stack</a></li>
          <li class="mb-1"><a href="contact.html">Contact</a></li>
        </ul>
      </div>
      <div class="col-md-4">
        <div class="text-white fw-semibold mb-2 small text-uppercase" style="letter-spacing:0.06em;">Get in touch</div>
        <ul class="list-unstyled small">
          <li class="mb-1"><i class="bi bi-envelope me-1"></i> <a href="mailto:hello@granitesignalsystems.com">hello@granitesignalsystems.com</a></li>
          <li class="mb-1"><i class="bi bi-telephone me-1"></i> (placeholder phone number)</li>
          <li class="mb-1"><i class="bi bi-geo-alt me-1"></i> New Hampshire &mdash; Lakes Region, Kearsarge Area, Central NH, and expanding</li>
          <li class="mt-2"><a href="https://app.ipromise.com/login"><i class="bi bi-box-arrow-in-right"></i> Client Login</a></li>
        </ul>
      </div>
    </div>
    <hr style="border-color: rgba(255,255,255,0.15);" class="my-4">
    <div class="d-flex flex-column flex-sm-row justify-content-between small">
      <span>&copy; <span id="gss-year"></span> Granite Signal Systems. All rights reserved.</span>
      <span>Contact information on this site is a placeholder pending final setup.</span>
    </div>
  </div>
</footer>
<script>document.getElementById("gss-year").textContent = new Date().getFullYear();</script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
"""

TAIL = """</body>
</html>
"""


def wrap(filename, title, description, body):
    head = HEAD.format(title=title, description=description)
    header = HEADER.format(nav_links=nav_html(filename))
    return head + header + body + FOOTER + TAIL


def write(filename, title, description, body):
    content = wrap(filename, title, description, body)
    path = os.path.join(OUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"wrote {filename} ({len(content)} bytes)")
