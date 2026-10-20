"""東証(JPX)の上場銘柄一覧(data_j.xlsx、公式・無料)を取得し、
国内株式のみを data/universe.json に保存する。月1回程度の実行で十分。"""
import json
from pathlib import Path

import pandas as pd
import requests

JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_XLSX = DATA_DIR / "data_j.xlsx"
OUT_JSON = DATA_DIR / "universe.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; jp-stock-screener/1.0; personal use)"}


def download():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    resp = requests.get(JPX_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    RAW_XLSX.write_bytes(resp.content)


def build_universe():
    df = pd.read_excel(RAW_XLSX)
    df.columns = [str(c).strip() for c in df.columns]

    code_col = next(c for c in df.columns if "コード" in c and "業種" not in c and "規模" not in c)
    name_col = next(c for c in df.columns if "銘柄名" in c)
    market_col = next(c for c in df.columns if "市場" in c)
    sector_col = next((c for c in df.columns if c.startswith("33業種区分")), None)

    records = []
    for _, row in df.iterrows():
        market = str(row.get(market_col, "")).strip()
        if "内国株式" not in market:
            continue
        code = row.get(code_col)
        if pd.isna(code):
            continue
        code = str(code).strip()
        if code.endswith(".0"):
            code = code[:-2]
        name = str(row.get(name_col, "")).strip()
        sector = str(row.get(sector_col, "")).strip() if sector_col else ""
        records.append({"code": code, "name": name, "market": market, "sector": sector})

    OUT_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"universe: {len(records)} domestic stocks -> {OUT_JSON}")


if __name__ == "__main__":
    download()
    build_universe()
