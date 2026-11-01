from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

from src.config import load_config, project_path
from src.ingest.create_dirs import create_directories


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def _extract_title(html: str) -> str:
    parser = _TitleParser()
    try:
        parser.feed(html)
    except Exception:
        return ""
    return re.sub(r"\s+", " ", parser.title).strip()


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    return f"{host}{path}"


def _same_page(requested: str, final: str) -> bool:
    return _normalize_url(requested) == _normalize_url(final)


def _listed_urls(cfg: dict) -> set[str]:
    return {_normalize_url(source["url"]) for source in cfg["sources"]}


def _remove_unlisted_raw_files(raw_dir, keep_ids: set[str]) -> None:
    for path in raw_dir.iterdir():
        name = path.name
        if name.endswith(".meta.json"):
            source_id = name[: -len(".meta.json")]
        elif name.endswith(".html"):
            source_id = name[: -len(".html")]
        else:
            continue
        if source_id not in keep_ids:
            path.unlink()
            print(f"removed extra file {path.name}")


def scrape_sources() -> list[dict]:
    """GET only the URLs listed in config. Do not crawl hrefs, PDFs, or other pages."""
    create_directories()
    cfg = load_config()
    raw_dir = project_path(cfg["paths"]["raw"])
    scrape_cfg = cfg["scrape"]
    listed = _listed_urls(cfg)
    keep_ids = {source["id"] for source in cfg["sources"]}
    results = []

    headers = {
        "User-Agent": scrape_cfg["user_agent"],
        "Accept": "text/html,application/xhtml+xml",
    }
    session = requests.Session()
    session.headers.update(headers)
    session.max_redirects = 3

    for i, source in enumerate(cfg["sources"]):
        source_id = source["id"]
        url = source["url"]
        meta = {
            "id": source_id,
            "name": source.get("name", ""),
            "url": url,
            "final_url": None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "http_status": None,
            "title": "",
            "error": None,
            "crawled_links": False,
        }
        html = ""

        if _normalize_url(url) not in listed:
            meta["error"] = "url is not in the shared source list"
        else:
            try:
                response = session.get(
                    url,
                    timeout=scrape_cfg["timeout_seconds"],
                    allow_redirects=True,
                )
                meta["http_status"] = response.status_code
                meta["final_url"] = response.url
                if not _same_page(url, response.url):
                    meta["error"] = f"redirected away from listed page to {response.url}"
                else:
                    html = response.text or ""
                    meta["title"] = _extract_title(html)
                    if response.status_code >= 400:
                        meta["error"] = f"http {response.status_code}"
            except requests.RequestException as exc:
                meta["error"] = str(exc)

        html_path = raw_dir / f"{source_id}.html"
        meta_path = raw_dir / f"{source_id}.meta.json"
        html_path.write_text(html, encoding="utf-8", errors="replace")
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        results.append(meta)
        print(f"scraped {source_id}: status={meta['http_status']} error={meta['error']}")

        if i < len(cfg["sources"]) - 1:
            time.sleep(float(scrape_cfg["pause_seconds"]))

    _remove_unlisted_raw_files(raw_dir, keep_ids)
    return results


def main() -> None:
    print("Phase 2 — scraping listed pages only (no internal link crawl)")
    scrape_sources()


if __name__ == "__main__":
    main()
