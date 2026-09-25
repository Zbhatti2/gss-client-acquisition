HOME_BODY = """
<section class="gss-hero">
  <div class="container">
    <div class="row align-items-center gy-4">
      <div class="col-lg-7">
        <div class="gss-eyebrow mb-2" style="color: #bfe8cd;">Missed calls become missed revenue</div>
        <h1 class="display-5 mb-3">Your Inquiries Deserve an Answer. Not a Voicemail.</h1>
        <p class="lead mb-4">Granite Signal Systems manages the lead response system that sits between your incoming inquiries and your crew &mdash; so every request gets acknowledged, qualified, and routed while you're still on the job.</p>
        <div class="d-flex flex-wrap gap-2">
          <a href="contact.html" class="btn btn-primary btn-lg px-4">Get in Touch</a>
          <a href="how-it-works.html" class="btn btn-outline-light btn-lg px-4">See How It Works</a>
        </div>
      </div>
      <div class="col-lg-5">
        <div class="p-4 rounded-4" style="background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.18);">
          <h2 class="h4 text-white mb-3">Never Miss Another Call. Never Lose Another Job.</h2>
          <p class="mb-0">Put Granite Signal Systems in front of your inbound calls so your business can answer every customer, book the appointment, and keep opportunities moving to the next step.</p>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="py-5">
  <div class="container">
    <div class="row justify-content-center text-center">
      <div class="col-lg-8">
        <div class="gss-eyebrow mb-2">The Business in One Sentence</div>
        <p class="fs-5">We provide an AI system that responds to your own inbound calls and inquiries, gathers approved information details, and moves qualified prospects to an estimate or callback &mdash; while you remain responsible for prices, safety, and final decisions.</p>
      </div>
    </div>
  </div>
</section>

<section class="py-5 gss-section-alt">
  <div class="container">
    <div class="row gy-4 align-items-start">
      <div class="col-lg-6">
        <div class="gss-eyebrow mb-2">Sound Familiar?</div>
        <ul class="list-unstyled">
          <li class="d-flex gap-2 mb-3"><i class="bi bi-check2-circle text-success mt-1"></i><span>You're on a roof, in a bucket truck, in a basement, or driving when the next estimate request comes in.</span></li>
          <li class="d-flex gap-2 mb-3"><i class="bi bi-check2-circle text-success mt-1"></i><span>A homeowner submits a form or calls after hours &mdash; and nobody responds until tomorrow.</span></li>
          <li class="d-flex gap-2 mb-3"><i class="bi bi-check2-circle text-success mt-1"></i><span>You have a contact form and maybe a CRM, but there's no reliable first-five-minute process.</span></li>
          <li class="d-flex gap-2 mb-3"><i class="bi bi-check2-circle text-success mt-1"></i><span>Evenings, weekends, storms, and simultaneous calls create gaps you can't staff around.</span></li>
          <li class="d-flex gap-2 mb-0"><i class="bi bi-check2-circle text-success mt-1"></i><span>You don't want another software project. You want fewer missed opportunities and cleaner information waiting for you.</span></li>
        </ul>
      </div>
      <div class="col-lg-6">
        <div class="p-4 gss-card bg-white h-100 d-flex align-items-center">
          <p class="fs-5 fw-semibold mb-0">Granite Signal Systems fixes the gap between the inquiry arriving and somebody on your crew actually having time to respond.</p>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="py-5">
  <div class="container">
    <div class="gss-eyebrow mb-2 text-center">What We Do &mdash; and What We Don't</div>
    <div class="row gy-4 mt-2">
      <div class="col-md-6">
        <div class="p-4 gss-card h-100">
          <h3 class="h5 mb-3"><i class="bi bi-x-circle text-danger"></i> We are NOT selling leads.</h3>
          <ul class="mb-0">
            <li>We do not generate homeowner interest.</li>
            <li>We do not promise a number of jobs.</li>
            <li>We improve the speed and consistency with which your business handles inquiries it already receives.</li>
          </ul>
        </div>
      </div>
      <div class="col-md-6">
        <div class="p-4 gss-card h-100">
          <h3 class="h5 mb-3"><i class="bi bi-check-circle text-success"></i> We offer a managed follow-up system.</h3>
          <ul class="mb-0">
            <li>Immediate acknowledgment for approved inbound calls / inquiries</li>
            <li>Structured qualification using questions you approve</li>
            <li>Clean callback tasks and estimate routing</li>
            <li>Human handoff for safety, pricing, legal, and uncertain situations</li>
            <li>Ongoing monitoring, failure review, and system maintenance</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="py-5 gss-section-alt">
  <div class="container">
    <div class="gss-eyebrow mb-4 text-center">The Flow</div>
    <div class="row gy-3 text-center">
      __FLOW_STEPS__
    </div>
  </div>
</section>

<section class="py-5">
  <div class="container">
    <div class="gss-eyebrow mb-4 text-center">Which Small Businesses Do We Serve</div>
    <div class="row gy-3">
      __INDUSTRY_CARDS__
    </div>
  </div>
</section>

<section class="py-5 gss-section-alt">
  <div class="container">
    <div class="row justify-content-center">
      <div class="col-lg-9 text-center">
        <p class="gss-quote fs-4 mb-0">&ldquo;You are not paying us for access to advanced AI to help your business grow. You are paying us to virtually install, test, and manage the calls and leads intake system around your business so you do not have to build and babysit it yourself.&rdquo;</p>
      </div>
    </div>
  </div>
</section>

<section class="py-5">
  <div class="container text-center">
    <h2 class="h3 mb-3">Ready to stop losing jobs to missed calls?</h2>
    <a href="contact.html" class="btn btn-lg" style="background-color: var(--gss-green-700); color: #fff;">Talk to Us</a>
  </div>
</section>
"""

