# Feature ideas

## Azure STT with automatic Groq fallback

Recorded: 2026-10-06. Status: deferred idea, not implemented.

For the production tutor, consider using Azure Speech's F0 allowance of five
speech-to-text hours per month, then automatically falling back to the existing
Groq `whisper-large-v3-turbo` model when that allowance is exhausted. Resume Azure
when the allowance renews. Students should not need to select a provider or
record their question again.

This concerns STT (student speech to written text), not TTS (the tutor's spoken
answer). Current STT remains Groq; current TTS remains Azure Speech.

### Keep the implementation simple

- First compare Arabic transcription accuracy and latency on real student
  recordings. Prefer Azure only if its quality or another practical benefit
  justifies maintaining two providers.
- Verify the Azure resource is F0 and the chosen transcription API supports that
  tier. F0 permits only one concurrent real-time transcription; overlapping
  requests could go directly to Groq.
- Start with Azure first and retry the same recording through Groq if Azure is
  unavailable or rejects it. Distinguish exhausted allowance from temporary
  throttling and configuration errors; do not treat every failure as monthly
  exhaustion. Record the reason for fallback.
- Avoid a usage-counter database, quota polling, and monthly reset machinery
  initially. Add them only if repeated failures or operational needs justify
  the complexity. If caching quota exhaustion later, verify the actual renewal
  boundary before deciding when to resume Azure.

At the prices checked on 2026-10-06, five hours on Groq's current model cost
about $0.20 ($0.04 per audio hour, with a ten-second minimum per request).
Free Azure usage alone offers limited savings; production simplicity and Arabic
accuracy should drive the decision.

References: [Azure Speech pricing](https://azure.microsoft.com/en-us/pricing/details/speech/),
[Azure Speech limits](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits),
and [Groq STT pricing](https://console.groq.com/docs/speech-to-text).

## Azure TTS: use F0 first, then manually upgrade to S0

Recorded: 2026-10-08. Status: agreed plan, not applied.

Use the existing `testinfuturix` Speech resource on the **Azure for Students**
subscription, starting with its F0 allowance of **500,000 neural TTS characters
per month**. When usage approaches that limit, manually upgrade the same resource
to S0. Subsequent paid usage should consume the student subscription's credit.
No automatic provider fallback or quota-counter database is planned.

### Current resources and migration

- As checked on 2026-10-08, both the local and hosted tutor use
  `hsa0234708-0866-resource`, S0, `swedencentral`, on the separate Free Trial
  subscription called `Azure subscription 1`.
- That trial credit expires **2026-10-18 at 19:31 UTC / 22:31 Jordan time**.
  Move TTS before then so trial expiry does not interrupt spoken answers.
- The student resource `testinfuturix` is currently F0 in
  `germanywestcentral`. Azure lists both F0 and S0 as available tiers for it.
  Before switching, test Arabic synthesis with `ar-SA-HamedNeural` there.
- To move the tutor to the student resource, update the private
  `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` configuration and restart the
  service after active requests finish. Keep the existing voice and text
  normalization. Verify spoken answers through the dev LMS before production.
  Keep credentials out of GitHub.

### Manual upgrade reminder

- Check Azure's **Synthesized Characters** metric using **Sum** for the current
  month. F0 does not automatically start spending student credit when its
  allowance is exhausted; further synthesis requests are rejected until the
  allowance resets or the resource is upgraded.
- Upgrade **before** all 500,000 characters are exhausted: Azure warns that
  updated quotas can take several hours to apply. Waiting until requests fail
  could interrupt TTS.
- Changing the existing resource's tier does not require a second resource or
  an application fallback implementation. Verify synthesis after the upgrade.
- S0 does not include F0's monthly free allowance and does not automatically
  return to F0 next month. This is a manual transition to paid usage, not an
  automatic monthly free-then-paid cycle.

References: [Azure Speech pricing](https://azure.microsoft.com/en-us/pricing/details/speech/),
[Azure Speech limits and tier-change delay](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits),
[Azure student credit](https://learn.microsoft.com/en-us/azure/education-hub/navigate-costs).
