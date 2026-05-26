"""検索クライアント。

役割は3つ:
1. 業種×地域から検索クエリを自動生成する
2. 検索API（SerpAPI）を呼んで企業サイト候補を取得する
3. 検索APIの代わりに、手元の企業リストCSVを入力として読み込む

Google検索結果ページの直接スクレイピングは行わない。必ず検索APIかCSVを使う。
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

import requests

from .logging_utils import get_logger
from .models import SearchResult

# 業種グループ -> 細かい業種（sub_industry）のキーワード一覧
INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "建設設備工事": [
        "電気工事", "空調設備", "給排水設備", "消防設備",
        "通信工事", "設備工事", "管工事",
    ],
    "リフォーム": [
        "住宅リフォーム", "外壁塗装", "防水工事",
        "内装工事", "屋根工事", "リノベーション",
    ],
    "工務店": [
        "注文住宅", "地域工務店", "住宅建築", "木造住宅", "住宅施工",
    ],
    "卸売業": [
        "建材卸", "住宅設備卸", "機械工具卸", "食品卸", "業務用食品卸",
        "日用品卸", "包装資材卸", "電材卸", "管材卸",
    ],
}

# クエリの語尾パターン（問い合わせ導線を持つ企業に当たりやすくする）
QUERY_SUFFIXES = ["会社 問い合わせ", "工事 会社 お問い合わせ", "会社 お問い合わせ"]


def generate_queries(industries: list[str], prefectures: list[str]) -> list[dict]:
    """業種×地域から検索クエリを生成する。

    Returns:
        各要素が {industry_group, sub_industry, prefecture, query} の辞書。
    """
    queries: list[dict] = []
    for industry in industries:
        keywords = INDUSTRY_KEYWORDS.get(industry, [industry])
        for prefecture in prefectures:
            for keyword in keywords:
                query = f"{prefecture} {keyword} 会社 問い合わせ"
                queries.append({
                    "industry_group": industry,
                    "sub_industry": keyword,
                    "prefecture": prefecture,
                    "query": query,
                })
    return queries


class SearchClient:
    """検索APIのラッパー。現状は SerpAPI を実装。

    別プロバイダ（Google CSE / Bing / Tavily）は同じ search() を実装すれば
    差し替えられる構造にしている。
    """

    def __init__(self, provider: str, api_keys: dict, timeout: int = 20):
        self.provider = provider
        self.api_keys = api_keys
        self.timeout = timeout
        self.log = get_logger()

    def search(self, query: str, limit: int) -> list[SearchResult]:
        """1クエリ分の検索を実行する。"""
        if self.provider == "serpapi":
            return self._search_serpapi(query, limit)
        # 将来の拡張ポイント。未実装プロバイダは明示的にエラーにする。
        raise NotImplementedError(
            f"検索プロバイダ '{self.provider}' は未対応です。"
            f"現在は 'serpapi' のみ利用できます。"
        )

    def _search_serpapi(self, query: str, limit: int) -> list[SearchResult]:
        """SerpAPI（Google検索）を呼び出す。"""
        api_key = self.api_keys.get("SERPAPI_API_KEY", "")
        if not api_key:
            raise RuntimeError("SERPAPI_API_KEY が設定されていません。")

        params = {
            "engine": "google",
            "q": query,
            "num": min(limit, 20),
            "hl": "ja",
            "gl": "jp",
            "api_key": api_key,
        }
        try:
            resp = requests.get(
                "https://serpapi.com/search.json",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            self.log.warning(f"検索失敗（{query}）: {e}")
            return []
        except ValueError as e:
            self.log.warning(f"検索結果の解析失敗（{query}）: {e}")
            return []

        if data.get("error"):
            self.log.warning(f"SerpAPIエラー（{query}）: {data['error']}")
            return []

        results: list[SearchResult] = []
        for item in data.get("organic_results", [])[:limit]:
            url = item.get("link", "")
            if not url:
                continue
            results.append(SearchResult(
                title=item.get("title", ""),
                url=url,
                snippet=item.get("snippet", ""),
                query=query,
            ))
        return results


def search_all(
    client: SearchClient,
    queries: list[dict],
    limit_per_query: int,
    max_total: int,
    sleep_seconds: float = 1.0,
) -> tuple[list[SearchResult], list[dict]]:
    """全クエリを順に実行して結果を集める。

    Returns:
        (検索結果のリスト, クエリ実行ログ [{...query, result_count}])
    """
    log = get_logger()
    all_results: list[SearchResult] = []
    query_log: list[dict] = []

    for q in queries:
        if len(all_results) >= max_total:
            log.info(f"取得上限 {max_total} 件に達したため検索を打ち切ります。")
            break
        hits = client.search(q["query"], limit_per_query)
        for r in hits:
            r.industry_group = q["industry_group"]
            r.sub_industry = q["sub_industry"]
        all_results.extend(hits)
        query_log.append({**q, "result_count": len(hits)})
        log.info(f"検索: {q['query']} -> {len(hits)} 件")
        time.sleep(sleep_seconds)

    return all_results[:max_total], query_log


def load_from_csv(csv_path: str) -> list[SearchResult]:
    """手元の企業リストCSVを検索結果の代わりに読み込む。

    CSVは少なくとも 'url' 列を持つこと。'company_name'（または 'name'）、
    'industry_group'、'sub_industry' 列があれば利用する。
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"入力CSVが見つかりません: {csv_path}")

    results: list[SearchResult] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("入力CSVにヘッダー行がありません。")
        lower_map = {name.lower().strip(): name for name in reader.fieldnames}

        if "url" not in lower_map:
            raise ValueError(
                "入力CSVに 'url' 列が必要です。"
                f"見つかった列: {reader.fieldnames}"
            )

        for row in reader:
            url = (row.get(lower_map["url"], "") or "").strip()
            if not url:
                continue
            name = ""
            for key in ("company_name", "name", "会社名"):
                if key in lower_map:
                    name = (row.get(lower_map[key], "") or "").strip()
                    if name:
                        break
            results.append(SearchResult(
                title=name,
                url=url,
                snippet="",
                industry_group=(row.get(lower_map.get("industry_group", ""), "") or "").strip(),
                sub_industry=(row.get(lower_map.get("sub_industry", ""), "") or "").strip(),
                query="(CSV入力)",
            ))
    return results
