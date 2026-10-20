"""ニュースソースの信頼度判定・フェイクニュース疑い検知・簡易センチメント分析のための共通ロジック。"""
import re

RAKUTEN_QUOTE_URL = "https://www.rakuten-sec.co.jp/web/market/search/quote.html?ric={code}.T"

# 情報の出所に応じた信頼度の重み。値が高いほど一次情報・大手報道機関に近い。
_TIER_A = {
    "日本経済新聞", "日経新聞", "Nikkei", "NHK", "ロイター", "Reuters", "共同通信",
    "時事通信", "Bloomberg", "ブルームバーグ", "適時開示", "東京証券取引所",
}
_TIER_B = {
    "朝日新聞", "読売新聞", "毎日新聞", "産経新聞", "東洋経済オンライン", "東洋経済",
    "ダイヤモンド・オンライン", "ダイヤモンドオンライン", "日刊工業新聞", "株探",
    "Kabutan", "モーニングスター", "FISCO", "会社四季報オンライン", "ITmedia",
    "共同通信社",
}
_TIER_C = {
    "みんかぶ", "Yahoo!ニュース", "Yahoo!ファイナンス", "excite", "livedoor",
}

_CLICKBAIT_PATTERNS = [
    r"【衝撃】", r"絶対", r"確実に?急騰", r"テンバガー確定", r"100%", r"爆上げ確定",
    r"!!+", r"！！+", r"今すぐ買え", r"知らないと損", r"大暴騰", r"仕手",
]

_POSITIVE_WORDS = [
    "上方修正", "増配", "自社株買い", "最高益", "黒字転換", "増収増益", "受注拡大",
    "業績好調", "提携", "新製品", "株価上昇", "買収提案", "割安", "決算好感",
    "増益", "好決算", "最高値更新",
]
_NEGATIVE_WORDS = [
    "下方修正", "減配", "赤字", "不祥事", "粉飾", "訴訟", "リコール", "自主回収",
    "架空取引", "経営破綻", "民事再生", "上場廃止", "内部統制不備", "業績悪化",
    "株価下落", "減益", "特別損失", "検査不正",
]

_CLICKBAIT_RE = re.compile("|".join(_CLICKBAIT_PATTERNS))


def credibility_for_source(source_name: str):
    """ニュースの発信元から信頼度の重み(0-1)とラベルを返す。"""
    name = (source_name or "").strip()
    for s in _TIER_A:
        if s in name:
            return 0.95, "高(主要通信社・公式開示)"
    for s in _TIER_B:
        if s in name:
            return 0.7, "中〜高(大手報道・専門メディア)"
    for s in _TIER_C:
        if s in name:
            return 0.4, "中(集約サイト・個人寄稿含む)"
    return 0.2, "低(発信元未確認)"


def is_clickbait(title: str) -> bool:
    return bool(_CLICKBAIT_RE.search(title or ""))


def sentiment_for_text(text: str) -> float:
    """見出しに含まれる好悪材料キーワードから -1〜1 のセンチメントを返す。"""
    text = text or ""
    pos = sum(text.count(w) for w in _POSITIVE_WORDS)
    neg = sum(text.count(w) for w in _NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total
