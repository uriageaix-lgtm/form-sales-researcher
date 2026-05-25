"""重複排除とID生成。

同じ企業を再実行で二重登録しないために、URLから安定した prospect_id を作る。
prospect_id はドメインのハッシュなので、同じサイトなら常に同じIDになる。
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse


def normalize_domain(url: str) -> str:
    """URLから比較・ID生成に使う正規化ドメインを取り出す。

    - スキームの有無を吸収
    - 大文字小文字を無視
    - 先頭の "www." を除去
    - ポート番号を除去

    例: "https://WWW.Example.co.jp:443/contact" -> "example.co.jp"
    """
    if not url:
        return ""
    text = url.strip()
    if "://" not in text:
        text = "http://" + text
    netloc = urlparse(text).netloc.lower()
    netloc = netloc.split("@")[-1]   # 認証情報を除去
    netloc = netloc.split(":")[0]    # ポートを除去
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def make_prospect_id(url: str) -> str:
    """URL（ドメイン）から安定した prospect_id を生成する。

    同じドメインなら常に同じIDになる。先頭に "p_" を付けた12桁のハッシュ。
    """
    domain = normalize_domain(url)
    digest = hashlib.sha256(domain.encode("utf-8")).hexdigest()
    return f"p_{digest[:12]}"


def normalize_company_name(name: str) -> str:
    """会社名を比較用に正規化する。

    法人格表記や記号・空白を落として、表記ゆれの一部を吸収する。
    """
    if not name:
        return ""
    text = name.strip().lower()
    # 法人格表記を除去
    for token in ("株式会社", "有限会社", "合同会社", "合資会社", "(株)", "（株）",
                   "(有)", "（有）", "co.,ltd.", "co.,ltd", "co., ltd.", "inc.",
                   "ltd.", "corporation", "corp."):
        text = text.replace(token, "")
    # 空白・記号を除去
    text = re.sub(r"[\s　・,，.。\-―ー‐]", "", text)
    return text


def is_excluded_domain(url: str, excluded_domains: list[str]) -> bool:
    """除外対象ドメイン（ポータル・求人・SNSなど）かどうか判定する。"""
    domain = normalize_domain(url)
    if not domain:
        return True
    for ex in excluded_domains:
        ex = ex.lower().strip()
        if not ex:
            continue
        # 完全一致、またはサブドメイン一致
        if domain == ex or domain.endswith("." + ex):
            return True
    return False


def dedupe_search_results(results: list) -> tuple[list, list]:
    """検索結果を重複排除する。

    同一ドメイン、または正規化後に同名の会社は最初の1件だけ残す。

    Returns:
        (残した結果のリスト, 除外した (url, reason) のリスト)
    """
    seen_domains: set[str] = set()
    seen_names: set[str] = set()
    kept: list = []
    dropped: list[tuple[str, str]] = []

    for r in results:
        url = getattr(r, "url", "") or ""
        name = getattr(r, "title", "") or ""
        domain = normalize_domain(url)
        norm_name = normalize_company_name(name)

        if not domain:
            dropped.append((url, "URLが不正"))
            continue
        if domain in seen_domains:
            dropped.append((url, "同一ドメインの重複"))
            continue
        if norm_name and norm_name in seen_names:
            dropped.append((url, "同名会社の重複"))
            continue

        seen_domains.add(domain)
        if norm_name:
            seen_names.add(norm_name)
        kept.append(r)

    return kept, dropped
