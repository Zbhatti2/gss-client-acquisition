import sys
sys.path.insert(0, ".")
from build import write
from pages_home import HOME_BODY
from pages_why import WHY_BODY
from pages_legal import LEGAL_BODY
from pages_how import HOW_BODY
from pages_ai import AI_BODY
from pages_contact import CONTACT_BODY

write("index.html", "Home",
      "Managed AI lead response for New Hampshire's field-service contractors. Never miss another call, never lose another job.",
      HOME_BODY)

write("why-you-need-this.html", "Why You Need This",
      "Why field-service businesses need managed lead response, even if they already use some AI tools.",
      WHY_BODY)

write("legal-compliance.html", "Legal & Compliance",
      "Granite Signal Systems' compliance model, client agreement terms, and what our AI never decides.",
      LEGAL_BODY)

write("how-it-works.html", "How It Works",
      "How the Granite Signal Lead Response System works, from inbound inquiry to booked estimate.",
      HOW_BODY)

write("ai-stack.html", "The AI Stack",
      "What each AI tool and model in the Granite Signal Systems stack actually does.",
      AI_BODY)

write("contact.html", "Contact",
      "Get in touch with Granite Signal Systems to talk about your intake process.",
      CONTACT_BODY)

NOT_FOUND_BODY = """
<section class="py-5">
  <div class="container text-center py-5">
    <h1 class="display-5 mb-3">Page Not Found</h1>
    <p class="text-muted mb-4">The page you're looking for doesn't exist or has moved.</p>
    <a href="index.html" class="btn btn-lg" style="background-color: var(--gss-green-700); color:#fff;">Back to Home</a>
  </div>
</section>
"""
write("404.html", "Page Not Found", "Page not found.", NOT_FOUND_BODY)

print("Done.")
