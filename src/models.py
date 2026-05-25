"""データモデル定義。

スプレッドシートの1行＝1企業（Prospect）を表すデータクラスと、
列の並び順・取りうるステータス値をここで一元管理する。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


class CrawlStatus:
    """crawl_status 列に入る値。"""

    SUCCESS = "success"   # 主要情報を取得できた
    PARTIAL = "partial"   # 一部だけ取得できた
    FAILED = "failed"     # 取得に失敗した
    SKIPPED = "skipped"   # 方針上クロールを見送った


class OutreachStatus:
    """outreach_status 列に入る値。"""

    NOT_SENT = "未送信"
    SENT = "送信済み"
    REPLIED = "返信あり"
    EXCLUDED = "対象外"


# スプレッドシート Prospects タブの列順。Prospect のフィールド名と一致させる。
PROSPECT_HEADERS: list[str] = [
    "prospect_id",
    "company_name",
    "industry_group",
    "sub_industry",
    "prefecture",
    "city",
    "address",
    "website_url",
    "contact_form_url",
    "contact_form_found",
    "phone",
    "email",
    "representative",
    "employee_count",
    "business_summary",
    "pain_signals",
    "ai_fit_score",
    "score_reason",
    "sales_angle",
    "personalization_note",
    "suggested_subject",
    "suggested_opening",
    "source_urls",
    "crawl_status",
    "error_message",
    "researched_at",
    "outreach_status",
    "notes",
]


@dataclass
class Prospect:
    """営業対象企業1社分の情報。"""

    prospect_id: str = ""
    company_name: str = ""
    industry_group: str = ""
    sub_industry: str = ""
    prefecture: str = ""
    city: str = ""
    address: str = ""
    website_url: str = ""
    contact_form_url: str = ""
    contact_form_found: bool = False
    phone: str = ""
    email: str = ""
    representative: str = ""
    employee_count: str = ""
    business_summary: str = ""
    pain_signals: str = ""
    ai_fit_score: int = 0
    score_reason: str = ""
    sales_angle: str = ""
    personalization_note: str = ""
    suggested_subject: str = ""
    suggested_opening: str = ""
    source_urls: str = ""
    crawl_status: str = CrawlStatus.FAILED
    error_message: str = ""
    researched_at: str = ""
    outreach_status: str = OutreachStatus.NOT_SENT
    notes: str = ""

    def stamp_now(self) -> None:
        """researched_at に現在時刻（ISO 8601）を入れる。"""
        self.researched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_row(self) -> list:
        """PROSPECT_HEADERS の順番でセルのリストに変換する。

        スプレッドシートのセルに入れやすいよう、bool は TRUE/FALSE 文字列にする。
        """
        data = asdict(self)
        row: list = []
        for key in PROSPECT_HEADERS:
            value = data.get(key, "")
            if isinstance(value, bool):
                value = "TRUE" if value else "FALSE"
            elif value is None:
                value = ""
            row.append(value)
        return row

    def to_dict(self) -> dict:
        """CSV出力などに使う辞書表現。"""
        return dict(zip(PROSPECT_HEADERS, self.to_row()))


@dataclass
class SearchResult:
    """検索APIから返ってきた1件分の結果。"""

    title: str = ""
    url: str = ""
    snippet: str = ""
    industry_group: str = ""
    sub_industry: str = ""
    query: str = ""


@dataclass
class RunStats:
    """1回の実行の集計値。Run_Log タブに書き込む。"""

    started_at: str = ""
    finished_at: str = ""
    industries: str = ""
    prefectures: str = ""
    queries_used: int = 0
    search_hits: int = 0
    after_dedupe: int = 0
    crawled: int = 0
    saved: int = 0
    skipped: int = 0
    errors: int = 0
    dry_run: bool = False
    notes: str = ""

    excluded: list = field(default_factory=list)  # (url, reason) のリスト

    def to_row(self) -> list:
        return [
            self.started_at,
            self.finished_at,
            self.industries,
            self.prefectures,
            self.queries_used,
            self.search_hits,
            self.after_dedupe,
            self.crawled,
            self.saved,
            self.skipped,
            self.errors,
            "TRUE" if self.dry_run else "FALSE",
            self.notes,
        ]


RUN_LOG_HEADERS: list[str] = [
    "started_at",
    "finished_at",
    "industries",
    "prefectures",
    "queries_used",
    "search_hits",
    "after_dedupe",
    "crawled",
    "saved",
    "skipped",
    "errors",
    "dry_run",
    "notes",
]

SEARCH_QUERY_HEADERS: list[str] = [
    "ran_at",
    "industry_group",
    "sub_industry",
    "prefecture",
    "query",
    "result_count",
]

EXCLUSION_HEADERS: list[str] = [
    "excluded_at",
    "url",
    "reason",
]
