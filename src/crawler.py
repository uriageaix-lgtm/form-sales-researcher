"""Webサイトのクローラー。

控えめにクロールするための制約を守る:
- robots.txt を確認する
- 1サイトあたりのページ数を制限する
- リクエスト間に待ち時間を入れる
- CAPTCHA・ログインが出たら突破せずスキップする
"""
from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .logging_utils import get_logger

# 会社情報・問い合わせにつながりやすい内部リンクのヒントワード
RELEVANT_LINK_HINTS = [
    "会社概要", "企業情報", "会社情報", "about", "company", "概要",
    "問い合わせ", "お問い合わせ", "contact", "inquiry",
    "見積", "お見積", "相談", "資料請求", "quote",
    "施工事例", "事例", "実績", "works", "case", "ギャラリー",
    "採用", "求人", "recruit",
    "代表", "ごあいさつ", "メッセージ", "message",
    "事業", "サービス", "service", "取扱", "商品",
]

# CAPTCHA / ログイン / アクセス制限を示すサイン
BLOCK_SIGNS = ["recaptcha", "g-recaptcha", "captcha", "cloudflare",
               "アクセスが集中", "are you human", "access denied"]


@dataclass
class CrawlResult:
    """1サイトのクロール結果。"""

    base_url: str = ""
    pages: dict | None = None        # {url: html}
    blocked: bool = False            # CAPTCHA等でブロックされた
    robots_disallowed: bool = False  # robots.txt で拒否された
    error: str = ""

    def __post_init__(self):
        if self.pages is None:
            self.pages = {}


class Crawler:
    """1サイトを控えめにクロールする。"""

    def __init__(self, crawl_config: dict):
        self.max_pages = int(crawl_config.get("max_pages_per_site", 8))
        self.timeout = int(crawl_config.get("timeout_seconds", 15))
        self.user_agent = crawl_config.get(
            "user_agent", "FormSalesResearchBot/1.0"
        )
        self.respect_robots = bool(crawl_config.get("respect_robots_txt", True))
        self.sleep = float(crawl_config.get("sleep_seconds_between_requests", 1.5))
        self.log = get_logger()
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # ---- robots.txt ----
    def _get_robots(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        """サイトの robots.txt を取得（キャッシュつき）。"""
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots_cache:
            return self._robots_cache[origin]

        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(urljoin(origin, "/robots.txt"))
        try:
            rp.read()
        except Exception:
            # robots.txt が読めない場合は「制限なし」とみなす（過度に保守的にしない）
            rp = None
        self._robots_cache[origin] = rp
        return rp

    def _can_fetch(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self._get_robots(url)
        if rp is None:
            return True
        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception:
            return True

    # ---- ページ取得 ----
    def _fetch(self, url: str) -> tuple[str | None, bool]:
        """1ページを取得する。

        Returns:
            (HTML文字列 or None, ブロックされたか)
        """
        headers = {"User-Agent": self.user_agent,
                   "Accept-Language": "ja,en;q=0.8"}
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout,
                                allow_redirects=True)
        except requests.RequestException as e:
            self.log.debug(f"取得失敗 {url}: {e}")
            return None, False

        if resp.status_code in (401, 403, 429):
            return None, True
        if resp.status_code >= 400:
            return None, False

        ctype = resp.headers.get("Content-Type", "").lower()
        if "html" not in ctype and ctype:
            # PDFや画像など。HTML以外はスキップ。
            return None, False

        resp.encoding = resp.apparent_encoding or resp.encoding
        html = resp.text
        lowered = html.lower()
        if any(sign in lowered for sign in BLOCK_SIGNS):
            return None, True
        return html, False

    def _collect_internal_links(self, base_url: str, html: str) -> list[str]:
        """トップページから、調査価値のある内部ページのURLを集める。"""
        soup = BeautifulSoup(html, "lxml")
        base_domain = urlparse(base_url).netloc
        found: list[str] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            abs_url = urljoin(base_url, href)
            parsed = urlparse(abs_url)
            if parsed.netloc != base_domain:
                continue  # 外部リンクは追わない
            abs_url = abs_url.split("#")[0]
            if abs_url in seen:
                continue

            anchor = (a.get_text() or "").lower()
            target = (anchor + " " + abs_url.lower())
            if any(hint.lower() in target for hint in RELEVANT_LINK_HINTS):
                seen.add(abs_url)
                found.append(abs_url)

        return found

    def crawl_site(self, base_url: str) -> CrawlResult:
        """1サイトをクロールして、主要ページのHTMLを集める。"""
        result = CrawlResult(base_url=base_url)

        if not self._can_fetch(base_url):
            result.robots_disallowed = True
            result.error = "robots.txt によりトップページの取得が許可されていません"
            return result

        top_html, blocked = self._fetch(base_url)
        if blocked:
            result.blocked = True
            result.error = "CAPTCHA／アクセス制限を検知したためスキップ"
            return result
        if top_html is None:
            result.error = "トップページを取得できませんでした"
            return result

        result.pages[base_url] = top_html
        time.sleep(self.sleep)

        # 内部リンクをたどる（max_pages まで）
        candidates = self._collect_internal_links(base_url, top_html)
        for link in candidates:
            if len(result.pages) >= self.max_pages:
                break
            if link in result.pages:
                continue
            if not self._can_fetch(link):
                continue
            page_html, blocked = self._fetch(link)
            if blocked:
                result.blocked = True
                break
            if page_html is not None:
                result.pages[link] = page_html
            time.sleep(self.sleep)

        return result
