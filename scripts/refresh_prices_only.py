"""data/prices.json・data/scores.json に既に載っている銘柄の「現在値・前日比」だけを
高頻度に更新するための軽量スクリプト。

ニュース検索・テクニカル指標・PER/PBR等の再計算は行わない(いずれも時間のかかる処理のため)。
株価そのもの(yfinanceのchart API、無料・ブロックされない)だけを取得し直すので数分で終わり、
取引時間中に15分おきなどの高頻度で回しても現実的な処理時間に収まる。

banner役の `scripts/fetch_news_and_score.py` (ニュース・テクニカル・ファンダメンタルズを含む
フル分析)とは役割を分けており、フル分析は1日1回程度、こちらは取引時間中に繰り返し実行する想定。
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from fetch_prices import fetch_all_prices

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PRICES_JSON = DATA_DIR / "prices.json"
SCORES_JSON = DATA_DIR / "scores.json"


def main():
    if not PRICES_JSON.exists():
        print("data/prices.json が見つかりません。先に scripts/run_all.py を実行してください。")
        return

    prices = json.loads(PRICES_JSON.read_text(encoding="utf-8"))
    if not prices:
        print("prices.json に銘柄がありません。")
        return

    print(f"refreshing current price for {len(prices)} stocks ...")
    latest = fetch_all_prices(prices)  # fetch_all_prices は {"code": ...} を持つリストを受け取る

    updated = 0
    for item in prices:
        p = latest.get(item["code"])
        if p:
            item["price"] = p["price"]
            item["change_pct"] = p["change_pct"]
            updated += 1
    PRICES_JSON.write_text(json.dumps(prices, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"updated {updated}/{len(prices)} stocks -> {PRICES_JSON}")

    if SCORES_JSON.exists():
        scores = json.loads(SCORES_JSON.read_text(encoding="utf-8"))
        scores_updated = 0
        for s in scores.get("stocks", []):
            p = latest.get(s["code"])
            if p:
                s["price"] = p["price"]
                s["change_pct"] = p["change_pct"]
                scores_updated += 1
        scores["price_updated_at"] = datetime.now(timezone.utc).isoformat()
        SCORES_JSON.write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"updated {scores_updated}/{len(scores.get('stocks', []))} stocks in {SCORES_JSON}")


if __name__ == "__main__":
    main()
