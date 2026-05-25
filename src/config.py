"""設定の読み込み。

config.yaml（業種・地域・スコアリング条件など）と
.env（APIキーなどの秘匿情報）を読み込み、ひとつの Config にまとめる。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values, load_dotenv
import os


@dataclass
class Config:
    """ツール全体の設定値。"""

    raw: dict = field(default_factory=dict)   # config.yaml の内容そのまま
    env: dict = field(default_factory=dict)   # .env ＋ 環境変数

    # ---- targets ----
    @property
    def prefectures(self) -> list[str]:
        return list(self.raw.get("targets", {}).get("prefectures", []))

    @property
    def industries(self) -> list[str]:
        return list(self.raw.get("targets", {}).get("industries", []))

    @property
    def limit_per_query(self) -> int:
        return int(self.raw.get("targets", {}).get("limit_per_query", 10))

    @property
    def max_total_results(self) -> int:
        return int(self.raw.get("targets", {}).get("max_total_results", 200))

    # ---- search ----
    @property
    def search_provider(self) -> str:
        # .env が優先、なければ config.yaml
        return (
            self.env.get("SEARCH_PROVIDER")
            or self.raw.get("search", {}).get("provider", "serpapi")
        ).strip().lower()

    @property
    def search_timeout(self) -> int:
        return int(self.raw.get("search", {}).get("timeout_seconds", 20))

    @property
    def excluded_domains(self) -> list[str]:
        return [d.lower() for d in self.raw.get("search", {}).get("excluded_domains", [])]

    # ---- crawl ----
    @property
    def crawl(self) -> dict:
        return self.raw.get("crawl", {})

    # ---- sheets ----
    @property
    def spreadsheet_id(self) -> str:
        # .env の GOOGLE_SHEET_ID が優先
        return (
            self.env.get("GOOGLE_SHEET_ID")
            or self.raw.get("sheets", {}).get("spreadsheet_id", "")
        ).strip()

    @property
    def sheets(self) -> dict:
        return self.raw.get("sheets", {})

    # ---- scoring ----
    @property
    def use_llm(self) -> bool:
        return bool(self.raw.get("scoring", {}).get("use_llm", False))

    @property
    def min_score_to_save(self) -> int:
        return int(self.raw.get("scoring", {}).get("min_score_to_save", 50))

    @property
    def high_priority_score(self) -> int:
        return int(self.raw.get("scoring", {}).get("high_priority_score", 80))

    @property
    def filter_by_prefecture(self) -> bool:
        """サイトの所在地が指定した都道府県と一致する企業だけを残すか。"""
        return bool(self.raw.get("targets", {}).get("filter_by_prefecture", True))

    # ---- output ----
    @property
    def save_local_csv(self) -> bool:
        return bool(self.raw.get("output", {}).get("save_local_csv", True))

    @property
    def local_csv_path(self) -> str:
        return self.raw.get("output", {}).get("local_csv_path", "./output/prospects.csv")

    @property
    def log_path(self) -> str:
        return self.raw.get("output", {}).get("log_path", "./output/run.log")

    # ---- secrets ----
    def secret(self, key: str, default: str = "") -> str:
        return (self.env.get(key) or default).strip()


def load_config(config_path: str, env_path: str = ".env") -> Config:
    """config.yaml と .env を読み込んで Config を返す。

    Args:
        config_path: config.yaml のパス。
        env_path: .env のパス。存在しなくてもエラーにしない。
    """
    cfg_file = Path(config_path)
    if not cfg_file.exists():
        raise FileNotFoundError(
            f"設定ファイルが見つかりません: {config_path}\n"
            f"config.example.yaml を config.yaml にコピーしてください。"
        )

    with cfg_file.open(encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    # .env を読み込む（無くてもよい）。プロセスの環境変数も取り込む。
    env: dict[str, Any] = {}
    if Path(env_path).exists():
        load_dotenv(env_path)
        env.update({k: v for k, v in dotenv_values(env_path).items() if v is not None})
    # OS の環境変数で上書き（CI などで便利）
    for key in (
        "SEARCH_PROVIDER", "SERPAPI_API_KEY", "GOOGLE_CSE_API_KEY", "GOOGLE_CSE_ID",
        "BING_SEARCH_API_KEY", "TAVILY_API_KEY", "GOOGLE_SERVICE_ACCOUNT_JSON",
        "GOOGLE_SHEET_ID", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
    ):
        if os.environ.get(key):
            env[key] = os.environ[key]

    return Config(raw=raw, env=env)


def validate_for_run(config: Config, dry_run: bool, input_csv: str | None) -> list[str]:
    """実行前のチェック。問題があれば警告メッセージのリストを返す。

    致命的でないものは警告として返し、呼び出し側が判断する。
    """
    warnings: list[str] = []

    if not input_csv:
        provider = config.search_provider
        if provider == "serpapi" and not config.secret("SERPAPI_API_KEY"):
            warnings.append(
                "SERPAPI_API_KEY が未設定です。検索を実行できません。"
                "（--input-csv で企業リストを直接渡す場合は不要です）"
            )

    if not dry_run:
        if not config.spreadsheet_id:
            warnings.append(
                "GOOGLE_SHEET_ID が未設定です。スプレッドシートへ書き込めません。"
            )
        sa_path = config.secret("GOOGLE_SERVICE_ACCOUNT_JSON", "./service-account.json")
        if not Path(sa_path).exists():
            warnings.append(
                f"サービスアカウントJSONが見つかりません: {sa_path}"
            )

    if not config.industries:
        warnings.append("config.yaml の targets.industries が空です。")
    if not config.prefectures and not input_csv:
        warnings.append("config.yaml の targets.prefectures が空です。")

    return warnings
