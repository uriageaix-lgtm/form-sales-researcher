"""クロールしたHTMLから企業情報を抽出する。

抽出対象: 会社名、所在地、電話、メール、事業内容、問い合わせフォームURL、
採用・施工事例の有無、営業禁止表記の有無 など。

公式サイトに書かれた事実だけを拾う方針。推測は最小限にする。
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# 47都道府県
PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]

# 問い合わせフォームへのリンクを示すアンカーテキスト／URLパス
CONTACT_HINTS = [
    "お問い合わせ", "問い合わせ", "問合せ", "お問合せ", "コンタクト",
    "contact", "inquiry", "お見積", "見積", "お見積り", "見積もり",
    "ご相談", "相談", "資料請求", "quote", "form", "otoiawase",
]
# 採用専用フォームを示す語（営業導線として不適切なのでフラグ化）
RECRUIT_HINTS = ["採用", "求人", "recruit", "entry", "応募", "エントリー"]

# 電話番号（日本の固定・携帯・フリーダイヤルにざっくり対応）
PHONE_RE = re.compile(r"0\d{1,4}[-(]?\d{1,4}[-)]?\d{3,4}")
# メールアドレス
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# 郵便番号つき住所の手がかり
POSTAL_RE = re.compile(r"〒?\s*\d{3}-\d{4}")

# 営業目的の連絡を断る表記
NO_SALES_PHRASES = [
    "営業目的", "営業のご連絡", "営業の連絡", "セールス", "勧誘",
    "営業お断り", "営業はお断り", "売り込み", "営業メールお断り",
]

# 課題の兆候を示すキーワード（pain_signals 用）。業種共通で広めに拾う。
PAIN_KEYWORDS = {
    "見積": "見積作成",
    "御見積": "見積作成",
    "提案": "提案書作成",
    "現場": "現場業務",
    "施工事例": "施工事例の整理",
    "施工実績": "施工実績の整理",
    "報告書": "報告書作成",
    "受発注": "受発注処理",
    "発注": "受発注処理",
    "請求": "請求書処理",
    "マニュアル": "マニュアル整備",
    "教育": "社員教育",
    "研修": "社員教育",
    "新人": "新人育成",
    "職人": "職人ノウハウの継承",
    "採用": "採用・人手不足",
    "求人": "採用・人手不足",
    "人手不足": "採用・人手不足",
    "在庫": "在庫・商品情報管理",
    "FAX": "FAX・電話対応",
}


def _visible_text(soup: BeautifulSoup) -> str:
    """スクリプト等を除いた表示テキストを返す。"""
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


# 会社名として不適切な「ページ見出し」っぽい語（これらは会社名ではない）
_NOT_A_COMPANY_NAME = [
    "会社概要", "会社案内", "企業情報", "会社情報", "概要", "about",
    "ごあいさつ", "ご挨拶", "代表挨拶", "代表者挨拶", "トップページ",
    "ホーム", "home", "お問い合わせ", "問い合わせ", "contact",
    "事業内容", "サービス", "service", "アクセス", "採用情報", "採用",
    "とは", "について", "メニュー", "menu", "申請書ダウンロード",
    "詳細", "一覧", "プライバシーポリシー",
]


def _looks_like_heading(text: str) -> bool:
    """その文字列が「会社名」ではなく「ページ見出し」っぽいか判定する。"""
    if not text:
        return True
    t = text.strip()
    # 完全一致、または「〇〇とは」「〇〇について」のような見出し表現
    for ng in _NOT_A_COMPANY_NAME:
        if t == ng or t.endswith(ng):
            return True
    return False


def _extract_company_name(pages: dict, fallback: str = "") -> str:
    """会社名を推定する。og:site_name → titleタグ → h1 の順。

    「会社概要」「会社案内」などのページ見出しは会社名ではないので採用しない。
    """
    candidates: list[str] = []

    # 候補1: og:site_name（最も信頼できる）
    for url, html in pages.items():
        soup = BeautifulSoup(html, "lxml")
        og = soup.find("meta", attrs={"property": "og:site_name"})
        if og and og.get("content"):
            candidates.append(og["content"].strip())
            break

    # 候補2: title タグ（区切り文字より前）
    for url, html in pages.items():
        soup = BeautifulSoup(html, "lxml")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            for sep in ("|", "｜", "-", "‐", "—", "–", "／", "/"):
                if sep in title:
                    # 区切りで分けた各部分のうち、見出しでない最初のものを使う
                    parts = [pp.strip() for pp in title.replace("｜", "|").split("|")]
                    parts = [pp for seg in parts for pp in seg.split(sep)]
                    for part in parts:
                        if part and not _looks_like_heading(part):
                            candidates.append(part)
                            break
                    break
            else:
                if title:
                    candidates.append(title)
            break

    # 候補3: h1
    for url, html in pages.items():
        soup = BeautifulSoup(html, "lxml")
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            candidates.append(h1.get_text(strip=True))
            break

    # 見出しっぽくない最初の候補を会社名とする
    for c in candidates:
        if not _looks_like_heading(c):
            return c
    # どれも見出しっぽいなら、フォールバック（検索結果のタイトル）を使う
    if fallback and not _looks_like_heading(fallback):
        return fallback
    return candidates[0] if candidates else fallback


def _extract_address(text: str) -> tuple[str, str, str]:
    """テキストから (住所, 都道府県, 市区町村) を推定する。"""
    prefecture = ""
    for pref in PREFECTURES:
        if pref in text:
            prefecture = pref
            break

    address = ""
    m = POSTAL_RE.search(text)
    if m:
        # 郵便番号の直後 ~40文字程度を住所候補とする
        start = m.start()
        snippet = text[start:start + 60]
        address = re.sub(r"\s+", " ", snippet).strip()
    elif prefecture:
        idx = text.find(prefecture)
        address = re.sub(r"\s+", " ", text[idx:idx + 50]).strip()

    city = ""
    if prefecture and address:
        after = address.split(prefecture, 1)[-1]
        cm = re.search(r"^[\u4e00-\u9fff\u3040-\u30ffA-Za-z0-9]+?[市区町村]", after)
        if cm:
            city = cm.group(0)

    return address, prefecture, city


def _find_contact_form(pages: dict) -> tuple[str, bool, bool]:
    """問い合わせフォームURLを探す。

    Returns:
        (contact_form_url, contact_form_found, recruit_only)
        recruit_only: 採用応募フォームしか見つからない場合 True
    """
    contact_candidates: list[str] = []
    recruit_candidates: list[str] = []

    for page_url, html in pages.items():
        soup = BeautifulSoup(html, "lxml")
        base_domain = urlparse(page_url).netloc

        # このページ自体が問い合わせ系URLかどうか
        low_url = page_url.lower()
        if any(h.lower() in low_url for h in CONTACT_HINTS):
            if soup.find("form") or "form" in low_url:
                if any(h.lower() in low_url for h in RECRUIT_HINTS):
                    recruit_candidates.append(page_url)
                else:
                    contact_candidates.append(page_url)

        # ページ内のリンクを調べる
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            abs_url = urljoin(page_url, href).split("#")[0]
            if urlparse(abs_url).netloc != base_domain:
                continue
            anchor = (a.get_text() or "").lower()
            target = anchor + " " + abs_url.lower()

            is_contact = any(h.lower() in target for h in CONTACT_HINTS)
            is_recruit = any(h.lower() in target for h in RECRUIT_HINTS)
            if is_contact and is_recruit:
                recruit_candidates.append(abs_url)
            elif is_contact:
                contact_candidates.append(abs_url)

    if contact_candidates:
        # フォーム専用ページらしいURL（contact/inquiry/form を含む）を優先
        for url in contact_candidates:
            if any(k in url.lower() for k in ("contact", "inquiry", "form", "otoiawase")):
                return url, True, False
        return contact_candidates[0], True, False

    if recruit_candidates:
        return recruit_candidates[0], True, True

    return "", False, False


def _detect_pain_signals(text: str) -> str:
    """テキスト中の課題キーワードから pain_signals を組み立てる。"""
    found: list[str] = []
    for keyword, label in PAIN_KEYWORDS.items():
        if keyword in text and label not in found:
            found.append(label)
    if not found:
        return "Web上で確認できる業務課題の手がかりは限定的"
    return "、".join(found[:6])


def _build_summary(pages: dict) -> str:
    """事業内容の要約を作る（meta description 優先、無ければ本文先頭）。"""
    for url, html in pages.items():
        soup = BeautifulSoup(html, "lxml")
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            content = desc["content"].strip()
            if len(content) >= 20:
                return content[:120]
    # フォールバック: トップページ本文の先頭
    first_html = next(iter(pages.values()), "")
    if first_html:
        text = _visible_text(BeautifulSoup(first_html, "lxml"))
        return text[:120] if text else "事業内容の記載を確認できませんでした"
    return "事業内容の記載を確認できませんでした"


def extract(pages: dict, fallback_name: str = "") -> dict:
    """クロール結果（{url: html}）から企業情報の辞書を返す。

    返す辞書のキーは Prospect のフィールド名に対応する。
    """
    if not pages:
        return {}

    all_text = " ".join(
        _visible_text(BeautifulSoup(html, "lxml")) for html in pages.values()
    )

    company_name = _extract_company_name(pages, fallback_name)
    address, prefecture, city = _extract_address(all_text)
    contact_form_url, contact_form_found, recruit_only = _find_contact_form(pages)

    # 電話・メール（最初に見つかったもの。example系メールは除外）
    phone = ""
    pm = PHONE_RE.search(all_text)
    if pm:
        phone = pm.group(0)

    email = ""
    for em in EMAIL_RE.finditer(all_text):
        candidate = em.group(0)
        if not any(bad in candidate.lower() for bad in
                   ("example.", "sentry.", "@2x", ".png", ".jpg")):
            email = candidate
            break

    # 代表者名
    representative = ""
    rep_m = re.search(r"代表(?:取締役)?(?:社長)?[\s:：]*([\u4e00-\u9fff]{2,5}\s?[\u4e00-\u9fff]{1,5})",
                       all_text)
    if rep_m:
        representative = rep_m.group(1).strip()

    has_works = any(k in all_text for k in ("施工事例", "施工実績", "導入事例", "実績紹介"))
    has_recruit = any(k in all_text for k in ("採用情報", "求人", "新卒", "中途採用"))
    has_no_sales = any(p in all_text for p in NO_SALES_PHRASES)

    pain_signals = _detect_pain_signals(all_text)
    business_summary = _build_summary(pages)

    return {
        "company_name": company_name,
        "address": address,
        "prefecture": prefecture,
        "city": city,
        "contact_form_url": contact_form_url,
        "contact_form_found": contact_form_found,
        "phone": phone,
        "email": email,
        "representative": representative,
        "business_summary": business_summary,
        "pain_signals": pain_signals,
        "source_urls": ",".join(list(pages.keys())[:10]),
        # スコアリング・除外判定に使う中間情報
        "_has_works": has_works,
        "_has_recruit": has_recruit,
        "_has_no_sales": has_no_sales,
        "_recruit_only_form": recruit_only,
        "_page_count": len(pages),
    }
