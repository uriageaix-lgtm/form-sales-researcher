"""extractor モジュールのテスト。

実サイトにはアクセスせず、サンプルHTMLで抽出ロジックを確認する。
"""
from src.extractor import extract

SAMPLE_TOP_HTML = """
<html>
<head>
  <title>株式会社サンプル電気工事 | 東京の電気設備工事</title>
  <meta name="description" content="株式会社サンプル電気工事は東京都新宿区を拠点に、電気工事・空調設備工事を行う会社です。施工事例多数。">
  <meta property="og:site_name" content="株式会社サンプル電気工事">
</head>
<body>
  <h1>株式会社サンプル電気工事</h1>
  <p>〒160-0023 東京都新宿区西新宿1-2-3</p>
  <p>電話: 03-1234-5678</p>
  <p>お問い合わせは info@sample-denki.co.jp まで</p>
  <p>代表取締役 山田太郎</p>
  <p>見積や現場報告、若手の教育に力を入れています。施工事例も多数掲載。</p>
  <nav>
    <a href="/company/">会社概要</a>
    <a href="/works/">施工事例</a>
    <a href="/contact/">お問い合わせ</a>
    <a href="/recruit/">採用情報</a>
  </nav>
</body>
</html>
"""

SAMPLE_CONTACT_HTML = """
<html><head><title>お問い合わせ</title></head>
<body><h1>お問い合わせ</h1><form><input name="name"></form></body></html>
"""

SAMPLE_NO_SALES_HTML = """
<html><head><title>お問い合わせ</title></head>
<body>
  <h1>お問い合わせ</h1>
  <p>営業目的のご連絡はご遠慮ください。</p>
  <form><input name="name"></form>
</body></html>
"""


def test_extract_basic_fields():
    pages = {
        "https://sample-denki.co.jp/": SAMPLE_TOP_HTML,
        "https://sample-denki.co.jp/contact/": SAMPLE_CONTACT_HTML,
    }
    info = extract(pages)
    assert info["company_name"] == "株式会社サンプル電気工事"
    assert info["prefecture"] == "東京都"
    assert "新宿区" in info["city"]
    assert info["phone"] == "03-1234-5678"
    assert info["email"] == "info@sample-denki.co.jp"


def test_extract_contact_form_found():
    pages = {
        "https://sample-denki.co.jp/": SAMPLE_TOP_HTML,
        "https://sample-denki.co.jp/contact/": SAMPLE_CONTACT_HTML,
    }
    info = extract(pages)
    assert info["contact_form_found"] is True
    assert "contact" in info["contact_form_url"]


def test_extract_pain_signals():
    pages = {"https://sample-denki.co.jp/": SAMPLE_TOP_HTML}
    info = extract(pages)
    # 「見積」「現場」「教育」「施工事例」などが拾えるはず
    assert "限定的" not in info["pain_signals"]
    assert info["pain_signals"]


def test_extract_detects_works_and_recruit():
    pages = {"https://sample-denki.co.jp/": SAMPLE_TOP_HTML}
    info = extract(pages)
    assert info["_has_works"] is True
    assert info["_has_recruit"] is True


def test_extract_detects_no_sales_phrase():
    pages = {
        "https://x.co.jp/": SAMPLE_TOP_HTML,
        "https://x.co.jp/contact/": SAMPLE_NO_SALES_HTML,
    }
    info = extract(pages)
    assert info["_has_no_sales"] is True


def test_extract_empty_pages():
    assert extract({}) == {}


def test_extract_representative():
    pages = {"https://sample-denki.co.jp/": SAMPLE_TOP_HTML}
    info = extract(pages)
    assert "山田太郎" in info["representative"]
