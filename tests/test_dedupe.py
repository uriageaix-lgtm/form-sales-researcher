"""dedupe モジュールのテスト。"""
from src.dedupe import (
    dedupe_search_results, is_excluded_domain, make_prospect_id,
    normalize_company_name, normalize_domain,
)
from src.models import SearchResult


def test_normalize_domain_strips_scheme_and_www():
    assert normalize_domain("https://www.Example.co.jp/contact") == "example.co.jp"
    assert normalize_domain("http://example.co.jp") == "example.co.jp"
    assert normalize_domain("example.co.jp/page") == "example.co.jp"


def test_normalize_domain_strips_port_and_auth():
    assert normalize_domain("https://example.com:8080/x") == "example.com"
    assert normalize_domain("https://user@example.com/x") == "example.com"


def test_normalize_domain_empty():
    assert normalize_domain("") == ""


def test_make_prospect_id_is_stable():
    # 同じドメインなら表記が違っても同じIDになる
    a = make_prospect_id("https://www.example.co.jp/contact")
    b = make_prospect_id("http://example.co.jp/")
    assert a == b
    assert a.startswith("p_")


def test_make_prospect_id_differs_by_domain():
    assert make_prospect_id("https://a.com") != make_prospect_id("https://b.com")


def test_normalize_company_name_removes_legal_tokens():
    assert normalize_company_name("株式会社サンプル") == "サンプル"
    assert normalize_company_name("サンプル（株）") == "サンプル"
    assert normalize_company_name("Sample Co., Ltd.") == "sample"


def test_is_excluded_domain_matches_subdomain():
    excluded = ["facebook.com", "indeed.com"]
    assert is_excluded_domain("https://ja-jp.facebook.com/foo", excluded) is True
    assert is_excluded_domain("https://jp.indeed.com/xyz", excluded) is True
    assert is_excluded_domain("https://example.co.jp", excluded) is False


def test_dedupe_removes_same_domain():
    results = [
        SearchResult(title="A社", url="https://a.co.jp/"),
        SearchResult(title="A社 別ページ", url="https://a.co.jp/contact"),
        SearchResult(title="B社", url="https://b.co.jp/"),
    ]
    kept, dropped = dedupe_search_results(results)
    assert len(kept) == 2
    assert len(dropped) == 1


def test_dedupe_removes_same_company_name():
    results = [
        SearchResult(title="株式会社サンプル", url="https://sample1.co.jp/"),
        SearchResult(title="サンプル（株）", url="https://sample2.co.jp/"),
    ]
    kept, dropped = dedupe_search_results(results)
    assert len(kept) == 1
    assert len(dropped) == 1


def test_dedupe_drops_invalid_url():
    results = [SearchResult(title="X社", url="")]
    kept, dropped = dedupe_search_results(results)
    assert len(kept) == 0
    assert len(dropped) == 1
