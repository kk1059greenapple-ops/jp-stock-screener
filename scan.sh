#!/usr/bin/env bash
# 価格帯を指定してローカルから「深掘りスキャン」を実行し、結果をページ表示用にコピーするワンコマンド。
# PER/PBR・セクター相対評価・決算発表日はこのスクリプト(自宅PCのIP)からのみ確実に取得できる。
# (GitHub Actions上の自動実行では、Yahoo Finance/株探の両方がクラウド実行環境のIPを
#  ブロックするため、これらの項目は空欄になる。ニュース分析・テクニカル指標は自動実行でも動く)
#
# 使い方:
#   ./scan.sh 1000 3000       # 株価1000円〜3000円で上位10件を深掘り
#   ./scan.sh 1000 3000 20    # 件数を20件に変更
set -e
cd "$(dirname "$0")"

MIN=${1:-0}
MAX=${2:-100000}
LIMIT=${3:-10}

if [ -d .venv ]; then
  source .venv/bin/activate
fi

python scripts/run_all.py --min-price "$MIN" --max-price "$MAX" --limit "$LIMIT"

mkdir -p docs/data
cp data/universe.json data/prices.json data/scores.json docs/data/

echo ""
echo "完了しました。結果を確認するには:"
echo "  cd docs && python3 -m http.server 8000"
echo "  ブラウザで http://localhost:8000 を開く"
echo ""
echo "この結果をスマホでも見られるようにしたい場合は、変更をコミットしてpushしてください:"
echo "  git add data docs/data && git commit -m 'local scan' && git push"
