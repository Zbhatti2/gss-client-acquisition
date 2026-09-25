// Granite Signal Systems -- contact form submit handler.
// Posts directly to the GSS platform's public lead-intake endpoint
// (see js/config.js) -- no server-side code on this site at all.
document.addEventListener("DOMContentLoaded", function () {
  var form = document.getElementById("gss-contact-form");
  if (!form) return;

  var statusBox = document.getElementById("gss-form-status");
  var submitBtn = document.getElementById("gss-form-submit");

  function showStatus(message, isError) {
    statusBox.textContent = message;
    statusBox.classList.remove("alert-success", "alert-danger");
    statusBox.classList.add(isError ? "alert-danger" : "alert-success");
    statusBox.classList.add("gss-visible");
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();

    if (!GSS_LEAD_INTAKE_TOKEN || GSS_LEAD_INTAKE_TOKEN.indexOf("REPLACE_WITH") === 0) {
      showStatus("This form isn't fully set up yet -- please call or email us directly using the details on this page.", true);
      return;
    }

    var payload = {
      token: GSS_LEAD_INTAKE_TOKEN,
      organization_name: form.organization_name.value.trim(),
      contact_name: form.contact_name.value.trim(),
      contact_email: form.contact_email.value.trim(),
      contact_phone: form.contact_phone.value.trim(),
      message: form.message.value.trim(),
      website: form.website.value // honeypot -- always sent, should stay empty
    };

    if (!payload.organization_name) {
      showStatus("Please tell us your business/company name.", true);
      return;
    }
    if (!payload.contact_name && !payload.contact_email && !payload.contact_phone) {
      showStatus("Please give us a name, email, or phone number so we can reach you.", true);
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Sending...";

    fetch(GSS_LEAD_INTAKE_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (data) { return { status: r.status, data: data }; }); })
      .then(function (result) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Send Message";
        if (result.data && result.data.ok) {
          showStatus("Thanks -- your message is in. We'll be in touch shortly.", false);
          form.reset();
        } else {
          showStatus((result.data && result.data.error) || "Something went wrong sending your message -- please try again or contact us directly.", true);
        }
      })
      .catch(function () {
        submitBtn.disabled = false;
        submitBtn.textContent = "Send Message";
        showStatus("We couldn't reach the server -- please try again in a moment, or contact us directly.", true);
      });
  });
});
