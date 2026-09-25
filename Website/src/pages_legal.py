LEGAL_BODY = """
<header class="gss-page-header">
  <div class="container">
    <h1 class="h2 mb-2">Legal &amp; Compliance</h1>
    <p class="mb-0">Keeping your data safe and your business clean.</p>
  </div>
</header>

<section class="py-5">
  <div class="container">
    <div class="gss-eyebrow mb-3">Our Compliance Model</div>
    <div class="table-responsive">
      <table class="table gss-table align-middle">
        <thead>
          <tr><th style="width: 28%;">Area</th><th>Launch Rule</th></tr>
        </thead>
        <tbody>
          <tr><td class="fw-semibold">Customer/contractor outreach</td><td>Manual B2B email and live business calls. Follow CAN-SPAM for commercial email.</td></tr>
          <tr><td class="fw-semibold">Homeowner SMS</td><td>Only within the client's approved messaging program and documented opt-in/use case. Uses A2P 10DLC for U.S. 10-digit business texting.</td></tr>
          <tr><td class="fw-semibold">Web forms</td><td>Uses an unchecked consent checkbox and required disclosures appropriate to the message type. Marketing and non-marketing consent are separated where required.</td></tr>
          <tr><td class="fw-semibold">Missed-call text-back</td><td>Not activated blindly. Only activated after approval from the client's use case/message first.</td></tr>
          <tr><td class="fw-semibold">AI voice</td><td>The FCC treats current AI-generated human voices as artificial/prerecorded voice technology under TCPA rules.</td></tr>
          <tr><td class="fw-semibold">Safety/pricing</td><td>AI never gives any binding quotes or makes emergency, structural, electrical, insurance, legal, or safety decisions.</td></tr>
          <tr><td class="fw-semibold">Identity</td><td>AI never claims to be a human employee. It identifies the actual business and, if asked, truthfully says it is an automated assistant.</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>

<section class="py-5 gss-section-alt">
  <div class="container">
    <div class="row justify-content-center">
      <div class="col-lg-9">
        <div class="gss-eyebrow mb-3 text-center">The Core Safety Rule</div>
        <div class="p-4 p-lg-5 gss-card bg-white">
          <p>Granite Signal Systems sells business-to-business services. Our automation system contacts the client/contractor's own inbound leads and customers only under an approved consent/use-case framework.</p>
          <div class="row gy-3 mt-2">
            <div class="col-md-4 text-center">
              <i class="bi bi-x-circle text-danger fs-3"></i>
              <p class="small fw-semibold mb-0 mt-2">We do NOT buy lists of homeowners.</p>
            </div>
            <div class="col-md-4 text-center">
              <i class="bi bi-x-circle text-danger fs-3"></i>
              <p class="small fw-semibold mb-0 mt-2">We do NOT scrape mobile numbers.</p>
            </div>
            <div class="col-md-4 text-center">
              <i class="bi bi-x-circle text-danger fs-3"></i>
              <p class="small fw-semibold mb-0 mt-2">We do NOT cold-text your consumers.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="py-5">
  <div class="container">
    <div class="row gy-4">
      <div class="col-lg-6">
        <div class="gss-eyebrow mb-3">What Our Client Agreement Says</div>
        <ul class="list-unstyled">
          <li class="d-flex gap-2 mb-3"><i class="bi bi-check2 text-success mt-1"></i><span>Client owns/controls its leads and is responsible for the legal basis to contact them.</span></li>
          <li class="d-flex gap-2 mb-3"><i class="bi bi-check2 text-success mt-1"></i><span>Client approves scripts, channels, and use cases before activation.</span></li>
          <li class="d-flex gap-2 mb-3"><i class="bi bi-check2 text-success mt-1"></i><span>Client remains responsible for quotes, work, safety, licenses, warranties, and customer promises.</span></li>
          <li class="d-flex gap-2 mb-3"><i class="bi bi-check2 text-success mt-1"></i><span>No guarantee of leads, revenue, closed jobs, or appointment volume.</span></li>
          <li class="d-flex gap-2 mb-3"><i class="bi bi-check2 text-success mt-1"></i><span>Opt-outs are honored and suppression records maintained.</span></li>
          <li class="d-flex gap-2 mb-0"><i class="bi bi-check2 text-success mt-1"></i><span>Data access, security, retention, breach/incident handling, and third-party vendors are addressed.</span></li>
        </ul>
      </div>
      <div class="col-lg-6">
        <div class="gss-eyebrow mb-3">What Our AI NEVER Decides</div>
        <div class="row row-cols-1 row-cols-sm-2 g-2">
          __NEVER_DECIDES__
        </div>
      </div>
    </div>
  </div>
</section>

<section class="py-5 gss-section-alt">
  <div class="container">
    <div class="gss-eyebrow mb-3 text-center">Data We Protect</div>
    <div class="row gy-4 mt-1">
      <div class="col-lg-6">
        <div class="p-4 gss-card bg-white h-100">
          <h3 class="h6 mb-3"><i class="bi bi-check-circle text-success"></i> What the AI is allowed to collect</h3>
          <ul class="small mb-0">
            <li>Name/contact information already supplied or voluntarily provided</li>
            <li>Property town/address when needed for service</li>
            <li>Service requested</li>
            <li>Brief description</li>
            <li>Urgency</li>
            <li>Preferred callback/estimate time</li>
            <li>Optional photos relevant to the estimate request</li>
          </ul>
        </div>
      </div>
      <div class="col-lg-6">
        <div class="p-4 gss-card bg-white h-100">
          <h3 class="h6 mb-3"><i class="bi bi-shield-x text-danger"></i> What it will never collect</h3>
          <ul class="small mb-0">
            <li>Social Security number</li>
            <li>Bank password/login</li>
            <li>Full card information in chat</li>
            <li>Medical information unrelated to the service</li>
            <li>Detailed insurance claim strategy</li>
            <li>Sensitive identity documents, unless a separately reviewed legitimate process requires them</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</section>
"""

NEVER_DECIDES = [
    "Final price or binding estimate",
    "Whether a dangerous tree/roof is safe",
    "Electrical/utility hazards",
    "Emergency response guarantees",
    "Insurance coverage or claim outcome",
    "Legal responsibility/liability",
    "Structural diagnosis",
    "Financing eligibility",
    "Contract terms beyond approved factual language",
]
_nd_html = []
for item in NEVER_DECIDES:
    _nd_html.append(f"""
          <div class="col"><div class="d-flex gap-2 align-items-start p-2"><i class="bi bi-slash-circle text-danger mt-1"></i><span class="small">{item}</span></div></div>""")
LEGAL_BODY = LEGAL_BODY.replace("__NEVER_DECIDES__", "".join(_nd_html))
