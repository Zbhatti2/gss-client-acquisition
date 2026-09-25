CONTACT_BODY = """
<header class="gss-page-header">
  <div class="container">
    <h1 class="h2 mb-2">Let's Talk About Your Intake Process</h1>
    <p class="mb-0">We work with small businesses and service companies across New Hampshire &mdash; garden and lawn maintenance, auto services, contractors, tree services, septic, HVAC, plumbing, roofing, and related trades.</p>
  </div>
</header>

<section class="py-5">
  <div class="container">
    <div class="row justify-content-center text-center mb-5">
      <div class="col-lg-8">
        <p class="fs-4 gss-quote d-inline-block text-start">What happens today if a new quote request comes in at 7:30 at night, or while everybody is out in the field?</p>
        <p class="text-muted">That's the question that starts every conversation.</p>
      </div>
    </div>

    <div class="row gy-5">
      <div class="col-lg-5">
        <div class="gss-eyebrow mb-3">Get in Touch</div>
        <ul class="list-unstyled mb-4">
          <li class="d-flex gap-2 mb-3">
            <i class="bi bi-envelope text-success mt-1"></i>
            <span><strong>Email:</strong> <a href="mailto:hello@granitesignalsystems.com">hello@granitesignalsystems.com</a><br>
            <span class="text-muted small">(placeholder &mdash; replace with actual business email)</span></span>
          </li>
          <li class="d-flex gap-2 mb-3">
            <i class="bi bi-telephone text-success mt-1"></i>
            <span><strong>Phone:</strong> <span class="text-muted">(placeholder &mdash; replace with actual business phone)</span></span>
          </li>
          <li class="d-flex gap-2 mb-3">
            <i class="bi bi-geo-alt text-success mt-1"></i>
            <span><strong>Service Area:</strong> New Hampshire &mdash; Lakes Region, Kearsarge Area, Central NH, and expanding</span>
          </li>
          <li class="d-flex gap-2 mb-0">
            <i class="bi bi-mailbox text-success mt-1"></i>
            <span><strong>Mailing Address:</strong> <span class="text-muted">(placeholder &mdash; valid postal address required for commercial email compliance)</span></span>
          </li>
        </ul>

        <div class="gss-eyebrow mb-3">What to Expect</div>
        <ol class="mb-0">
          <li class="mb-2"><strong>A short conversation.</strong> We'll ask about your inbound inquiry flow, who handles it, and what happens after hours.</li>
          <li class="mb-2"><strong>A 10-minute demo.</strong> We'll run a fake customer through the system using your real services and towns &mdash; no access to your systems needed.</li>
          <li class="mb-0"><strong>A clear yes or no.</strong> If you already handle every inquiry in minutes, we'll tell you. If there's a gap, we'll show you exactly what the system does and what it costs.</li>
        </ol>
      </div>

      <div class="col-lg-7">
        <div class="p-4 p-lg-5 gss-card">
          <h2 class="h5 mb-3">Send Us a Message</h2>
          <div id="gss-form-status" class="alert gss-form-status" role="alert"></div>
          <form id="gss-contact-form" novalidate>
            <div class="row g-3">
              <div class="col-12">
                <label class="form-label" for="organization_name">Business / Company Name <span class="text-danger">*</span></label>
                <input type="text" class="form-control" id="organization_name" name="organization_name" required>
              </div>
              <div class="col-sm-6">
                <label class="form-label" for="contact_name">Your Name</label>
                <input type="text" class="form-control" id="contact_name" name="contact_name">
              </div>
              <div class="col-sm-6">
                <label class="form-label" for="contact_phone">Phone</label>
                <input type="tel" class="form-control" id="contact_phone" name="contact_phone">
              </div>
              <div class="col-12">
                <label class="form-label" for="contact_email">Email</label>
                <input type="email" class="form-control" id="contact_email" name="contact_email">
              </div>
              <div class="col-12">
                <label class="form-label" for="message">What's happening with your inbound inquiries today?</label>
                <textarea class="form-control" id="message" name="message" rows="4"></textarea>
              </div>
              <!-- Honeypot: real visitors never see this field; a bot filling every input will fill it too. -->
              <div class="gss-hp-field" aria-hidden="true">
                <label for="website">Leave this field empty</label>
                <input type="text" id="website" name="website" tabindex="-1" autocomplete="off">
              </div>
              <div class="col-12">
                <button type="submit" id="gss-form-submit" class="btn btn-lg w-100" style="background-color: var(--gss-green-700); color: #fff;">Send Message</button>
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>

    <div class="row justify-content-center mt-5">
      <div class="col-lg-9">
        <div class="p-4 gss-card bg-white text-center">
          <p class="mb-2">If you already respond to nearly every inbound inquiry within minutes, have reliable after-hours coverage, use a mature CRM/dispatch process, track every lead, and have no intake pain &mdash; tell us. We'll tell you we probably can't add enough value.</p>
          <p class="fw-semibold mb-0">We'd rather turn down a bad fit than take your money and underdeliver.</p>
        </div>
      </div>
    </div>
  </div>
</section>

<script src="js/config.js"></script>
<script src="js/contact-form.js"></script>
"""
