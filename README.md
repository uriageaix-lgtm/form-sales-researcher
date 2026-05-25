# フォーム営業リサーチ自動化ツール（GitHub Actions版）

建設設備工事・リフォーム・工務店・卸売業を対象に、フォーム営業の対象企業を
Web上でリサーチし、Googleスプレッドシートに営業リストとして保存するツールです。

GitHub Actions により、**毎朝決まった時刻に自動で実行**されます。
パソコンを開いていなくても、リストが自動で更新されていきます。

このツールは問い合わせフォームへの送信は行いません。企業の発見・調査・
スコアリング・営業文案の生成・スプレッドシート保存までを行います。
送信は、できあがったリストを人が確認したうえで行う前提です。

## セットアップ

初めての方は **SETUP_GUIDE.md** を見てください。GitHubへの登録から
毎朝の自動実行まで、初心者向けに手順を詳しく書いています。

## 動作の流れ

1. config.yaml の業種×都道府県から検索クエリを自動生成
2. SerpAPIで企業の公式サイト候補を収集
3. ポータル・求人・SNSなどを除外し、重複企業をまとめる
4. 各企業サイトを控えめにクロール（robots.txt遵守）
5. 会社情報・問い合わせフォームURLなどを抽出
6. 指定した都道府県の企業だけに絞り込む（filter_by_prefecture）
7. AI研修サービスとの相性を100点満点でスコアリング
8. 営業切り口・件名案・本文冒頭案を生成
9. Googleスプレッドシートへ保存（重複させず更新）

## 設定

`config.yaml` で対象や条件を調整できます。主な項目：

- `prefectures`：調べる都道府県（1県ずつ進めるならここを1つに）
- `industries`：調べる業種
- `limit_per_query`：1クエリあたりの件数
- `filter_by_prefecture`：true なら指定県の企業だけ残す

## 必要な秘密情報（GitHub Secrets に登録）

- `SERPAPI_API_KEY`：SerpAPIのキー
- `GOOGLE_SHEET_ID`：保存先スプレッドシートのID
- `GOOGLE_SERVICE_ACCOUNT_JSON`：サービスアカウントのJSON（中身まるごと）

## 実行時刻の変更

`.github/workflows/research.yml` の `cron` を編集します。
時刻はUTC（日本時間より9時間遅い）。初期設定は日本時間の朝9時です。

## テスト

```
pip install -e ".[dev]"
pytest
```

## ディレクトリ構成

```
.github/workflows/research.yml   毎朝の自動実行設定
src/                             ツール本体
tests/                           テスト
config.yaml                      業種・地域などの設定
SETUP_GUIDE.md                   初心者向けセットアップ手順
```
