from __future__ import annotations

import json

import numpy as np
from sentence_transformers import SentenceTransformer

from src.config import load_config, project_path
from src.ingest.create_dirs import create_directories


def _read_chunks(chunks_path) -> list[dict]:
    if not chunks_path.exists():
        raise FileNotFoundError(f"No chunks at {chunks_path}. Run: python -m src.ingest.chunk")
    chunks = []
    with chunks_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    if not chunks:
        raise ValueError(f"{chunks_path} is empty. Run: python -m src.ingest.chunk")
    return chunks


def embed_chunks() -> dict:
    create_directories()
    cfg = load_config()
    listed_ids = {s["id"] for s in cfg["sources"]}
    chunks_path = project_path(cfg["paths"]["chunks"]) / "chunks.jsonl"
    out_dir = project_path(cfg["paths"]["embeddings"])
    model_name = cfg["embedding_model"]

    chunks = [c for c in _read_chunks(chunks_path) if c.get("source_id") in listed_ids]
    if not chunks:
        raise ValueError("No chunks from listed sources. Run: python -m src.ingest.chunk")

    print(f"loading embedding model {model_name}")
    model = SentenceTransformer(model_name)
    texts = [c["text"] for c in chunks]
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    vectors = np.asarray(vectors, dtype=np.float32)

    np.save(out_dir / "vectors.npy", vectors)
    ids = [
        {
            "id": c["id"],
            "source_id": c.get("source_id"),
            "field": c.get("field"),
            "url": c.get("url"),
            "scheme_name": c.get("scheme_name"),
            "fetched_at": c.get("fetched_at"),
        }
        for c in chunks
    ]
    (out_dir / "ids.json").write_text(json.dumps(ids, indent=2, ensure_ascii=False), encoding="utf-8")

    meta = {
        "model": model_name,
        "count": int(vectors.shape[0]),
        "dim": int(vectors.shape[1]),
        "normalized": True,
        "dtype": "float32",
        "vectors_file": "vectors.npy",
        "ids_file": "ids.json",
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"embedded {meta['count']} chunks dim={meta['dim']} -> {out_dir}")
    return meta


def main() -> None:
    print("Phase 5 — embedding chunks")
    embed_chunks()


if __name__ == "__main__":
    main()
