from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_config, project_path
from src.query.guardrails import screen_query

FOREIGN_AMC_RE = re.compile(
    r"\b(sbi|axis|icici|nippon|kotak|uti|ppfas|mirae|quant|parag parikh|"
    r"motilal|bandhan|edelweiss|dsp|franklin|invesco|tata|lic)\b",
    re.I,
)

FIELD_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("expense_ratio", ("expense ratio", "expense")),
    ("exit_load", ("exit load", "exit-load")),
    ("min_sip", ("minimum sip", "min sip", "sip")),
    ("min_investment", ("lumpsum", "minimum investment")),
    ("lock_in", ("lock-in", "lock in")),
    ("riskometer", ("riskometer", "risk rating", "very high risk")),
    ("benchmark", ("benchmark",)),
    ("aum", ("aum", "fund size")),
]

SCHEME_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("hdfc-large-cap", ("large cap", "large-cap", "hdfc large cap")),
    ("hdfc-flexi-cap", ("flexi cap", "flexi-cap", "hdfc flexi", "hdfc equity")),
    ("hdfc-elss", ("elss", "tax saver", "tax-saver")),
    ("hdfc-mid-cap", ("mid cap", "mid-cap", "hdfc mid")),
    ("hdfc-amc", ("hdfc mutual fund", "amc overview", "fund house")),
]

_STOP = {
    "a", "an", "the", "of", "for", "to", "is", "in", "on", "and", "or", "what",
    "how", "which", "does", "do", "please", "me", "tell",
}
_TOKEN_RE = re.compile(r"[a-z0-9%]+")
_CHUNKS: list[dict] | None = None


def resolve_scheme(question: str, listed_ids: set[str]) -> str | None:
    q = question.lower()
    best_id = None
    best_len = 0
    for source_id, aliases in SCHEME_ALIASES:
        if source_id not in listed_ids:
            continue
        for alias in aliases:
            if alias in q and len(alias) > best_len:
                best_id = source_id
                best_len = len(alias)
    return best_id


def resolve_field(question: str) -> str | None:
    q = question.lower()
    best_field = None
    best_len = 0
    for field, aliases in FIELD_ALIASES:
        for alias in aliases:
            if alias in q and len(alias) > best_len:
                best_field = field
                best_len = len(alias)
    return best_field


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP and len(t) > 1}


def _artifact_dir(cfg: dict, key: str) -> Path:
    if os.getenv("VERCEL"):
        path = Path("/tmp") / key
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = project_path(cfg["paths"][key])
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_site_chunks() -> list[dict]:
    global _CHUNKS
    if _CHUNKS is not None:
        return _CHUNKS
    cfg = load_config()
    listed_ids = {s["id"] for s in cfg["sources"]}
    chunks_path = project_path(cfg["paths"]["chunks"]) / "chunks.jsonl"
    if not chunks_path.exists():
        raise FileNotFoundError(f"Missing site artifacts at {chunks_path}")
    chunks = []
    with chunks_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            if chunk.get("source_id") in listed_ids:
                chunks.append(chunk)
    _CHUNKS = chunks
    return chunks


def _score_chunk(question: str, chunk: dict, scheme_id: str | None, field_id: str | None) -> float:
    q_tokens = _tokens(question)
    c_tokens = _tokens(chunk.get("text") or "")
    if not q_tokens:
        return 0.0
    overlap = len(q_tokens & c_tokens) / len(q_tokens)
    score = overlap
    if scheme_id and chunk.get("source_id") == scheme_id:
        score += 0.4
    elif scheme_id and chunk.get("source_id") != scheme_id:
        score -= 0.25
    if field_id and chunk.get("field") == field_id:
        score += 0.55
    if str(chunk.get("field") or "").startswith("section_"):
        score -= 0.08
    return score


def retrieve_from_artifacts(question: str, cfg: dict, listed_ids: set[str], k: int) -> tuple[list[dict], str | None, str | None]:
    chunks = load_site_chunks()
    scheme_id = resolve_scheme(question, listed_ids)
    field_id = resolve_field(question)
    ranked = []
    for chunk in chunks:
        score = _score_chunk(question, chunk, scheme_id, field_id)
        if score <= 0:
            continue
        ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    hits = []
    for score, chunk in ranked[:k]:
        hits.append(
            {
                "id": chunk.get("id"),
                "distance": max(0.0, 1.0 - min(score, 1.0)),
                "similarity": min(score, 1.0),
                "text": chunk.get("text"),
                "url": chunk.get("url"),
                "scheme_name": chunk.get("scheme_name"),
                "field": chunk.get("field"),
                "fetched_at": chunk.get("fetched_at"),
                "source_id": chunk.get("source_id"),
            }
        )
    return hits, scheme_id, field_id


