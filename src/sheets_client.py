"""Google Sheets への保存。

サービスアカウント認証で対象スプレッドシートに接続し、
Prospects / Run_Log / Search_Queries / Exclusions / Config の各タブへ書き込む。

Prospects への書き込みは冪等（upsert）。prospect_id または website_url が
一致する行があれば更新し、無ければ追記する。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

from .logging_utils import get_logger
from .models import (
    PROSPECT_HEADERS, RUN_LOG_HEADERS, SEARCH_QUERY_HEADERS,
    EXCLUSION_HEADERS, Prospect, RunStats,
)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _with_retry(func, *args, max_retries: int = 4, **kwargs):
    """Google Sheets API の書き込みを、上限エラー時にリトライする。

    「1分あたりの書き込み回数」の上限（429エラー）に当たった場合、
    少し待ってから再試行する。待ち時間は試行ごとに延ばす。
    """
    log = get_logger()
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            is_quota = "429" in str(e) or "Quota exceeded" in str(e)
            if not is_quota or attempt == max_retries - 1:
                raise
            wait = 30 * (attempt + 1)
            log.warning(f"スプレッドシートの書き込み上限に達しました。"
                        f"{wait}秒待って再試行します（{attempt + 1}回目）。")
            time.sleep(wait)
    return None


class SheetsClient:
    """Googleスプレッドシートへの読み書きを担当する。"""

    def __init__(self, service_account_json: str, spreadsheet_id: str, sheet_names: dict):
        self.log = get_logger()
        self.spreadsheet_id = spreadsheet_id
        self.sheet_names = sheet_names

        creds = Credentials.from_service_account_file(
            service_account_json, scopes=_SCOPES
        )
        self.client = gspread.authorize(creds)
        self.spreadsheet = self.client.open_by_key(spreadsheet_id)

    def _get_or_create_worksheet(self, name: str, headers: list[str]):
        """指定名のタブを取得。無ければ作成し、ヘッダー行を入れる。"""
        try:
            ws = self.spreadsheet.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet(
                title=name, rows=200, cols=max(len(headers), 10)
            )
            ws.update([headers], "A1")
            self.log.info(f"タブ '{name}' を新規作成しました。")
            return ws

        first_row = ws.row_values(1)
        if not first_row:
            ws.update([headers], "A1")
        return ws

    def ensure_tabs(self) -> None:
        """必要なタブを全て用意する。"""
        self._get_or_create_worksheet(
            self.sheet_names.get("prospects_sheet", "Prospects"), PROSPECT_HEADERS)
        self._get_or_create_worksheet(
            self.sheet_names.get("run_log_sheet", "Run_Log"), RUN_LOG_HEADERS)
        self._get_or_create_worksheet(
            self.sheet_names.get("search_queries_sheet", "Search_Queries"),
            SEARCH_QUERY_HEADERS)
        self._get_or_create_worksheet(
            self.sheet_names.get("exclusions_sheet", "Exclusions"),
            EXCLUSION_HEADERS)

    def upsert_prospects(self, prospects: list[Prospect]) -> tuple[int, int]:
        """Prospects タブへ upsert する。

        Returns:
            (新規追加した件数, 更新した件数)
        """
        if not prospects:
            return 0, 0

        ws = self._get_or_create_worksheet(
            self.sheet_names.get("prospects_sheet", "Prospects"), PROSPECT_HEADERS)

        existing = ws.get_all_values()
        header = existing[0] if existing else PROSPECT_HEADERS
        rows = existing[1:] if len(existing) > 1 else []

        id_col = header.index("prospect_id") if "prospect_id" in header else 0
        url_col = header.index("website_url") if "website_url" in header else 7

        id_to_row: dict[str, int] = {}
        url_to_row: dict[str, int] = {}
        for i, row in enumerate(rows):
            sheet_row = i + 2
            if id_col < len(row) and row[id_col]:
                id_to_row[row[id_col]] = sheet_row
            if url_col < len(row) and row[url_col]:
                url_to_row[row[url_col].rstrip("/")] = sheet_row

        added = 0
        updated = 0
        to_append: list[list] = []
        to_update: list[dict] = []

        last_col = _col_letter(len(PROSPECT_HEADERS))
        for p in prospects:
            row_values = p.to_row()
            target_row = id_to_row.get(p.prospect_id)
            if target_row is None:
                target_row = url_to_row.get((p.website_url or "").rstrip("/"))

            if target_row is not None:
                to_update.append({
                    "range": f"A{target_row}:{last_col}{target_row}",
                    "values": [row_values],
                })
                updated += 1
            else:
                to_append.append(row_values)
                added += 1

        if to_update:
            _with_retry(ws.batch_update, to_update,
                        value_input_option="USER_ENTERED")

        if to_append:
            _with_retry(ws.append_rows, to_append,
                        value_input_option="USER_ENTERED")

        return added, updated

    def append_run_log(self, stats: RunStats) -> None:
        """Run_Log タブへ実行サマリを追記する。"""
        ws = self._get_or_create_worksheet(
            self.sheet_names.get("run_log_sheet", "Run_Log"), RUN_LOG_HEADERS)
        _with_retry(ws.append_row, stats.to_row(),
                    value_input_option="USER_ENTERED")

    def append_search_queries(self, query_log: list[dict]) -> None:
        """Search_Queries タブへ使用したクエリを追記する。"""
        if not query_log:
            return
        ws = self._get_or_create_worksheet(
            self.sheet_names.get("search_queries_sheet", "Search_Queries"),
            SEARCH_QUERY_HEADERS)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [
            [now, q.get("industry_group", ""), q.get("sub_industry", ""),
             q.get("prefecture", ""), q.get("query", ""), q.get("result_count", 0)]
            for q in query_log
        ]
        _with_retry(ws.append_rows, rows, value_input_option="USER_ENTERED")

    def append_exclusions(self, exclusions: list[tuple]) -> None:
        """Exclusions タブへ除外したURLと理由を追記する。"""
        if not exclusions:
            return
        ws = self._get_or_create_worksheet(
            self.sheet_names.get("exclusions_sheet", "Exclusions"),
            EXCLUSION_HEADERS)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [[now, url, reason] for url, reason in exclusions]
        _with_retry(ws.append_rows, rows, value_input_option="USER_ENTERED")

    def write_config_snapshot(self, config_rows: list[tuple]) -> None:
        """Config タブへ現在の設定値の控えを書き込む。"""
        name = self.sheet_names.get("config_sheet", "Config")
        ws = self._get_or_create_worksheet(name, ["key", "value"])
        _with_retry(ws.clear)
        _with_retry(ws.update,
                    [["key", "value"]] + [list(r) for r in config_rows], "A1")


def _col_letter(n: int) -> str:
    """1始まりの列番号をスプレッドシートの列記号（A, B, ... AA）に変換する。"""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result
