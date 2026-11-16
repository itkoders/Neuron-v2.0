# NEURON V2 — Gemini test extraction setup

## Environment variables (Render)

Add these variables to the NEURON V2 web service:

- `GEMINI_API_KEY`: API key created in Google AI Studio. Keep it secret; never put it in GitHub or send it in Telegram/chat.
- `GEMINI_MODEL`: optional; defaults to `gemini-3.8-flash`.

After saving environment variables, trigger a manual deploy. If the key is absent, NEURON uses its deterministic PDF/DOCX parser and does not call Gemini.

## Extraction flow

1. Existing PDF/DOCX parser extracts a first-pass question set and document images.
2. Gemini receives the PDF itself (native document/vision input) or DOCX text plus embedded images.
3. Gemini returns structured JSON containing question text, type, and answer choices.
4. NEURON validates and caps the result at 100 questions.
5. The existing teacher editor remains mandatory. The test is not published until the teacher reviews the questions and sets the correct answer key.
6. If Gemini is unavailable, rate-limited, or returns invalid data, the parser fallback remains available.

## Privacy note

Google's Gemini API free tier may use submitted content to improve Google's products. Do not upload files containing student names, phone numbers, grades, or other personal information to the free tier. Use anonymized test papers. Check the current Google AI Studio/API terms and quota before production use.

## Current provider references

- Pricing and free-tier details: https://ai.google.dev/gemini-api/docs/pricing
- PDF document understanding: https://ai.google.dev/gemini-api/docs/document-processing
- Model information: https://ai.google.dev/gemini-api/docs/models
