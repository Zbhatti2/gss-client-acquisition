HOW_BODY = """
<header class="gss-page-header">
  <div class="container">
    <h1 class="h2 mb-2">How the Granite Signal Lead Response System Works</h1>
    <p class="mb-0">We sell one standardized result: faster, structured handling of your own inbound requests.</p>
  </div>
</header>

<section class="py-5">
  <div class="container">
    <div class="row justify-content-center text-center mb-4">
      <div class="col-lg-8">
        <p class="fs-5">We do not sell a menu of random AI services &mdash; every client gets the same reliable system, tuned to their business.</p>
      </div>
    </div>
    <div class="gss-eyebrow mb-3 text-center">What Every Standard Client Receives</div>
    <div class="row gy-3">
      __COMPONENTS__
    </div>
  </div>
</section>

<section class="py-5 gss-section-alt">
  <div class="container">
    <div class="gss-eyebrow mb-3 text-center">Example: Tree Service Web Inquiry</div>
    <div class="table-responsive">
      <table class="table gss-table bg-white align-middle">
        <thead>
          <tr><th style="width:16%;">Moment</th><th style="width:42%;">System Action</th><th>What Homeowner Experiences</th></tr>
        </thead>
        <tbody>
          <tr><td class="fw-semibold">0 min</td><td>Form creates contact/opportunity</td><td class="text-muted">Nothing complicated; their request has been received</td></tr>
          <tr><td class="fw-semibold">0&ndash;2 min</td><td>Approved acknowledgment from the actual tree company</td><td class="text-muted">&ldquo;We received your request&hellip;&rdquo; and one simple question</td></tr>
          <tr><td class="fw-semibold">Conversation</td><td>AI asks service/town/problem/urgency/preferred time</td><td class="text-muted">Short one-question-at-a-time exchange</td></tr>
          <tr><td class="fw-semibold">Safety keyword</td><td>Stops normal bot flow; alerts human</td><td class="text-muted">No AI diagnosis. Human takes over.</td></tr>
          <tr><td class="fw-semibold">Qualified</td><td>Books approved estimate OR creates callback task</td><td class="text-muted">Clear next step</td></tr>
          <tr><td class="fw-semibold">No response</td><td>One approved follow-up at the client's approved interval</td><td class="text-muted">Reminder, not harassment</td></tr>
          <tr><td class="fw-semibold">Second no response</td><td>Optional second and final approved follow-up</td><td class="text-muted">Then automation stops</td></tr>
          <tr><td class="fw-semibold">Opt-out</td><td>DND/suppression</td><td class="text-muted">No more automated SMS</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>

<section class="py-5 text-center">
  <div class="container">
    <h2 class="h3 mb-3">Curious which model does what?</h2>
    <a href="ai-stack.html" class="btn btn-lg" style="background-color: var(--gss-green-700); color:#fff;">See the AI Stack</a>
  </div>
</section>
"""

COMPONENTS = [
    ("telephone-inbound", "Inbound response layer", "Immediate acknowledgment for approved web inquiries; missed-call follow-up can be added only after the client's use case and consent process are reviewed."),
    ("clipboard-check", "Qualification", "Service, town/ZIP, short problem description, urgency, preferred contact time, and optional photo request."),
    ("signpost-split", "Routing", "Estimate booking where appropriate, otherwise a clean callback task and owner notification."),
    ("shield-check", "Guardrails", "No binding quote, no unsafe diagnosis, no invented availability, automatic human handoff for emergencies/uncertainty."),
    ("kanban", "CRM visibility", "Every inquiry moves through a visible pipeline instead of disappearing in voicemail, email, or memory."),
    ("eye", "Monitoring", "Failure review, opt-out review, transcript sampling, one controlled improvement at a time."),
    ("bar-chart-line", "Monthly proof", "Response metrics, conversations, bookings/callbacks, handoffs, errors, and changes made."),
]
_comp_html = []
for icon, title, desc in COMPONENTS:
    _comp_html.append(f"""
      <div class="col-md-6 col-lg-4">
        <div class="p-4 gss-card h-100">
          <div class="gss-icon-badge mb-3"><i class="bi bi-{icon}"></i></div>
          <h3 class="h6 mb-2">{title}</h3>
          <p class="small text-muted mb-0">{desc}</p>
        </div>
      </div>""")
HOW_BODY = HOW_BODY.replace("__COMPONENTS__", "".join(_comp_html))