FLOW_STEPS = [
    ("1", "Homeowner submits an approved inquiry."),
    ("2", "Your CRM creates the contact."),
    ("3", "Automated acknowledgment is sent."),
    ("4", "AI asks only the questions you've approved."),
    ("5", "Information is saved to your pipeline."),
    ("6", "Estimate or callback is booked &mdash; or a human task is created."),
    ("7", "You take over."),
]

_flow_html = []
for n, text in FLOW_STEPS:
    _flow_html.append(f"""
      <div class="col-6 col-md-3 col-lg-3 col-xl-3">
        <div class="p-3 h-100">
          <div class="gss-icon-badge mx-auto mb-2 fw-bold">{n}</div>
          <p class="small mb-0">{text}</p>
        </div>
      </div>""")
HOME_BODY = HOME_BODY.replace("__FLOW_STEPS__", "".join(_flow_html))

INDUSTRIES = [
    ("tree", "Tree Services &amp; Land Clearing", "field crews, storm demand, large-ticket work, simple first qualification"),
    ("droplet", "Septic / Drain / Pumping", "urgency, owner-operator shops, high-ticket repairs"),
    ("thermometer-half", "HVAC / Plumbing", "strong urgency and replacement/repair economics"),
    ("house-gear", "Roofing / Exteriors", "high ticket and quote forms common"),
    ("water", "Well / Pump / Water Treatment", "urgent no-water situations and valuable installs"),
    ("cone-striped", "Excavation / Sitework", "high-value inquiries; owners frequently in field"),
    ("stars", "Commercial &amp; Domestic Cleaning", "recurring service scheduling and inquiry intake"),
]
_industry_html = []
for icon, name, desc in INDUSTRIES:
    _industry_html.append(f"""
      <div class="col-md-6 col-lg-4">
        <div class="p-4 gss-card h-100">
          <div class="gss-icon-badge mb-3"><i class="bi bi-{icon}"></i></div>
          <h3 class="h6 mb-2">{name}</h3>
          <p class="small text-muted mb-0">{desc}</p>
        </div>
      </div>""")
HOME_BODY = HOME_BODY.replace("__INDUSTRY_CARDS__", "".join(_industry_html))
