from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from src.config import ROOT, load_config, project_path
from src.query.retrieve import retrieve

load_dotenv(ROOT / ".env")

DISCLAIMER = "Facts-only. No investment advice."
SYSTEM_PROMPT = """You are a facts-only mutual fund FAQ assistant.
Use only the retrieved chunks. Do not invent numbers or advice.
Answer in at most 3 sentences.
Do not calculate or compare returns.
Do not tell the user to buy or sell.
Citation URL must be the source_url provided in the user message, not a URL you remember.
"""


def _cap_sentences(text: str, n: int = 3) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    return " ".join(parts[:n])


def _last_updated(hits: list[dict]) -> str:
    stamps = [h.get("fetched_at") for h in hits if h.get("fetched_at")]
    if not stamps:
        return ""
    stamps.sort()
    raw = stamps[-1]
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return raw[:10]


def _pick_hit(question: str, hits: list[dict]) -> dict:
    q = (question or "").lower()
    hints = (
        ("expense_ratio", ("expense",)),
        ("exit_load", ("exit load", "exit-load")),
        ("min_sip", ("sip",)),
        ("min_investment", ("lumpsum", "minimum investment", "1st investment")),
        ("lock_in", ("lock-in", "lock in")),
        ("riskometer", ("riskometer", "risk")),
        ("benchmark", ("benchmark",)),
        ("aum", ("aum", "fund size")),
    )
    for field, words in hints:
        if any(word in q for word in words):
            for hit in hits:
                if hit.get("field") == field:
                    return hit
    return hits[0]


def _extractive_answer(question: str, retrieval: dict) -> str:
    if retrieval.get("message") and not retrieval.get("in_corpus"):
        return _cap_sentences(retrieval["message"])
    hits = retrieval.get("hits") or []
    if not hits:
        return "This fact is not in the listed Groww HDFC corpus."
    hit = _pick_hit(question, hits)
    text = hit["text"]
    scheme = hit.get("scheme_name") or "the scheme"
    snippet = text[:420].rsplit(" ", 1)[0]
    return _cap_sentences(f"{scheme}: {snippet}.")


def _groq_answer(question: str, retrieval: dict) -> tuple[str, dict | None]:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    if not api_key or not model:
        return _extractive_answer(question, retrieval), None

    hits = retrieval.get("hits") or []
    context = [
        {
            "field": h.get("field"),
            "scheme_name": h.get("scheme_name"),
            "url": h.get("url"),
            "fetched_at": h.get("fetched_at"),
            "text": h.get("text"),
        }
        for h in hits[:4]
    ]
    user = (
        f"Question: {question}\n"
        f"source_url: {retrieval.get('source_url')}\n"
        f"Retrieved chunks JSON:\n{json.dumps(context, ensure_ascii=False)}\n"
        "Write at most 3 factual sentences. Do not include a Source line; the app will add it."
    )
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    }
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    text = body["choices"][0]["message"]["content"]
    return _cap_sentences(text), body


def answer_question(question: str) -> dict:
    cfg = load_config()
    retrieval = retrieve(question)
    used_llm = False
    raw_completion = None

    if retrieval.get("refused"):
        text = retrieval.get("message") or "I cannot answer that."
        source_url = retrieval.get("source_url")
        last_updated = ""
    elif not retrieval.get("in_corpus"):
        text = retrieval.get("message") or "This fact is not in the listed Groww HDFC corpus."
        source_url = None
        last_updated = ""
    else:
        try:
            text, raw_completion = _groq_answer(question, retrieval)
            used_llm = raw_completion is not None
        except requests.RequestException:
            text = _extractive_answer(question, retrieval)
            used_llm = False
        source_url = retrieval.get("source_url")
        last_updated = _last_updated(retrieval.get("hits") or [])
        if retrieval.get("intent") == "returns":
            text = _cap_sentences(
                (retrieval.get("message") or "")
                + " Open the official source for published figures; this assistant does not compute returns."
            )

    result = {
        "query_id": retrieval.get("query_id"),
        "text": _cap_sentences(text),
        "source_url": source_url,
        "last_updated_from_sources": last_updated,
        "refused": bool(retrieval.get("refused")),
        "in_corpus": bool(retrieval.get("in_corpus")),
        "disclaimer": DISCLAIMER,
        "used_llm": used_llm,
        "retrieval": {
            "intent": retrieval.get("intent"),
            "reason": retrieval.get("reason"),
            "scheme_filter": retrieval.get("scheme_filter"),
            "best_similarity": retrieval.get("best_similarity"),
            "hits": [
                {
                    "id": h.get("id"),
                    "field": h.get("field"),
                    "similarity": h.get("similarity"),
                    "url": h.get("url"),
                }
                for h in (retrieval.get("hits") or [])
            ],
        },
    }

    if os.getenv("VERCEL"):
        out_dir = Path("/tmp/answers")
    else:
        out_dir = project_path(cfg["paths"]["artifacts_answers"])
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {"answer": result, "raw_completion": raw_completion}
        (out_dir / f"{retrieval['query_id']}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    return result


def list_stage_files() -> dict:
    cfg = load_config()

    def listing(rel: str) -> list[dict]:
        path = project_path(rel) if rel != "chroma" else project_path(cfg["chroma"]["persist_dir"])
        if not path.exists():
            return []
        items = []
        if path.is_file():
            items.append({"name": path.name, "bytes": path.stat().st_size})
            return items
        for child in sorted(path.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_file():
                items.append({"name": child.name, "bytes": child.stat().st_size})
        return items[:40]

    return {
        "raw": listing(cfg["paths"]["raw"]),
        "cleaned": listing(cfg["paths"]["cleaned"]),
        "chunks": listing(cfg["paths"]["chunks"]),
        "embeddings": listing(cfg["paths"]["embeddings"]),
        "chroma": listing("chroma"),
        "retrieval": listing(cfg["paths"]["artifacts_retrieval"]),
        "answers": listing(cfg["paths"]["artifacts_answers"]),
    }
