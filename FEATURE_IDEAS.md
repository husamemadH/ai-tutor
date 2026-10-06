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
