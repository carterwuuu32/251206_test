from __future__ import annotations

import html
import json
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import List
from urllib.parse import quote
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


CACHE_PATH = Path("data/news_cache.json")
STYLE_PATH = Path("static/style.css")
REFRESH_INTERVAL_SECONDS = 60 * 60 * 24  # 24 hours
MAX_ITEMS = 25
HOST = "0.0.0.0"
PORT = 5000

RSS_QUERIES = [
    "人工智慧 最新消息",
    "生成式 AI 最新消息",
    "OpenAI 最新消息",
]


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: str


class NewsService:
    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._items: List[NewsItem] = []
        self._last_updated: str | None = None
        self._load_cache()

    @property
    def items(self) -> List[NewsItem]:
        with self._lock:
            return list(self._items)

    @property
    def last_updated(self) -> str | None:
        with self._lock:
            return self._last_updated

    def refresh(self) -> None:
        items = self._fetch_news()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            self._items = items
            self._last_updated = timestamp
            self._save_cache()

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return

        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self._last_updated = data.get("last_updated")
            self._items = [NewsItem(**item) for item in data.get("items", [])]
        except (json.JSONDecodeError, OSError, TypeError):
            self._items = []
            self._last_updated = None

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_updated": self._last_updated,
            "items": [asdict(item) for item in self._items],
        }
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _fetch_news(self) -> List[NewsItem]:
        entries: List[NewsItem] = []
        seen_links = set()

        for query in RSS_QUERIES:
            rss_url = (
                "https://news.google.com/rss/search?"
                f"q={quote(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
            )
            request = Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})

            try:
                with urlopen(request, timeout=15) as response:
                    content = response.read()
                root = ET.fromstring(content)
            except Exception:
                continue

            for item_node in root.findall("./channel/item"):
                title = (item_node.findtext("title") or "").strip()
                link = (item_node.findtext("link") or "").strip()
                pub_date = (item_node.findtext("pubDate") or "").strip()
                source = (item_node.findtext("source") or "Google News").strip()

                if not title or not link or link in seen_links:
                    continue

                seen_links.add(link)
                entries.append(
                    NewsItem(
                        title=title,
                        link=link,
                        source=source,
                        published=pub_date,
                    )
                )

        return entries[:MAX_ITEMS]


def start_daily_refresh(service: NewsService) -> None:
    def worker() -> None:
        while True:
            try:
                service.refresh()
            except Exception:
                pass
            time.sleep(REFRESH_INTERVAL_SECONDS)

    threading.Thread(target=worker, daemon=True).start()


def render_page(service: NewsService) -> str:
    items_markup = ""
    for item in service.items:
        items_markup += (
            "<li class='news-item'>"
            f"<a href='{html.escape(item.link)}' target='_blank' rel='noopener noreferrer'>{html.escape(item.title)}</a>"
            "<div class='meta'>"
            f"<span>{html.escape(item.source)}</span>"
            f"<span>{html.escape(item.published)}</span>"
            "</div></li>"
        )

    if not items_markup:
        items_markup = "<p>目前沒有可顯示的新聞，請稍後再試。</p>"
    else:
        items_markup = f"<ul class='news-list'>{items_markup}</ul>"

    updated = html.escape(service.last_updated or "尚未更新")
    return f"""<!doctype html>
<html lang='zh-Hant'>
<head>
  <meta charset='UTF-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1.0' />
  <title>每日 AI 新聞</title>
  <link rel='stylesheet' href='/static/style.css' />
</head>
<body>
  <main class='container'>
    <header>
      <h1>每日 AI 新聞（中文）</h1>
      <p>自動彙整最新的人工智慧相關新聞。</p>
      <p class='updated-time'>最後更新：{updated}</p>
    </header>
    {items_markup}
  </main>
</body>
</html>"""


class NewsHandler(BaseHTTPRequestHandler):
    service: NewsService

    def do_GET(self) -> None:
        if self.path == "/":
            page = render_page(self.service).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        if self.path == "/static/style.css" and STYLE_PATH.exists():
            content = STYLE_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    service = NewsService(CACHE_PATH)
    if not service.items:
        service.refresh()
    start_daily_refresh(service)

    handler = NewsHandler
    handler.service = service

    server = HTTPServer((HOST, PORT), handler)
    print(f"Server running at http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
