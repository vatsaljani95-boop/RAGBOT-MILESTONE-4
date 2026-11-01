# Product Requirements Document

**Product:** HDFC Mutual Fund FAQ Assistant (Groww public pages)  
**Type:** Facts-only RAG prototype  
**Status:** Draft  
**Source:** `problemstatement.txt`

---

## 1. Problem

Retail users and support/content teams repeatedly ask the same factual questions about mutual fund schemes (expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, how to download statements). Answers must come from official public pages, with a citation, and must never become investment advice.

## 2. Goal

Build a small FAQ assistant that:

- Answers **factual** questions about a defined HDFC Mutual Fund corpus scraped from **Groww public pages**.
- Returns **one source URL** with every answer.
- **Refuses** advice, portfolio, and buy/sell questions.
- Makes the **RAG pipeline inspectable**: each stage’s data is stored and can be shown in a demo.

## 3. Users

| User | Need |
| --- | --- |
| Retail investor comparing schemes | Fast facts with a link to the page they came from |
| Support / content team | Repeatable answers to common MF FAQs without giving advice |

## 4. In-scope corpus

Public Groww pages only (scrape and store):

| # | Page | URL |
| --- | --- | --- |
| 1 | AMC overview — HDFC Mutual Fund | https://groww.in/mutual-funds/amc/hdfc-mutual-funds |
| 2 | Large Cap — HDFC Large Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| 3 | Flexi Cap — HDFC Flexi Cap Direct Plan Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 4 | ELSS (tax saver) — HDFC ELSS Tax Saver Fund Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 5 | Mid Cap — HDFC Mid Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |

Additional official public URLs (Groww / AMC / SEBI / AMFI / factsheets) may be added until the source list has **15–25 URLs**. No app-backend screenshots. No third-party blogs.

## 5. Product behavior

### 5.1 Must answer (facts only)

Examples:

- Expense ratio of a listed scheme
- ELSS lock-in
- Minimum SIP
- Exit load
- Riskometer / benchmark
- How to download a capital-gains statement (process only, no account data)

### 5.2 Must refuse

Opinion, suitability, timing, and portfolio questions (e.g. “Should I buy/sell?”). Response: polite facts-only refusal plus one relevant **educational** official link.

### 5.3 Answer format

- At most **3 sentences**
- Exactly **one citation URL**
- Line: `Last updated from sources: <date or timestamp>`
- No computed or compared returns; if asked for performance, **link to the official factsheet** instead of calculating

### 5.4 UI (tiny)

- Welcome line
- Three example questions
- Persistent note: **Facts-only. No investment advice.**
- Single question input and answer area
- Disclaimer snippet in the UI
- Optional demo view of RAG stage artifacts (raw → chunks → embeddings metadata → retrieved docs → LLM answer)

### 5.5 Safety

- **No PII:** do not accept or store PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers. If the user pastes them, refuse and do not persist.
- Public sources only.
- No investment advice. No performance claims.

## 6. RAG requirements (demo-first)

This is a **RAG demo**. Implement **phase-wise** and **persist each stage** so it can be shown.

| Phase | Requirement |
| --- | --- |
| 1. Create directories | Stage folders for raw, cleaned, chunks, embeddings, chroma, artifacts |
| 2. Scrape | Fetch allowlisted public pages; store raw HTML + URL + timestamp |
| 3. Load documents | Read raw HTML from disk; extract text into cleaned JSON **before** chunking |
| 4. Chunk | Field-aware + section chunks with source URL metadata |
| 5. Embed | `sentence-transformers/all-MiniLM-L6-v2` |
| 6. Vector DB | ChromaDB |
| 7. Retrieval | Same embedding model and same Chroma collection as ingestion |
| 8. UI + generation | Tiny facts-only UI; LLM via API; **model name from `.env`** |
| 9. Guardrails | PII / advice / returns tests and runtime checks |

**Config (not secrets):** embedding model name, Chroma path/collection, chunk parameters, retrieval `k`, default LLM provider — all in a **config file** so they can be changed without code edits.

**Secrets:** Groq (and optional other) API keys and the **LLM model id** live in `.env`.

**LLM:** Primary path is **Groq**. Model id is read from `.env` (problem statement draft: `qwen/qwen3.8-27b`; treat as configurable — use the Groq model id that exists in the account). Optional later providers: Gemini, OpenAI, Anthropic, Mistral.

## 7. Non-goals

- Personalized portfolio or KYC flows
- Live trading, order placement, or Groww authenticated APIs
- Return calculation, ranking, or “best fund” recommendations
- Multi-AMC coverage beyond the listed HDFC / Groww corpus (unless URLs are added to the source list)
- Fine-tuning a model

## 8. Deliverables

1. Working prototype (hosted app/notebook) **or** a ≤3-minute demo video
2. Source list (CSV or MD) of 15–25 URLs used
3. README: setup, scope (AMC + schemes), known limits
4. Sample Q&A file: 5–10 queries with assistant answers + links
5. Disclaimer snippet used in the UI
6. Inspectable RAG artifacts (per-stage stored data)
7. `config` + `.env` split as specified

## 9. Success criteria

- Factual questions on the five pages return a correct fact, one valid source URL, and a last-updated line.
- Advice questions are refused with an educational link.
- PII is not stored.
- Returns questions do not produce computed performance numbers.
- Demo can show raw docs, chunks, embeddings/index, retrieved context, and final answer separately.
- Changing embedding model / Chroma settings / `k` is possible via config; changing LLM model is possible via `.env`.

## 10. Skills this exercise tests

- **W1** Identify the exact fact; answer vs refuse
- **W2** Instruction-style prompting, concise phrasing, polite refusals, citation wording
- **W3** Small-corpus RAG with accurate citations from official pages
