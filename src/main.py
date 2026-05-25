"""CLIエントリポイント。

検索 → 重複排除 → クロール → 抽出 → スコアリング → Sheets保存 までを通す。

実行例:
    python -m src.main --config config.yaml
    python -m src.main --config config.yaml --industry "建設設備工事" --prefecture "東京都" --limit 50
    python -m src.main --config config.yaml --dry-run
    python -m src.main --config config.yaml --input-csv mylist.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config, validate_for_run
from .crawler import Crawler
from .dedupe import (
    dedupe_search_results, is_excluded_domain, make_prospect_id, normalize_domain,
)
from .extractor import extract
from .logging_utils import setup_logger
from .models import CrawlStatus, Prospect, RunStats
from .scorer import score_prospect
from .search_client import SearchClient, generate_queries, load_from_csv, search_all


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="form-sales-researcher",
        description="フォーム営業向け 企業リサーチ自動化ツール",
    )
    parser.add_argument("--config", default="config.yaml",
                        help="設定ファイルのパス（既定: config.yaml）")
    parser.add_argument("--env", default=".env",
                        help=".env ファイルのパス（既定: .env）")
    parser.add_argument("--industry", action="append", default=None,
                        help="対象業種を絞る（複数指定可。config.yaml より優先）")
    parser.add_argument("--prefecture", action="append", default=None,
                        help="対象都道府県を絞る（複数指定可。config.yaml より優先）")
    parser.add_argument("--limit", type=int, default=None,
                        help="1クエリあたりの取得件数（config.yaml より優先）")
    parser.add_argument("--input-csv", default=None,
                        help="検索の代わりに企業リストCSVを入力にする（'url' 列が必須）")
    parser.add_argument("--dry-run", action="store_true",
                        help="スプレッドシートへ書き込まずに流れだけ確認する")
    parser.add_argument("--verbose", action="store_true",
                        help="詳細ログを出力する")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    config = load_config(args.config, args.env)
    log = setup_logger(config.log_path, verbose=args.verbose)

    # CLI引数で config を上書き
    industries = args.industry or config.industries
    prefectures = args.prefecture or config.prefectures
    limit_per_query = args.limit or config.limit_per_query

    log.info("=" * 60)
    log.info("フォーム営業リサーチを開始します。")
    log.info(f"業種: {industries} / 地域: {prefectures}")
    log.info(f"モード: {'CSV入力' if args.input_csv else '検索API'}"
             f"{' / ドライラン' if args.dry_run else ''}")

    # 事前チェック
    for w in validate_for_run(config, args.dry_run, args.input_csv):
        log.warning(f"注意: {w}")

    stats = RunStats(
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        industries=", ".join(industries),
        prefectures=", ".join(prefectures),
        dry_run=args.dry_run,
    )

    # ---- 1. 企業候補の取得（検索 or CSV） ----
    query_log: list[dict] = []
    if args.input_csv:
        try:
            results = load_from_csv(args.input_csv)
        except (FileNotFoundError, ValueError) as e:
            log.error(f"CSV読み込みエラー: {e}")
            return 1
        log.info(f"CSVから {len(results)} 件の企業を読み込みました。")
    else:
        if not config.secret("SERPAPI_API_KEY"):
            log.error("SERPAPI_API_KEY が未設定のため検索できません。"
                      "--input-csv を使うか .env を設定してください。")
            return 1
        client = SearchClient(
            provider=config.search_provider,
            api_keys={"SERPAPI_API_KEY": config.secret("SERPAPI_API_KEY")},
            timeout=config.search_timeout,
        )
        queries = generate_queries(industries, prefectures)
        log.info(f"検索クエリを {len(queries)} 件生成しました。")
        results, query_log = search_all(
            client, queries, limit_per_query,
            config.max_total_results,
            sleep_seconds=1.0,
        )

    stats.queries_used = len(query_log)
    stats.search_hits = len(results)

    # ---- 2. 除外ドメインの除去 ＋ 重複排除 ----
    filtered = []
    for r in results:
        if is_excluded_domain(r.url, config.excluded_domains):
            stats.excluded.append((r.url, "除外ドメイン（ポータル・求人・SNS等）"))
        else:
            filtered.append(r)
    deduped, dropped = dedupe_search_results(filtered)
    stats.excluded.extend(dropped)
    stats.after_dedupe = len(deduped)
    log.info(f"除外・重複排除後: {len(deduped)} 件 "
             f"（除外 {len(stats.excluded)} 件）")

    # ---- 3. 各企業をクロール → 抽出 → スコアリング ----
    crawler = Crawler(config.crawl)
    prospects: list[Prospect] = []

    for idx, r in enumerate(deduped, start=1):
        log.info(f"[{idx}/{len(deduped)}] 調査中: {r.url}")
        prospect = Prospect(
            prospect_id=make_prospect_id(r.url),
            website_url=r.url,
            company_name=r.title,
            industry_group=r.industry_group,
            sub_industry=r.sub_industry,
        )
        prospect.stamp_now()

        try:
            crawl_result = crawler.crawl_site(r.url)
            stats.crawled += 1

            if crawl_result.robots_disallowed:
                prospect.crawl_status = CrawlStatus.SKIPPED
                prospect.error_message = crawl_result.error
                prospect.notes = "robots.txt の指定によりクロールを見送り"
                stats.skipped += 1
            elif crawl_result.blocked:
                prospect.crawl_status = CrawlStatus.SKIPPED
                prospect.error_message = crawl_result.error
                prospect.notes = "CAPTCHA／アクセス制限のためスキップ"
                stats.skipped += 1
            elif not crawl_result.pages:
                prospect.crawl_status = CrawlStatus.FAILED
                prospect.error_message = crawl_result.error or "ページを取得できず"
                stats.errors += 1
            else:
                # 抽出
                info = extract(crawl_result.pages, fallback_name=r.title)
                extra = {k: v for k, v in info.items() if k.startswith("_")}
                for key, value in info.items():
                    if key.startswith("_"):
                        continue
                    # 検索由来の業種は抽出で上書きしない
                    if key in ("industry_group", "sub_industry"):
                        continue
                    if value:
                        setattr(prospect, key, value)

                # スコアリング
                score_prospect(prospect, extra, config.high_priority_score)

                # 営業禁止表記・採用専用フォームの注記
                if extra.get("_has_no_sales"):
                    prospect.crawl_status = CrawlStatus.PARTIAL
                    prospect.notes = "営業目的の連絡を断る記載あり。送信前に要確認。"
                elif extra.get("_recruit_only_form"):
                    prospect.crawl_status = CrawlStatus.PARTIAL
                    prospect.notes = "見つかったのは採用応募フォームのみ。要確認。"
                elif info.get("_page_count", 0) >= 2:
                    prospect.crawl_status = CrawlStatus.SUCCESS
                else:
                    prospect.crawl_status = CrawlStatus.PARTIAL

        except Exception as e:
            # 1社のエラーで全体を止めない
            prospect.crawl_status = CrawlStatus.FAILED
            prospect.error_message = f"{type(e).__name__}: {e}"
            stats.errors += 1
            log.warning(f"  調査中にエラー: {e}")

        prospects.append(prospect)

    # ---- 3.5 都道府県による絞り込み ----
    # config の filter_by_prefecture が true のとき、サイトから読み取った所在地が
    # 指定した都道府県と一致する企業だけを残す。
    # 他県の企業は除外タブに記録。所在地が不明な企業は notes に印を付けて残す。
    if config.filter_by_prefecture and prefectures and not args.input_csv:
        target_prefs = set(prefectures)
        kept_after_pref = []
        for p in prospects:
            # クロール失敗・スキップはそのまま残す（所在地を取れていないため）
            if p.crawl_status in (CrawlStatus.SKIPPED, CrawlStatus.FAILED):
                kept_after_pref.append(p)
                continue
            if not p.prefecture:
                # 所在地が読み取れなかった企業は、印を付けて残す
                note = "所在地未確認（都道府県を自動判定できず）"
                p.notes = (p.notes + " / " + note) if p.notes else note
                kept_after_pref.append(p)
            elif p.prefecture in target_prefs:
                # 指定した都道府県と一致
                kept_after_pref.append(p)
            else:
                # 他県のため除外。除外タブに記録する。
                stats.excluded.append(
                    (p.website_url, f"対象外の都道府県（{p.prefecture}）")
                )
        removed = len(prospects) - len(kept_after_pref)
        prospects = kept_after_pref
        log.info(f"都道府県の絞り込み: {removed} 件を対象外として除外 "
                 f"（指定: {', '.join(prefectures)}）")

    # ---- 4. 保存対象の絞り込み ----
    to_save = [
        p for p in prospects
        if p.ai_fit_score >= config.min_score_to_save
        or p.crawl_status in (CrawlStatus.SKIPPED, CrawlStatus.FAILED)
    ]
    log.info(f"保存対象: {len(to_save)} 件 / 調査 {len(prospects)} 件 "
             f"（min_score_to_save={config.min_score_to_save}）")

    # ---- 5. ローカルCSV出力 ----
    if config.save_local_csv:
        _write_local_csv(config.local_csv_path, prospects)
        log.info(f"ローカルCSVを保存しました: {config.local_csv_path}")

    # ---- 6. スプレッドシートへ保存 ----
    stats.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if args.dry_run:
        log.info("ドライランのためスプレッドシートへの書き込みはスキップします。")
        _print_summary(prospects, stats, log)
        return 0

    if not config.spreadsheet_id:
        log.warning("GOOGLE_SHEET_ID が未設定のため、スプレッドシート保存をスキップしました。")
        _print_summary(prospects, stats, log)
        return 0

    try:
        from .sheets_client import SheetsClient
        sheets = SheetsClient(
            service_account_json=config.secret(
                "GOOGLE_SERVICE_ACCOUNT_JSON", "./service-account.json"),
            spreadsheet_id=config.spreadsheet_id,
            sheet_names=config.sheets,
        )
        sheets.ensure_tabs()
        added, updated = sheets.upsert_prospects(to_save)
        stats.saved = added + updated
        sheets.append_search_queries(query_log)
        sheets.append_exclusions(stats.excluded)
        sheets.append_run_log(stats)
        sheets.write_config_snapshot([
            ("industries", ", ".join(industries)),
            ("prefectures", ", ".join(prefectures)),
            ("limit_per_query", str(limit_per_query)),
            ("min_score_to_save", str(config.min_score_to_save)),
            ("use_llm", str(config.use_llm)),
        ])
        log.info(f"スプレッドシートへ保存しました（新規 {added} 件 / 更新 {updated} 件）。")
    except Exception as e:
        log.error(f"スプレッドシート保存でエラー: {type(e).__name__}: {e}")
        log.error("ローカルCSVには結果が残っています。")
        return 1

    _print_summary(prospects, stats, log)
    return 0


def _write_local_csv(path: str, prospects: list[Prospect]) -> None:
    """調査結果をローカルCSVへ書き出す。"""
    from .models import PROSPECT_HEADERS
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(PROSPECT_HEADERS)
        for p in prospects:
            writer.writerow(p.to_row())


def _print_summary(prospects: list[Prospect], stats: RunStats, log) -> None:
    """実行結果のサマリをログに出す。"""
    high = [p for p in prospects if p.ai_fit_score >= 80]
    log.info("-" * 60)
    log.info(f"調査企業数: {len(prospects)}")
    log.info(f"  スコア80以上（最優先）: {len(high)} 件")
    log.info(f"  クロール成功: {stats.crawled} / スキップ: {stats.skipped} "
             f"/ エラー: {stats.errors}")
    if high:
        log.info("最優先候補:")
        for p in sorted(high, key=lambda x: -x.ai_fit_score)[:10]:
            log.info(f"  {p.ai_fit_score}点  {p.company_name}  {p.website_url}")
    log.info("=" * 60)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except FileNotFoundError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n中断しました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
