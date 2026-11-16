"""Gemini-assisted question extraction for NEURON V2 online tests.

The deterministic parser remains the fallback. This module never publishes a test:
every extracted question must be reviewed by the teacher before publication.
"""
import base64
import json
import os
import re

import aiohttp


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
MAX_QUESTIONS = 100


QUESTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "questions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING"},
                    "type": {"type": "STRING", "enum": ["choice", "written"]},
                    "options": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {"text": {"type": "STRING"}},
                            "required": ["text"],
                        },
                    },
                },
                "required": ["text", "type", "options"],
            },
        }
    },
    "required": ["questions"],
}


def _docx_parts(raw):
    """Return readable DOCX text and a small set of embedded images."""
    from docx import Document

    doc = Document(__import__("io").BytesIO(raw))
    text_blocks = []
    for paragraph in doc.paragraphs:
        value = (paragraph.text or "").strip()
        if value:
            text_blocks.append(value)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                text_blocks.append(" | ".join(cells))

    image_parts = []
    total = 0
    for rel in doc.part.rels.values():
        if "image" not in rel.reltype:
            continue
        part = rel.target_part
        blob = getattr(part, "blob", b"")
        mime = getattr(part, "content_type", "image/png") or "image/png"
        if not blob or len(image_parts) >= 12 or total + len(blob) > 5_000_000:
            continue
        if not mime.startswith("image/"):
            continue
        image_parts.append({
            "inlineData": {
                "mimeType": mime,
                "data": base64.b64encode(blob).decode("ascii"),
            }
        })
        total += len(blob)
    return "\n".join(text_blocks), image_parts


def _clean_questions(value):
    if not isinstance(value, dict):
        return []
    source = value.get("questions")
    if not isinstance(source, list):
        return []
    result = []
    for item in source:
        if not isinstance(item, dict):
            continue
        question_text = " ".join(str(item.get("text") or "").split()).strip()
        if not question_text:
            continue
        raw_options = item.get("options")
        options = []
        if isinstance(raw_options, list):
            for option in raw_options[:6]:
                if isinstance(option, dict):
                    option_text = " ".join(str(option.get("text") or "").split()).strip()
                else:
                    option_text = " ".join(str(option or "").split()).strip()
                if option_text:
                    options.append({"key": "ABCDEF"[len(options)], "text": option_text})
        question_type = "choice" if len(options) >= 2 else "written"
        result.append({
            "id": len(result) + 1,
            "text": question_text[:5000],
            "options": options,
            "images": [],
            "type": question_type,
        })
        if len(result) >= MAX_QUESTIONS:
            break
    return result


async def extract_questions_with_gemini(filename, raw):
    """Return (questions, status). Empty questions means use deterministic fallback."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return [], "not_configured"

    extension = str(filename or "").lower().rsplit(".", 1)[-1]
    parts = [{
        "text": (
            "You are extracting an exam from a teacher-provided document. "
            "Return ONLY questions that genuinely appear in the source; never invent, "
            "rewrite, complete, or guess missing content. Preserve the original language "
            "(Uzbek, Russian, English, etc.) and wording. Separate every question from its "
            "answer choices. A), B), C), D) labels are choices, not question text. "
            "Keep choices in source order. If a question has fewer than two clear choices, "
            "mark it as written and return an empty options array. Ignore page numbers, "
            "headers, footers, answer keys, explanations, and unrelated paragraphs. "
            "If a diagram or picture is part of a question, keep the question text and "
            "do not invent a description. Return at most 100 questions in source order. "
            "If the source is not a test or the question is unclear, omit it rather than guess. "
            "The document may contain multiple questions on one page."
        )
    }]

    try:
        if extension == "pdf":
            if len(raw) > 10_000_000:
                return [], "file_too_large_for_ai"
            parts.append({
                "inlineData": {
                    "mimeType": "application/pdf",
                    "data": base64.b64encode(raw).decode("ascii"),
                }
            })
        elif extension == "docx":
            text_value, image_parts = _docx_parts(raw)
            if not text_value and not image_parts:
                return [], "empty_document"
            parts.append({"text": "DOCX text content:\n" + text_value[:180_000]})
            parts.extend(image_parts)
        else:
            return [], "unsupported_file"

        model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
        url = GEMINI_API_URL.format(model=model)
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 16000,
                "responseMimeType": "application/json",
                "responseSchema": QUESTION_SCHEMA,
            },
        }
        timeout = aiohttp.ClientTimeout(total=100, connect=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, params={"key": api_key}, json=payload) as response:
                if response.status != 200:
                    # Do not log or return the request URL because it contains the API key.
                    if response.status == 429:
                        return [], "rate_limited"
                    if response.status in (401, 403):
                        return [], "invalid_api_key"
                    return [], "provider_error_" + str(response.status)
                data = await response.json(content_type=None)

        candidates = data.get("candidates") or []
        if not candidates:
            return [], "empty_ai_response"
        response_parts = (candidates[0].get("content") or {}).get("parts") or []
        response_text = "\n".join(
            str(part.get("text") or "") for part in response_parts if isinstance(part, dict)
        ).strip()
        if not response_text:
            return [], "empty_ai_response"
        response_text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", response_text, flags=re.I)
        parsed = json.loads(response_text)
        questions = _clean_questions(parsed)
        return (questions, "ok") if questions else ([], "no_questions_found")
    except asyncio.TimeoutError:
        return [], "timeout"
    except Exception:
        return [], "ai_parse_error"


# Imported only for explicit timeout handling; kept separate from the main bot module.
import asyncio
