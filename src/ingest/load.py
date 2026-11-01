from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from src.config import load_config, project_path
from src.ingest.create_dirs import create_directories

DROP_TAGS = ("script", "style", "noscript", "svg", "iframe", "nav", "footer", "header", "form")


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(DROP_TAGS):
        tag.decompose()

    parts: list[str] = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                parts.append(" | ".join(cells))
        table.decompose()

    for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = node.get_text(" ", strip=True)
        if text:
            parts.append(text)

    leftover = soup.get_text(" ", strip=True)
    if leftover:
        parts.append(leftover)

    text = "\n".join(parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_documents() -> list[dict]:
    create_directories()
    cfg = load_config()
    raw_dir = project_path(cfg["paths"]["raw"])
    cleaned_dir = project_path(cfg["paths"]["cleaned"])
    listed_ids = {s["id"] for s in cfg["sources"]}
    name_by_id = {s["id"]: s.get("name", "") for s in cfg["sources"]}
    loaded = []

    meta_files = sorted(raw_dir.glob("*.meta.json"))
    if not meta_files:
        raise FileNotFoundError(f"No scraped files in {raw_dir}. Run: python -m src.ingest.scrape")

    for extra in cleaned_dir.glob("*.json"):
        if extra.stem not in listed_ids:
            extra.unlink()
            print(f"removed extra cleaned file {extra.name}")

    for meta_path in meta_files:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        source_id = meta["id"]
        if source_id not in listed_ids:
            print(f"skipped unlisted {source_id}")
            continue
        html_path = raw_dir / f"{source_id}.html"
        html = html_path.read_text(encoding="utf-8", errors="replace") if html_path.exists() else ""

        load_error = meta.get("error")
        text = ""
        if meta.get("http_status") == 200 and html.strip():
            try:
                text = _visible_text(html)
            except Exception as exc:
                load_error = f"parse failed: {exc}"
        elif not load_error:
            load_error = "empty or missing html"

        doc = {
            "id": source_id,
            "name": name_by_id.get(source_id, meta.get("name", "")),
            "scheme_name": name_by_id.get(source_id, meta.get("name", "")),
            "url": meta.get("url"),
            "title": meta.get("title") or "",
            "fetched_at": meta.get("fetched_at"),
            "http_status": meta.get("http_status"),
            "text": text,
            "char_count": len(text),
            "load_error": load_error,
        }
        out = cleaned_dir / f"{source_id}.json"
        out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        loaded.append(doc)
        print(f"loaded {source_id}: chars={doc['char_count']} error={load_error}")

    return loaded


def main() -> None:
    print("Phase 3 — loading documents from data/raw")
    load_documents()


if __name__ == "__main__":
    main()
