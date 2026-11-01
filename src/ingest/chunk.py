from __future__ import annotations

import hashlib
import json
import re

from src.config import load_config, project_path
from src.ingest.create_dirs import create_directories

FIELD_PATTERNS: list[tuple[str, list[str]]] = [
    ("expense_ratio", [r"expense\s*ratio.{0,80}"]),
    ("exit_load", [r"exit\s*load.{0,180}"]),
    ("min_sip", [r"min(?:imum)?\.?\s*(?:for\s*)?sip.{0,80}", r"minimum sip investment.{0,80}"]),
    ("min_investment", [r"min(?:imum)?\.?\s*for 1st investment.{0,80}", r"minimum lumpsum investment.{0,80}"]),
    ("lock_in", [r"lock[- ]in.{0,160}", r"mandatory\s+(?:period|lock).{0,80}"]),
    ("riskometer", [r"riskometer.{0,80}", r"rated\s+(?:low|moderate|high|very high)\s+risk.{0,40}", r"\bvery high risk\b"]),
    ("benchmark", [r"fund benchmark.{0,120}", r"benchmark[:\s]+[A-Za-z0-9][^\n]{0,80}"]),
    ("aum", [r"fund size\s*\(aum\).{0,80}", r"asset under management.{0,80}"]),
    ("category", [r"category average \(\s*equity [a-z ]+\)", r"is a [a-z ]+mutual fund scheme"]),
]

NOISE_MARKERS = (
    "download the app groww",
    "nifty 50 options",
    "brokerage calculator",
    "stocks : a b c",
    "compare mutual funds best debt",
    "groww terminal",
    "option chain",
    "mf screener",
)

RETURNS_NOISE = ("would've become", "historic returns", "compare similar funds")


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def _window(text: str, start: int, end: int, pad: int = 80) -> str:
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    snippet = text[lo:hi].strip()
    return re.sub(r"\s+", " ", snippet)


def _field_score(field: str, snippet: str) -> int:
    s = snippet.lower()
    score = 1
    if field == "expense_ratio":
        if re.search(r"expense ratio\s+[\d.]+%", s):
            score += 5
        if "illustrative" in s or "historical and for illustrative" in s:
            score -= 5
    elif field == "exit_load":
        if "redeem" in s:
            score += 5
        if re.search(r"\d+(?:\.\d+)?%", s):
            score += 2
        if "fee payable" in s:
            score -= 3
    elif field == "min_sip":
        if "₹" in snippet or "rs" in s:
            score += 4
        if "return calculator" in s:
            score -= 2
    elif field == "riskometer":
        if "rated" in s and "risk" in s:
            score += 4
    elif field == "benchmark":
        if "nifty" in s or "bse" in s or "sensex" in s:
            score += 4
    elif field == "lock_in":
        if "3 year" in s or "three year" in s:
            score += 5
    return score


def extract_field_chunks(doc: dict) -> tuple[list[dict], list[tuple[int, int]]]:
    text = doc.get("text") or ""
    chunks = []
    covered: list[tuple[int, int]] = []
    for field, patterns in FIELD_PATTERNS:
        best: tuple[int, int, str, int] | None = None
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
                snippet = _window(text, match.start(), match.end())
                score = _field_score(field, snippet)
                if score <= 0:
                    continue
                if best is None or score > best[3]:
                    best = (match.start(), match.end(), snippet, score)
        if not best:
            continue
        start, end, snippet, _score = best
        if len(snippet) < 20:
            continue
        covered.append((max(0, start - 80), min(len(text), end + 80)))
        chunks.append(_make_chunk(doc, field, snippet))
    return chunks, covered


def _is_noise(text: str) -> bool:
    lower = text.lower()
    if any(marker in lower for marker in RETURNS_NOISE) and "expense ratio" not in lower:
        return True
    hits = sum(1 for marker in NOISE_MARKERS if marker in lower)
    if hits >= 2:
        return True
    if lower.count("nifty") >= 8:
        return True
    return False


def split_sections(text: str, max_chars: int, overlap: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    sections: list[str] = []
    buf = ""
    for para in paragraphs:
        pieces = [para] if len(para) <= max_chars else [
            para[i : i + max_chars] for i in range(0, len(para), max_chars - overlap)
        ]
        for piece in pieces:
            if not buf:
                buf = piece
            elif len(buf) + 1 + len(piece) <= max_chars:
                buf = f"{buf}\n{piece}"
            else:
                sections.append(buf)
                tail = buf[-overlap:] if overlap and len(buf) > overlap else ""
                buf = f"{tail}{piece}".strip() if tail else piece
    if buf:
        sections.append(buf)
    return sections


def _make_chunk(doc: dict, field: str, text: str) -> dict:
    text = text.strip()
    return {
        "id": f"{doc['id']}:{field}:{_sha(text)}",
        "text": text,
        "url": doc.get("url"),
        "scheme_name": doc.get("scheme_name") or doc.get("name") or "",
        "source_id": doc.get("id"),
        "title": doc.get("title") or "",
        "field": field,
        "fetched_at": doc.get("fetched_at"),
        "char_count": len(text),
    }


def chunk_document(doc: dict, max_chars: int, overlap: int) -> list[dict]:
    text = (doc.get("text") or "").strip()
    if not text:
        return []

    field_chunks, covered = extract_field_chunks(doc)
    used_texts = {c["text"] for c in field_chunks}
    sections = []
    # Walk the original text and skip spans already captured as fields.
    remainder_parts: list[str] = []
    last = 0
    for start, end in sorted(covered):
        remainder_parts.append(text[last:start])
        last = max(last, end)
    remainder_parts.append(text[last:])
    remainder = "\n".join(p.strip() for p in remainder_parts if p.strip())

    for i, section in enumerate(split_sections(remainder, max_chars, overlap)):
        if len(section) < 80 or _is_noise(section) or section in used_texts:
            continue
        sections.append(_make_chunk(doc, f"section_{i}", section))

    return field_chunks + sections


def chunk_documents() -> list[dict]:
    create_directories()
    cfg = load_config()
    cleaned_dir = project_path(cfg["paths"]["cleaned"])
    chunks_dir = project_path(cfg["paths"]["chunks"])
    max_chars = int(cfg["chunking"]["section_max_chars"])
    overlap = int(cfg["chunking"]["overlap"])

    listed_ids = {s["id"] for s in cfg["sources"]}
    files = sorted(p for p in cleaned_dir.glob("*.json") if p.stem in listed_ids)
    if not files:
        raise FileNotFoundError(f"No cleaned documents in {cleaned_dir}. Run: python -m src.ingest.load")

    all_chunks: list[dict] = []
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("id") not in listed_ids:
            continue
        doc_chunks = chunk_document(doc, max_chars, overlap)
        all_chunks.extend(doc_chunks)
        print(f"chunked {doc.get('id')}: {len(doc_chunks)} chunks")

    out = chunks_dir / "chunks.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    print(f"wrote {len(all_chunks)} chunks -> {out}")
    return all_chunks


def main() -> None:
    print("Phase 4 — chunking cleaned documents")
    chunk_documents()


if __name__ == "__main__":
    main()
