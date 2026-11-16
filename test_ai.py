"""Gemini-assisted question extraction for NEURON V2 online tests.

The deterministic parser remains the fallback. This module never publishes a test:
every extracted question must be reviewed by the teacher before publication.
"""
import asyncio
import base64
import json
import os
import re

from gemini_manager import gemini_generate


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
MAX_QUESTIONS = 101


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
        if question_type == "written":
            options = []
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


def _parse_model_json(data):
    candidates = (data or {}).get("candidates") or []
    if not candidates:
        return None
    parts = (candidates[0].get("content") or {}).get("parts") or []
    raw = "\\n".join(str(p.get("text") or "") for p in parts if isinstance(p, dict)).strip()
    if not raw:
        return None
    raw = re.sub(r"^\\s*```(?:json)?\\s*|\\s*```$", "", raw, flags=re.I)
    return json.loads(raw)


async def _gemini_json(model, parts, schema, max_tokens=16000):
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }
    data, status = await gemini_generate(model, payload, timeout_seconds=100)
    if status != "ok":
        return None, status
    try:
        parsed = _parse_model_json(data)
        return (parsed, "ok") if isinstance(parsed, dict) else (None, "empty_ai_response")
    except Exception:
        return None, "ai_parse_error"


async def extract_questions_with_gemini(filename, raw):
    """Return (questions, status). Empty questions means use deterministic fallback."""
    extension = str(filename or "").lower().rsplit(".", 1)[-1]
    parts = [{
        "text": (
            "You are extracting an exam from a teacher-provided document. "
            "Return ONLY questions genuinely present in the source; never invent or guess. "
            "Preserve the source language and wording. Separate every question from its options. "
            "A), B), C), D) labels are options, not question text. Keep source order. "
            "If fewer than two clear options exist, mark it written and return no options. "
            "Ignore page numbers, headers, footers, answer keys and unrelated paragraphs. "
            "For diagrams, keep the question and do not invent image descriptions. "
            "Return at most 101 questions in source order. Omit unclear/non-question text."
        )
    }]
    try:
        if extension == "pdf":
            if len(raw) > 10_000_000:
                return [], "file_too_large_for_ai"
            parts.append({"inlineData": {
                "mimeType": "application/pdf",
                "data": base64.b64encode(raw).decode("ascii"),
            }})
        elif extension == "docx":
            text_value, image_parts = _docx_parts(raw)
            if not text_value and not image_parts:
                return [], "empty_document"
            parts.append({"text": "DOCX text content:\\n" + text_value[:180_000]})
            parts.extend(image_parts)
        else:
            return [], "unsupported_file"
        model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
        parsed, status = await _gemini_json(model, parts, QUESTION_SCHEMA)
        if not parsed:
            return [], status
        questions = _clean_questions(parsed)
        return (questions, "ok") if questions else ([], "no_questions_found")
    except asyncio.TimeoutError:
        return [], "timeout"
    except Exception:
        return [], "ai_parse_error"


def _year_tokens(value):
    # Three- or four-digit historical years are strict; surrounding suffixes such as "-yil" are ignored.
    return set(re.findall(r"(?<!\\d)([1-9]\\d{2,3})(?!\\d)", str(value or "")))


async def grade_written_answer(question_text, reference_answer, student_answer):
    """Semantically grade one written response; exact historical years are enforced locally."""
    reference = " ".join(str(reference_answer or "").split()).strip()
    answer = " ".join(str(student_answer or "").split()).strip()
    if not reference or not answer:
        return None, "needs_review"
    required_years = _year_tokens(reference)
    submitted_years = _year_tokens(answer)
    if required_years and submitted_years != required_years:
        return {"score": 0, "confidence": 1.0,
                "feedback": "Tarixiy yil aniq mos kelmadi."}, "ok"

    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    schema = {
        "type": "OBJECT",
        "properties": {
            "correct": {"type": "BOOLEAN"},
            "confidence": {"type": "NUMBER"},
            "feedback": {"type": "STRING"},
        },
        "required": ["correct", "confidence", "feedback"],
    }
    prompt = (
        "You are a careful school-exam marker. Grade the student's answer against the teacher's reference answer. "
        "Judge meaning and essential facts, not exact wording. Accept minor spelling mistakes, a missing/extra "
        "single letter, common Uzbek apostrophe variants, and harmless grammatical differences when the intended "
        "meaning is unmistakably correct. Do not accept a different person, place, event, cause, result, or fact. "
        "Do not invent facts or give credit for vague related text. If uncertain, return confidence below 0.82. "
        "Historical years are strict: a wrong, missing, or additional conflicting year is incorrect. "
        "Return JSON only.\nQUESTION: " + str(question_text)[:3000] +
        "\\nTEACHER REFERENCE: " + reference[:3000] +
        "\\nSTUDENT ANSWER: " + answer[:3000]
    )
    parsed, status = await _gemini_json(model, [{"text": prompt}], schema, max_tokens=500)
    if not parsed:
        return None, status
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0))))
        correct = bool(parsed.get("correct"))
        feedback = " ".join(str(parsed.get("feedback") or "").split())[:300]
    except Exception:
        return None, "ai_parse_error"
    if confidence < 0.82:
        return {"score": 0, "confidence": confidence, "feedback": feedback}, "needs_review"
    return {"score": 1 if correct else 0, "confidence": confidence, "feedback": feedback}, "ok"
