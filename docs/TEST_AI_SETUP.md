# NEURON V2 — Gemini AI test module setup

## Render Environment Variables

Set these on the NEURON V2 Render service:

- `GEMINI_API_KEYS`: up to 10 Gemini keys, separated by commas or new lines. Example format only: `key1,key2,key3`.
- `GEMINI_API_KEY`: optional legacy/single-key fallback; can be kept while migrating.
- `GEMINI_MODEL`: optional; defaults to `gemini-3.8-flash`.

Do not paste real keys into GitHub, source code, Telegram, or ChatGPT. Add them only in Render Environment settings. The application masks keys in status output and never logs full key values.

The manager rotates keys, skips keys in cooldown, and tries another configured key after rate limits, invalid credentials, transient server errors, or timeouts. It tracks per-key success/error counters in process memory and exposes safe, masked status in the Super Admin overview API. Counters reset when the service restarts.

**Quota warning:** key rotation does not multiply quota when keys belong to the same Google Cloud project. Gemini quotas are generally project/model/tier based. Separate keys help with credential isolation and rotation; independent project quotas require separately configured projects and must follow Google's terms. Do not create multiple projects to evade provider limits.

## Test extraction

1. Teacher uploads PDF/DOCX.
2. Gemini parses source questions and options; deterministic parser is fallback.
3. Teacher reviews every question and provides the correct choice or reference answer for written questions.
4. Nothing is published until the teacher confirms the answer key.

## Written-answer grading

- Gemini grades by meaning and essential facts, not exact character matching.
- Minor spelling, apostrophe, and one-letter mistakes are tolerated when the intended meaning is clearly correct.
- Historical years found in the teacher's reference answer are checked strictly before AI grading. A missing, different, or extra year results in an incorrect answer.
- Low-confidence or unavailable-AI results remain pending for teacher review.
- AI does not see or change the student's answer key; it grades only after submission.

## Privacy

Google's Gemini API free tier may use submitted content to improve Google's products. Use anonymized test papers only; do not send student names, phone numbers, grades, or other personal information. Review current Google AI Studio/API terms and quotas before production use.

## Official references

- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/document-processing
- https://ai.google.dev/gemini-api/docs/models
