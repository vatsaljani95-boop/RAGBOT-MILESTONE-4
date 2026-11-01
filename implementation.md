# Implementation

Phase-wise build for the FAQ assistant. Each phase has a **folder or file you can open** in a demo.

Run from the project root after `pip install -r requirements.txt`.

| Phase | What | Output |
| --- | --- | --- |
| 1 | Creating the directory | Empty folders from `config.yaml` |
| 2 | Scraping documents | `data/raw/{id}.html` + `data/raw/{id}.meta.json` |
| 3 | Loading the document | `data/cleaned/{id}.json` |
| 4 | Chunking | `data/chunks/chunks.jsonl` |
| 5 | Embedding | `data/embeddings/` |
| 6 | Storing in vector DB | `chroma/` |
| 7 | Retrieval | `artifacts/retrieval/` |
| 8 | UI | local app |
| 9 | Guardrail edge cases + tests | `tests/test_guardrails.py` |

**Phase 3 is required before chunking.** Chunking reads cleaned documents, not live URLs and not raw HTML.

```text
python -m src.ingest.create_dirs
python -m src.ingest.scrape
python -m src.ingest.load
python -m src.ingest.chunk
python -m src.ingest.embed
python -m src.ingest.index
python -m src.query.retrieve --check-index
python -m src.query.retrieve "Expense ratio of HDFC Large Cap Direct Growth"
python -m uvicorn src.app:app --host 127.0.0.1 --port 8000
```

---

## 1. Creating the directory

**Goal:** Make a stable place for every RAG stage.

**Create:**

- `data/raw`, `data/cleaned`, `data/chunks`, `data/embeddings`
- `chroma`
- `artifacts/retrieval`, `artifacts/answers`
- `src/ingest`, `src/query`

**Also add:** `config.yaml`, `sources.md`, `.env.example`, `.gitignore`.

**How:** `python -m src.ingest.create_dirs`  
Idempotent: existing folders are left as-is.

---

## 2. Scraping documents

**Goal:** Download **only the five shared Groww URLs** and keep the original HTML.

**Input:** Exact URL list in `config.yaml` / `sources.md` (problem statement links).

**Rules:**

- GET each listed URL once. Do **not** crawl `<a href>`, SID/PDF, factsheets, or other internal Groww pages.
- If a listed URL redirects to a **different** page, do not save that other document.
- Delete any `data/raw/` files whose id is not in the shared list.

**For each listed URL:**

1. GET with a browser-like User-Agent, timeout, 1–2s pause between URLs.
2. Write `data/raw/{id}.html`.
3. Write `data/raw/{id}.meta.json`: `id`, `url`, `final_url`, `http_status`, `fetched_at`, `title`, `error`.

Public GET only. No cookies, logins, or account pages.

**How:** `python -m src.ingest.scrape`

---

## 3. Loading the document

**Goal:** Turn saved HTML into plain text the rest of the pipeline can use.

**Input:** `data/raw/*.meta.json` + matching `.html`.  
**Output:** `data/cleaned/{id}.json`

**Steps:**

1. Read HTML from disk (no network).
2. Drop `script`, `style`, `nav`, `footer`, `noscript`.
3. Keep headings, paragraphs, list items, and table rows as text.
4. Collapse whitespace.
5. Save `{ id, url, title, scheme_name, text, fetched_at, char_count }`.

If a scrape failed (`http_status` not 200 or empty HTML), write a cleaned file with `text: ""` and `load_error`, and continue.

**How:** `python -m src.ingest.load`

---

## 4. Chunking

**Input:** `data/cleaned/*.json` (no network, no raw HTML).  
**Output:** `data/chunks/chunks.jsonl`

**Strategy:** field-aware + section split.

1. One short chunk per fact field when the label appears: expense ratio, exit load, min SIP, min investment, lock-in, riskometer, benchmark, AUM.
2. Remaining prose split to `section_max_chars` (config, default 1000) with `overlap` (default 100).
3. Drop empty docs, tiny leftovers, Groww footer/nav, and return-calculator tables.
4. Every chunk keeps `id`, `text`, `url`, `scheme_name`, `field`, `fetched_at`.

