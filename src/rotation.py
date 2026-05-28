"""都道府県の自動切り替え（ローテーション）。

「今日は何県を調べるか」を、日付をもとに自動で決める。
北海道 → 青森県 → … と1日ずつ進み、最後まで行ったら先頭に戻る。

これにより、毎日 config.yaml を手で書き換えなくても、
実行されるたびに対象の県が自動で切り替わる。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

# 47都道府県（北から南の順）。ローテーションはこの順で進む。
ALL_PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]

# ローテーションの起点となる日。この日が rotation_list の先頭にあたる。
_EPOCH = date(2026, 1, 1)


def pick_prefecture_for_today(
    rotation_list: list[str],
    today: date | None = None,
) -> str:
    """日付をもとに、今日調べる都道府県を1つ返す。

    起点日(_EPOCH)からの経過日数を rotation_list の長さで割った余りで、
    リストの何番目かを決める。1日進むごとに次の県へ移り、
    最後まで行くと自動的に先頭へ戻る。

    Args:
        rotation_list: 巡回する都道府県のリスト。
        today: 基準にする日付。省略時は実行日(UTC)。

    Returns:
        今日の対象となる都道府県名。

    Raises:
        ValueError: rotation_list が空のとき。
    """
    if not rotation_list:
        raise ValueError("ローテーション対象の都道府県リストが空です。")
    if today is None:
        today = datetime.now(timezone.utc).date()
    days_elapsed = (today - _EPOCH).days
    index = days_elapsed % len(rotation_list)
    return rotation_list[index]


def resolve_rotation_list(config_value) -> list[str]:
    """config.yaml の rotation 設定を、実際の都道府県リストに変換する。

    config_value が次のいずれの形でも受け付ける:
      - "all" という文字列 → 47都道府県すべて
      - 都道府県名のリスト → そのリストをそのまま使う
      - 空 / None → 47都道府県すべて（既定）

    Returns:
        巡回対象の都道府県リスト。
    """
    if config_value is None or config_value == "":
        return list(ALL_PREFECTURES)
    if isinstance(config_value, str):
        if config_value.strip().lower() == "all":
            return list(ALL_PREFECTURES)
        # 単一の県名が文字列で入っていた場合
        return [config_value.strip()]
    if isinstance(config_value, list):
        cleaned = [str(x).strip() for x in config_value if str(x).strip()]
        return cleaned or list(ALL_PREFECTURES)
    return list(ALL_PREFECTURES)
