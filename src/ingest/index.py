from __future__ import annotations

import json

import chromadb
import numpy as np

from src.config import load_config, project_path
from src.ingest.create_dirs import create_directories


def _meta_value(value) -> str:
    if value is None:
        return ""
    return str(value)


def _read_chunks(path) -> dict[str, dict]:
    if not path.exists():
        raise FileNotFoundError(f"No chunks at {path}. Run: python -m src.ingest.chunk")
    by_id = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            by_id[chunk["id"]] = chunk
    return by_id


def index_chunks() -> dict:
    create_directories()
    cfg = load_config()
    listed_ids = {s["id"] for s in cfg["sources"]}
    chunks_path = project_path(cfg["paths"]["chunks"]) / "chunks.jsonl"
    emb_dir = project_path(cfg["paths"]["embeddings"])
    persist_dir = project_path(cfg["chroma"]["persist_dir"])
    collection_name = cfg["chroma"]["collection"]

    vectors_path = emb_dir / "vectors.npy"
    ids_path = emb_dir / "ids.json"
    if not vectors_path.exists() or not ids_path.exists():
        raise FileNotFoundError(f"Missing embeddings in {emb_dir}. Run: python -m src.ingest.embed")

    chunks_by_id = _read_chunks(chunks_path)
    id_rows = json.loads(ids_path.read_text(encoding="utf-8"))
    vectors = np.load(vectors_path)
    if len(id_rows) != len(vectors):
        raise ValueError(f"ids.json ({len(id_rows)}) and vectors.npy ({len(vectors)}) length mismatch")

    ids, embeddings, documents, metadatas = [], [], [], []
    for row, vector in zip(id_rows, vectors):
        chunk = chunks_by_id.get(row["id"])
        if not chunk:
            continue
        if chunk.get("source_id") not in listed_ids:
            continue
        ids.append(chunk["id"])
        embeddings.append(vector.astype(float).tolist())
        documents.append(chunk["text"])
        metadatas.append(
            {
                "url": _meta_value(chunk.get("url")),
                "scheme_name": _meta_value(chunk.get("scheme_name")),
                "field": _meta_value(chunk.get("field")),
                "fetched_at": _meta_value(chunk.get("fetched_at")),
                "source_id": _meta_value(chunk.get("source_id")),
            }
        )

    if not ids:
        raise ValueError("No listed chunks to upsert. Run phases 4 and 5 first.")

    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    existing = {c.name for c in client.list_collections()}
    if collection_name in existing:
        client.delete_collection(collection_name)
    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine", "embedding_model": cfg["embedding_model"]},
    )
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )

    summary = {
        "persist_dir": str(persist_dir),
        "collection": collection_name,
        "count": collection.count(),
        "embedding_model": cfg["embedding_model"],
    }
    (persist_dir / "index_meta.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"upserted {summary['count']} chunks into Chroma collection '{collection_name}' at {persist_dir}")
    return summary


def main() -> None:
    print("Phase 6 — storing chunks in ChromaDB")
    index_chunks()


if __name__ == "__main__":
    main()
