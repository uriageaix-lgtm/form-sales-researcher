"""スコアリングと営業切り口の生成。

ai_fit_score（AI研修・AI定着支援サービスとの相性）を100点満点で算出する。
仕様書の6項目に沿ったルールベース実装。LLMは use_llm=true のとき将来差し込む。
"""
from __future__ import annotations

from .models import Prospect

# 業種グループ別の営業切り口テンプレート
SALES_ANGLES: dict[str, str] = {
    "建設設備工事": (
        "見積作成・現場報告・施工写真整理・安全書類づくり・若手や職人への教育を、"
        "AI活用で標準化し、事務と現場の手間を同時に減らせます。"
    ),
    "リフォーム": (
        "現地調査後の提案書・見積作成、施工事例ページの活用、チラシ等の販促、"
        "問い合わせ後の追客スピードをAIで底上げできます。"
    ),
    "工務店": (
        "顧客ヒアリングの整理、住宅提案資料や仕様説明の作成、施工事例の活用、"
        "OB顧客対応や社内ノウハウの標準化をAIで支援できます。"
    ),
    "卸売業": (
        "受発注処理・見積対応・請求書処理・商品情報の整理・営業資料作成、"
        "電話/FAX/メール対応の効率化をAIでまとめて改善できます。"
    ),
}

# 業種グループ別の件名案
SUBJECTS: dict[str, str] = {
    "建設設備工事": "見積・現場報告のAI効率化についてのご提案",
    "リフォーム": "提案書作成と追客のAI活用についてのご相談",
    "工務店": "住宅提案資料づくりのAI活用についてのご提案",
    "卸売業": "受発注・請求処理のAI効率化についてのご提案",
}

DEFAULT_ANGLE = (
    "見積・提案書・現場報告・請求処理などの定型業務をAI活用で効率化し、"
    "中小企業の人手不足を補う研修・定着支援をご提案できます。"
)


def _score_industry_fit(prospect: Prospect) -> tuple[int, str]:
    """業種適合（最大25点）。"""
    if prospect.industry_group in SALES_ANGLES:
        if prospect.sub_industry:
            return 25, "対象4業種に該当し、AI研修の訴求と業務課題が近い"
        return 22, "対象4業種に該当"
    return 8, "対象4業種への該当が明確でない"


def _score_pain(prospect: Prospect) -> tuple[int, str]:
    """現場・営業・事務の複合課題（最大20点）。"""
    signals = [s for s in prospect.pain_signals.split("、") if s]
    weak = "確認できる" in prospect.pain_signals and "限定的" in prospect.pain_signals
    if weak or not signals:
        return 5, "課題の手がかりがWeb上で限定的"
    if len(signals) >= 3:
        return 20, f"複数の業務課題が読み取れる（{len(signals)}件）"
    if len(signals) == 2:
        return 14, "業務課題の手がかりが2件確認できる"
    return 9, "業務課題の手がかりが1件確認できる"


def _score_sme_fit(extra: dict) -> tuple[int, str]:
    """中小企業適合（最大15点）。

    従業員数が取れないことが多いため、ページ規模や採用情報の有無から推定する。
    """
    page_count = extra.get("_page_count", 0)
    has_recruit = extra.get("_has_recruit", False)
    # ページ数が極端に多い＝大企業の可能性、と緩く推定
    if page_count >= 7 and has_recruit:
        return 12, "一定規模の組織だが中小企業の範囲内と推定"
    if has_recruit:
        return 15, "採用活動があり、中小企業として人手不足課題がありそう"
    return 11, "規模は不明だが地域企業として中小企業の可能性が高い"


def _score_contactability(prospect: Prospect, extra: dict) -> tuple[int, str]:
    """問い合わせ可能性（最大15点）。"""
    if extra.get("_recruit_only_form"):
        return 4, "採用応募フォームのみで営業導線が不明確"
    if prospect.contact_form_found:
        return 15, "問い合わせフォームがあり営業連絡の導線が明確"
    if prospect.phone or prospect.email:
        return 8, "フォームは未確認だが電話/メールの連絡先がある"
    return 2, "問い合わせ導線が確認できない"


