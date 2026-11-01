# Architecture

**Product:** HDFC Mutual Fund FAQ Assistant  
**Source of truth:** `PRD.md`  
**Style:** Phase-wise RAG with **each stage saved on disk** so a demo can show scrape → load → chunk → embed → index → retrieve → answer.

---

## Design goals

1. Facts only, one citation URL per answer. No investment advice.
2. Inspectable RAG: do not keep a stage only in memory.
3. Tunables in `config.yaml`. Secrets and LLM model id in `.env`.
4. Same embedding model for ingest and query: `sentence-transformers/all-MiniLM-L6-v2`.
5. Vector store: ChromaDB.

---

## Pipeline (ingest vs query)

```text
INGEST (run when sources change)
  1. Create directories
  2. Scrape public URLs  → data/raw/
  3. Load documents      → data/cleaned/     ← required before chunking
  4. Chunk               → data/chunks/
  5. Embed               → data/embeddings/
  6. Store in Chroma     → chroma/

QUERY (every user question)
  Guardrails → retrieve → LLM → tiny UI
```

**Load is a separate phase.** Scraping only writes raw HTML. Loading reads those files, extracts text, and writes cleaned documents. Chunking never fetches the network.

---

## Repository layout

```text
Buildingchatbot/
  config.yaml
  sources.md
  .env
  data/raw/              # scraped HTML + meta.json
  data/cleaned/          # loaded documents (text + fields)
  data/chunks/
  data/embeddings/
  chroma/
  artifacts/retrieval/
  artifacts/answers/
  src/ingest/
  src/query/
  src/app.py
```

---

## Ingest phases

### 1. Creating the directory

Create the folders above from `config.yaml` so later phases have a place to write.

### 2. Scraping documents

- Fetch only allowlisted URLs in `sources.md` / `config.yaml`.
- Save `data/raw/{id}.html` and `data/raw/{id}.meta.json` (`url`, `fetched_at`, `http_status`, `title`).
- Public pages only. Rate-limit requests.

### 3. Loading the document

- Read **from disk** (`data/raw/`), do not scrape again.
- Strip scripts/styles; extract visible text and tables.
- Save `data/cleaned/{id}.json`: `id`, `url`, `title`, `text`, `fetched_at`.
- Chunking input is this cleaned JSON, not raw HTML.

### 4. Chunking

Field-aware chunks (expense ratio, exit load, SIP, lock-in, riskometer, benchmark) plus section chunks for remaining prose. Write `data/chunks/chunks.jsonl`.

### 5. Embedding

Embed chunk **text** with MiniLM. Optional dump under `data/embeddings/` for the demo.

### 6. Storing in vector DB

Upsert into persistent Chroma: id, document, embedding, metadata (`url`, `scheme_name`, `field`, `fetched_at`).

---

## Query path

### 7. Retrieval

Same MiniLM + same Chroma collection. `k` from config. Dump `artifacts/retrieval/`. Weak scores → “not in corpus”, do not invent facts.

### 8. UI + generation

Tiny UI: welcome, 3 example questions, **Facts-only. No investment advice.** Groq LLM; model id from `.env`. Answer ≤3 sentences, one source URL, `Last updated from sources:`.

### 9. Guardrails

Before retrieval: PII (PAN, Aadhaar, account, OTP, email, phone) → refuse, do not store. Advice / buy-sell → canned refusal + educational link. Returns → no math; link factsheet if present.

---

## Config vs secrets

`config.yaml`: embedding model, Chroma path, chunk sizes, `k`, source list, directory paths.  
`.env`: `GROQ_API_KEY`, `LLM_MODEL` (and optional other providers).
