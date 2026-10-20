"""価格帯でフィルタ済みの銘柄(data/prices.json)についてGoogleニュースRSS(無料)でニュースを検索し、
発信元の信頼度・見出しの煽り表現・直近の値動きを加味した「上昇期待度」を算出して
data/scores.json に保存する。

上昇期待度はニュース見出しから機械的に算出した参考指標であり、将来の株価を予測・保証するものではない。
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import RAKUTEN_QUOTE_URL, credibility_for_source, is_clickbait, sentiment_for_text

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PRICES_JSON = DATA_DIR / "prices.json"
OUT_JSON = DATA_DIR / "scores.json"

NEWS_LOOKBACK_DAYS = 10
MAX_ARTICLES_PER_STOCK = 12
SLEEP_BETWEEN_REQUESTS = 0.8
DEFAULT_LIMIT = 150  # 1回の実行で深掘りする銘柄数の上限(ニュースソースへの負荷と実行時間を抑えるため)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; jp-stock-screener/1.0; personal use)"}


def fetch_news(query):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "ja", "gl": "JP", "ceid": "JP:ja"}
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)

    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_LOOKBACK_DAYS)
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_raw = item.findtext("pubDate") or ""
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else None
        if not source and " - " in title:
            title, source = title.rsplit(" - ", 1)

        pub_date = None
        try:
            pub_date = datetime.strptime(pub_date_raw, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        if pub_date and pub_date < cutoff:
            continue

        items.append(
            {
                "title": title,
                "link": link,
                "source": source or "不明な発信元",
                "published": pub_date.isoformat() if pub_date else None,
            }
        )
        if len(items) >= MAX_ARTICLES_PER_STOCK:
            break
    return items


def score_stock(stock):
    query = f"{stock['name']} 株価"
    try:
        articles = fetch_news(query)
    except Exception as exc:  # noqa: BLE001
        return {
            "news_count": 0,
            "expectation_pct": 50.0,
            "confidence": "低(ニュース取得失敗)",
            "news": [],
            "error": str(exc),
        }

    weighted_sentiment = 0.0
    weight_sum = 0.0
    credible_positive_sources = set()
    credible_negative_sources = set()
    enriched = []

    for art in articles:
        weight, tier = credibility_for_source(art["source"])
        sentiment = sentiment_for_text(art["title"])
        clickbait = is_clickbait(art["title"])
        fake_news_risk = clickbait and weight < 0.5

        weighted_sentiment += sentiment * weight
        weight_sum += weight
        if weight >= 0.6:
            if sentiment > 0.15:
                credible_positive_sources.add(art["source"])
            elif sentiment < -0.15:
                credible_negative_sources.add(art["source"])

        enriched.append(
            {**art, "credibility_tier": tier, "credibility_weight": weight, "fake_news_risk": fake_news_risk}
        )

    avg_sentiment = weighted_sentiment / weight_sum if weight_sum else 0.0

    corroboration_bonus = 0.0
    if len(credible_positive_sources) >= 2:
        corroboration_bonus += 8
    if len(credible_negative_sources) >= 2:
        corroboration_bonus -= 8

    momentum_component = max(-10.0, min(10.0, stock.get("change_pct", 0.0)))

    expectation = 50 + avg_sentiment * 30 + corroboration_bonus + momentum_component * 0.5
    expectation = max(0.0, min(100.0, expectation))

    avg_weight = weight_sum / len(articles) if articles else 0.0
    if not articles:
        confidence = "低(関連ニュースなし)"
    elif avg_weight >= 0.7:
        confidence = "高"
    elif avg_weight >= 0.45:
        confidence = "中"
    else:
        confidence = "低(未確認情報が中心)"

    return {
        "news_count": len(articles),
        "expectation_pct": round(expectation, 1),
        "confidence": confidence,
        "news": enriched,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="ニュース深掘りする銘柄数の上限。0で無制限(件数が多いと実行時間・検索負荷が増大)",
    )
    args = parser.parse_args()

    stocks = json.loads(PRICES_JSON.read_text(encoding="utf-8"))
    # 値動きが大きい(=材料が出ている可能性が高い)銘柄を優先してニュースを深掘りする
    stocks.sort(key=lambda s: abs(s.get("change_pct", 0.0)), reverse=True)
    if args.limit:
        stocks = stocks[: args.limit]

    results = []
    for i, stock in enumerate(stocks, 1):
        info = score_stock(stock)
        results.append({**stock, **info, "rakuten_url": RAKUTEN_QUOTE_URL.format(code=stock["code"])})
        print(f"[{i}/{len(stocks)}] {stock['code']} {stock['name']}: {info['expectation_pct']}%")
        time.sleep(SLEEP_BETWEEN_REQUESTS)

    results.sort(key=lambda r: r["expectation_pct"], reverse=True)
    OUT_JSON.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "disclaimer": (
                    "本スコアはニュース見出し等から機械的に算出した参考指標であり、"
                    "投資助言ではありません。将来の株価を保証するものではなく、"
                    "最終判断および楽天証券での取扱い確認はご自身で行ってください。"
                ),
                "stocks": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"scores: {len(results)} stocks -> {OUT_JSON}")


if __name__ == "__main__":
    main()
