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


# 役所・公的機関・業界団体を示すキーワード（営業先にならないため除外する）
NON_BUSINESS_KEYWORDS = [
    # 自治体・役所
    "市役所", "区役所", "町役場", "村役場", "県庁", "都庁", "道庁", "府庁",
    "水道局", "下水道", "教育委員会", "保健所", "保健センター", "消防署",
    "消防局", "警察署", "図書館", "公民館", "市議会", "県議会",
    "地方公共団体", "自治体", "出張所", "支所",
    # 公的機関・独立行政法人など
    "独立行政法人", "公社", "事業団", "公団", "公庫", "機構",
    "ハローワーク", "職業安定所", "年金事務所", "税務署", "法務局",
    # 業界団体・協同組合
    "協会", "協議会", "組合", "連合会", "連合", "商工会", "商工会議所",
    "振興会", "振興協会", "事業協同組合", "農業協同組合", "農協",
    "漁業協同組合", "漁協", "生活協同組合", "生協", "共済", "財団法人",
    "社団法人", "公益財団", "公益社団", "一般財団", "一般社団",
    "学会", "研究会連合",
]

# 役所・公的機関でよく使われるドメイン末尾
NON_BUSINESS_DOMAIN_SUFFIXES = [
    ".go.jp",    # 国の機関
    ".lg.jp",    # 地方自治体
    ".ed.jp",    # 教育機関
    ".ac.jp",    # 大学など
]


def is_non_business(name: str, url: str) -> tuple[bool, str]:
    """役所・公的機関・業界団体かどうかを判定する。

    会社名（検索結果のタイトル）とURLの両方から判定する。
    営業先として不適切なものを True で返す。

    Returns:
        (除外すべきか, 理由)
    """
    text = (name or "")
    # ドメイン末尾で判定（.go.jp / .lg.jp など）
    domain = normalize_domain(url)
    for suffix in NON_BUSINESS_DOMAIN_SUFFIXES:
        if domain.endswith(suffix):
            return True, f"役所・公的機関（{suffix}ドメイン）"
    # 名前に含まれるキーワードで判定
    for keyword in NON_BUSINESS_KEYWORDS:
        if keyword in text:
            return True, f"役所・団体（「{keyword}」を含む）"
    return False, ""
