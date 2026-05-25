"""scorer モジュールのテスト。"""
from src.models import Prospect
from src.scorer import score_prospect


def _good_prospect() -> tuple[Prospect, dict]:
    """営業優先度が高いはずの企業。"""
    p = Prospect(
        prospect_id="p_test1",
        company_name="株式会社テスト電気工事",
        industry_group="建設設備工事",
        sub_industry="電気工事",
        prefecture="東京都",
        city="新宿区",
        website_url="https://test-denki.co.jp",
        contact_form_url="https://test-denki.co.jp/contact",
        contact_form_found=True,
        representative="山田太郎",
        business_summary="電気工事を手がける会社です。",
        pain_signals="見積作成、現場業務、施工事例の整理、新人育成",
    )
    extra = {
        "_has_works": True,
        "_has_recruit": True,
        "_has_no_sales": False,
        "_recruit_only_form": False,
        "_page_count": 5,
    }
    return p, extra


def _weak_prospect() -> tuple[Prospect, dict]:
    """営業対象として弱い企業。"""
    p = Prospect(
        prospect_id="p_test2",
        company_name="無関係な会社",
        industry_group="",
        sub_industry="",
        website_url="https://unrelated.example.com",
        contact_form_found=False,
        business_summary="事業内容の記載を確認できませんでした",
        pain_signals="Web上で確認できる業務課題の手がかりは限定的",
    )
    extra = {
        "_has_works": False,
        "_has_recruit": False,
        "_has_no_sales": False,
        "_recruit_only_form": False,
        "_page_count": 1,
    }
    return p, extra


def test_score_in_valid_range():
    p, extra = _good_prospect()
    score_prospect(p, extra)
    assert 0 <= p.ai_fit_score <= 100


def test_good_prospect_scores_high():
    p, extra = _good_prospect()
    score_prospect(p, extra)
    assert p.ai_fit_score >= 80


def test_weak_prospect_scores_low():
    p, extra = _weak_prospect()
    score_prospect(p, extra)
    assert p.ai_fit_score < 50


def test_good_scores_higher_than_weak():
    good, ge = _good_prospect()
    weak, we = _weak_prospect()
    score_prospect(good, ge)
    score_prospect(weak, we)
    assert good.ai_fit_score > weak.ai_fit_score


def test_no_sales_phrase_lowers_score():
    p, extra = _good_prospect()
    extra["_has_no_sales"] = True
    score_prospect(p, extra)
    # 除外リスク項目が0点になるぶん下がる
    p2, extra2 = _good_prospect()
    score_prospect(p2, extra2)
    assert p.ai_fit_score < p2.ai_fit_score


def test_sales_angle_and_subject_are_filled():
    p, extra = _good_prospect()
    score_prospect(p, extra)
    assert p.sales_angle
    assert p.suggested_subject
    assert p.suggested_opening
    assert p.personalization_note


def test_field_length_limits():
    p, extra = _good_prospect()
    score_prospect(p, extra)
    assert len(p.score_reason) <= 120
    assert len(p.sales_angle) <= 100
    assert len(p.personalization_note) <= 100
    assert len(p.suggested_subject) <= 40
    assert len(p.suggested_opening) <= 160