def retrieve_from_chroma(question: str, cfg: dict, listed_ids: set[str]) -> tuple[list[dict], str | None, str | None]:
    import chromadb
    from sentence_transformers import SentenceTransformer

    persist_dir = project_path(cfg["chroma"]["persist_dir"])
    collection = chromadb.PersistentClient(path=str(persist_dir)).get_collection(cfg["chroma"]["collection"])
    scheme_id = resolve_scheme(question, listed_ids)
    field_id = resolve_field(question)
    vector = SentenceTransformer(cfg["embedding_model"]).encode(
        [question],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )[0].astype(float).tolist()

    def _where() -> dict | None:
        clauses = []
        if scheme_id:
            clauses.append({"source_id": scheme_id})
        if field_id:
            clauses.append({"field": field_id})
        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    kwargs = {
        "query_embeddings": [vector],
        "n_results": int(cfg["retrieval"]["k"]),
        "include": ["documents", "metadatas", "distances"],
    }
    where = _where()
    if where:
        kwargs["where"] = where
    raw = collection.query(**kwargs)
    if field_id and (not raw["ids"] or not raw["ids"][0]):
        kwargs.pop("where", None)
        if scheme_id:
            kwargs["where"] = {"source_id": scheme_id}
        raw = collection.query(**kwargs)
    hits = []
    for i, chunk_id in enumerate(raw["ids"][0]):
        distance = float(raw["distances"][0][i])
        meta = raw["metadatas"][0][i] or {}
        hits.append(
            {
                "id": chunk_id,
                "distance": distance,
                "similarity": 1.0 - distance,
                "text": raw["documents"][0][i],
                "url": meta.get("url"),
                "scheme_name": meta.get("scheme_name"),
                "field": meta.get("field"),
                "fetched_at": meta.get("fetched_at"),
                "source_id": meta.get("source_id"),
            }
        )
    return hits, scheme_id, field_id


def chroma_vs_chunks() -> dict:
    chunks = load_site_chunks()
    return {
        "backend": "artifacts",
        "chunks_file": len(chunks),
        "all_present": len(chunks) > 0,
        "missing_in_chroma": [],
        "extra_in_chroma": [],
        "note": "Vercel/runtime uses saved site chunks, not Chroma or live web.",
    }


def retrieve(question: str) -> dict:
    cfg = load_config()
    listed_ids = {s["id"] for s in cfg["sources"]}
    guard = screen_query(question)
    query_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    out_dir = _artifact_dir(cfg, "artifacts_retrieval")
    backend = (cfg.get("retrieval") or {}).get("backend", "artifacts")

    artifact = {
        "query_id": query_id,
        "query": question if guard["persist_query"] else "[redacted]",
        "intent": guard["intent"],
        "refused": guard["action"] == "refuse",
        "reason": guard["reason"],
        "message": guard["message"],
        "source_url": guard["source_url"],
        "scheme_filter": None,
        "field_filter": None,
        "backend": backend,
        "k": cfg["retrieval"]["k"],
        "min_relevance": cfg["retrieval"]["min_relevance"],
        "in_corpus": False,
        "hits": [],
    }

    if guard["action"] != "retrieve":
        _write_artifact(out_dir, artifact)
        return artifact

    q_lower = question.lower()
    if FOREIGN_AMC_RE.search(question) and "hdfc" not in q_lower:
        artifact["in_corpus"] = False
        artifact["message"] = "This fact is not in the listed Groww HDFC corpus."
        artifact["reason"] = "unknown_scheme"
        _write_artifact(out_dir, artifact)
        return artifact

    k = int(cfg["retrieval"]["k"])
    if backend == "chroma" and not os.getenv("VERCEL"):
        hits, scheme_id, field_id = retrieve_from_chroma(question, cfg, listed_ids)
    else:
        hits, scheme_id, field_id = retrieve_from_artifacts(question, cfg, listed_ids, k)

    artifact["scheme_filter"] = scheme_id
    artifact["field_filter"] = field_id
    min_rel = float(cfg["retrieval"]["min_relevance"])
    best = hits[0]["similarity"] if hits else 0.0
    in_corpus = bool(hits) and best >= min_rel
    artifact["hits"] = hits
    artifact["in_corpus"] = in_corpus
    artifact["best_similarity"] = best
    if not in_corpus:
        artifact["message"] = "This fact is not in the listed Groww HDFC corpus."
        artifact["source_url"] = None
    else:
        artifact["source_url"] = hits[0]["url"]
        if guard["intent"] == "returns":
            artifact["message"] = (
                "I do not calculate or compare returns. See the official page linked from the retrieved source."
            )

    _write_artifact(out_dir, artifact)
    return artifact


def _write_artifact(out_dir: Path, artifact: dict) -> None:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{artifact['query_id']}.json"
        path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 7 — retrieve from saved site artifacts")
    parser.add_argument("question", nargs="*", help="User question")
    parser.add_argument("--check-index", action="store_true", help="Verify saved chunks exist")
    args = parser.parse_args()

    if args.check_index or not args.question:
        report = chroma_vs_chunks()
        print(json.dumps(report, indent=2))
        if not args.question:
            return

    if args.question:
        question = " ".join(args.question)
        result = retrieve(question)
        print(json.dumps({k: result[k] for k in result if k != "hits"}, indent=2, ensure_ascii=False))
        print(f"hits={len(result['hits'])} in_corpus={result['in_corpus']}")


if __name__ == "__main__":
    main()