**How:** `python -m src.ingest.chunk`

---

## 5. Embedding

**Input:** `data/chunks/chunks.jsonl`  
**Output:** `data/embeddings/vectors.npy`, `ids.json`, `meta.json`

Embed each listed chunk’s `text` with the model in `config.yaml` (`sentence-transformers/all-MiniLM-L6-v2`). Use the same model later at query time. Vectors are L2-normalized float32.

**How:** `python -m src.ingest.embed`

---

## 6. Storing data in vector DB

**Input:** `data/chunks/chunks.jsonl` + `data/embeddings/vectors.npy` + `ids.json`  
**Output:** persistent Chroma dir from config (`chroma/`, collection `hdfc_mf_faq`)

Upsert each listed chunk with its MiniLM vector. Metadata: `url`, `scheme_name`, `field`, `fetched_at`, `source_id`. Rebuild is idempotent (drop collection, then upsert). Use cosine space to match normalized embeddings. Same collection name is used later for retrieval.

**How:** `python -m src.ingest.index`

---

## 7. Retrieval logic

**Input:** user question + Chroma collection `hdfc_mf_faq`  
**Output:** `artifacts/retrieval/{query_id}.json`

1. Run guardrails. PII / empty / advice → stop, no Chroma query. Do not store raw PII.
2. Embed the question with the **same** MiniLM model from config.
3. Query Chroma `k` from config. If the question names a listed scheme, filter `source_id`.
4. Similarity is `1 - cosine_distance`. If best score is below `min_relevance`, return “not in this corpus”.
5. Write the query (or `[redacted]`), hits, scores, and source URL to `artifacts/retrieval/`.

**How:**
```text
python -m src.query.retrieve --check-index
python -m src.query.retrieve "Expense ratio of HDFC Large Cap Direct Growth"
```

---

## 8. UI

Tiny local page at `http://127.0.0.1:8000`.

- Welcome line, three example questions, persistent note **Facts-only. No investment advice.**
- One text box; answer area with at most 3 sentences, one source URL, `Last updated from sources:`
- Disclaimer snippet on the page
- Optional **Show RAG stages** panel listing files under `data/`, `chroma/`, and `artifacts/`
- Guardrails run before retrieval. Groq is used when `GROQ_API_KEY` and `LLM_MODEL` are set in `.env`; otherwise the answer is taken from retrieved chunk text.

**How:** `python -m uvicorn src.app:app --host 127.0.0.1 --port 8000`

---

## 9. Edge cases and guardrail test cases

**Not implemented in this step.** Enforce **before** retrieval. Do not save the raw user text when PII matches.

| Case | Input example | Expected |
| --- | --- | --- |
| PAN | `ABCDE1234F expense ratio` | Refuse PII; no retrieval; nothing stored |
| Aadhaar | `1234 5678 9012 lock-in` | Same |
| Phone / email / OTP | `send OTP to 9876543210` | Same |
| Account number | `folio 123456789012` | Same |
| Advice | `Should I buy HDFC Large Cap?` | Polite refusal + educational official link |
| Sell / timing | `Is this a good time to sell?` | Same |
| Returns math | `What is 3 year return vs Nifty?` | No calculation; factsheet link if in corpus |
| Empty / whitespace | `   ` | Ask for a question; no retrieval |
| Unknown scheme | `expense ratio of SBI Small Cap` | Not in corpus (after retrieval miss) |
| Fact (happy path) | `Expense ratio of HDFC Large Cap Direct Growth` | Retrieve + answer + one Groww URL |
| Statement how-to | `How to download capital gains statement?` | Process only; no account data |

Tests live in `tests/test_guardrails.py` and cover: PII regex, advice keywords, returns keywords, empty input, and “do not persist PII”.
