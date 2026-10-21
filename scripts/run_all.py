"""価格帯を指定して universe → prices → news/score を一括実行するエントリポイント。

例:
    python scripts/run_all.py --min-price 1000 --max-price 3000
"""
import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent


def run(cmd):
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-price", type=float, default=0)
    parser.add_argument("--max-price", type=float, default=100000)
    parser.add_argument("--skip-universe", action="store_true", help="data_j.xlsx の再取得をスキップ(既に取得済みの場合)")
    parser.add_argument("--limit", type=int, default=1000, help="ニュース深掘りする銘柄数の上限(0で無制限)")
    args = parser.parse_args()

    py = sys.executable
    if not args.skip_universe:
        run([py, str(SCRIPTS_DIR / "update_universe.py")])

    run(
        [
            py,
            str(SCRIPTS_DIR / "fetch_prices.py"),
            "--min-price",
            str(args.min_price),
            "--max-price",
            str(args.max_price),
        ]
    )

    run([py, str(SCRIPTS_DIR / "fetch_news_and_score.py"), "--limit", str(args.limit)])


if __name__ == "__main__":
    main()
