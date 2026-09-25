// Granite Signal Systems website -- lead-intake configuration.
//
// LEAD_INTAKE_TOKEN authorizes this site to create ONE thing in the GSS
// platform: a new Opportunity for the Granite Signal Systems tenant. It is
// meant to be public (it's sitting right here in this file, viewable by
// anyone) -- see the GSS System Management > Lead Intake config screen for
// the full explanation of what this token can and can't do.
//
// TODO (Zeb): replace REPLACE_WITH_LEAD_INTAKE_TOKEN below with the real
// token before this site goes live. Get it from:
//   GSS app -> System Management -> Config -> "Lead Intake Config" ->
//   Intake token (Copy button)
// The form will show a clear "Invalid token" error and nothing will be
// lost if this is deployed with the placeholder still in place -- it just
// won't be able to submit until the real token is pasted in here.
const GSS_LEAD_INTAKE_ENDPOINT = "https://app.ipromise.com/api/public/leads";
const GSS_LEAD_INTAKE_TOKEN = "REPLACE_WITH_LEAD_INTAKE_TOKEN";
