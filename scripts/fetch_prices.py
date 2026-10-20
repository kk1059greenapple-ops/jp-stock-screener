"""data/universe.json の銘柄について yfinance(無料・APIキー不要)で直近株価を取得し、
指定した価格帯に収まる銘柄を data/prices.json に保存する。"""
import argparse
import json
import time
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
UNIVERSE_JSON = DATA_DIR / "universe.json"
OUT_JSON = DATA_DIR / "prices.json"

CHUNK_SIZE = 150
SLEEP_BETWEEN_CHUNKS = 1.5


def load_universe():
    return json.loads(UNIVERSE_JSON.read_text(encoding="utf-8"))


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def fetch_all_prices(universe):
    codes = [item["code"] for item in universe]
    tickers = [f"{code}.T" for code in codes]
    results = {}

    for batch in chunked(tickers, CHUNK_SIZE):
        try:
            data = yf.download(
                tickers=" ".join(batch),
                period="5d",
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=False,
            )
        except Exception as exc:  # noqa: BLE001 - ネットワーク取得は多様な理由で失敗しうる
            print(f"batch failed: {exc}")
            continue

        multi = len(batch) > 1
        for ticker in batch:
            code = ticker[:-2]
            try:
                closes = data[ticker]["Close"].dropna() if multi else data["Close"].dropna()
            except Exception:
                continue
            if closes.empty:
                continue
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) > 1 else last
            change_pct = (last - prev) / prev * 100 if prev else 0.0
            results[code] = {"price": round(last, 1), "change_pct": round(change_pct, 2)}

        time.sleep(SLEEP_BETWEEN_CHUNKS)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-price", type=float, default=0)
    parser.add_argument("--max-price", type=float, default=float("inf"))
    args = parser.parse_args()

    universe = load_universe()
    prices = fetch_all_prices(universe)

    merged = []
    for item in universe:
        p = prices.get(item["code"])
        if not p:
            continue
        if not (args.min_price <= p["price"] <= args.max_price):
            continue
        merged.append({**item, **p})

    merged.sort(key=lambda r: r["price"])
    OUT_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"prices: {len(merged)} stocks in [{args.min_price}, {args.max_price}] -> {OUT_JSON}")


if __name__ == "__main__":
    main()