def _score_personalization(prospect: Prospect, extra: dict) -> tuple[int, str]:
    """パーソナライズ可能性（最大15点）。"""
    materials = 0
    if extra.get("_has_works"):
        materials += 1
    if extra.get("_has_recruit"):
        materials += 1
    if prospect.representative:
        materials += 1
    if prospect.business_summary and "確認できませんでした" not in prospect.business_summary:
        materials += 1
    if materials >= 2:
        return 15, "施工事例・採用情報・代表メッセージ等の個別化材料がある"
    if materials == 1:
        return 9, "個別化に使える材料が一部ある"
    return 3, "営業文を個別化できる材料が乏しい"


def _score_low_risk(extra: dict) -> tuple[int, str]:
    """除外リスクの低さ（最大10点）。"""
    if extra.get("_has_no_sales"):
        return 0, "営業目的の連絡を断る旨の記載がある"
    if extra.get("_recruit_only_form"):
        return 3, "採用専用フォームのみで営業対象として不向きの可能性"
    return 10, "営業対象として明確な除外リスクは見当たらない"


def score_prospect(prospect: Prospect, extra: dict, high_priority: int = 80) -> Prospect:
    """Prospect にスコアと営業切り口を書き込んで返す。

    Args:
        prospect: 抽出済みのProspect（スコア未設定）。
        extra: extractor が返す中間情報（_has_works など）。
        high_priority: 最優先とみなす閾値。
    """
    parts = [
        _score_industry_fit(prospect),
        _score_pain(prospect),
        _score_sme_fit(extra),
        _score_contactability(prospect, extra),
        _score_personalization(prospect, extra),
        _score_low_risk(extra),
    ]
    total = sum(p[0] for p in parts)
    reasons = "／".join(p[1] for p in parts if p[1])

    prospect.ai_fit_score = total
    prospect.score_reason = reasons[:120]

    # 営業切り口・件名・冒頭文
    angle = SALES_ANGLES.get(prospect.industry_group, DEFAULT_ANGLE)
    prospect.sales_angle = angle[:100]
    prospect.suggested_subject = SUBJECTS.get(
        prospect.industry_group, "業務効率化のためのAI活用についてのご提案"
    )[:40]

    prospect.personalization_note = _build_personalization(prospect, extra)[:100]
    prospect.suggested_opening = _build_opening(prospect)[:160]

    return prospect


def _build_personalization(prospect: Prospect, extra: dict) -> str:
    """フォーム営業の冒頭に使える個別メモを作る。"""
    bits: list[str] = []
    if prospect.prefecture:
        area = prospect.prefecture + (prospect.city or "")
        bits.append(f"{area}を中心に事業を展開")
    if prospect.sub_industry:
        bits.append(f"{prospect.sub_industry}に取り組む")
    if extra.get("_has_works"):
        bits.append("施工事例・実績をサイトで公開")
    if extra.get("_has_recruit"):
        bits.append("採用にも力を入れている")
    if not bits:
        return "公式サイトの事業内容を踏まえて文面を個別化すること"
    return "、".join(bits) + "点に触れると自然な書き出しになる"


def _build_opening(prospect: Prospect) -> str:
    """問い合わせフォーム本文の冒頭案を作る。"""
    name = prospect.company_name or "御社"
    area = (prospect.prefecture or "") + (prospect.city or "")
    sub = prospect.sub_industry or "事業"
    area_phrase = f"{area}で" if area else ""
    return (
        f"突然のご連絡失礼いたします。{area_phrase}{sub}に取り組まれている"
        f"{name}様のサイトを拝見し、ご連絡いたしました。"
        f"中小企業向けのAI研修・定着支援を行っており、見積や提案書、現場報告などの"
        f"業務効率化でお役に立てればと考えております。"
    )
