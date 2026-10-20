"""株価の時系列データ(直近1年、yfinance=無料・Yahoo Financeベース)から、
ニュースに依存しない客観的なテクニカル指標・ファンダメンタルズ指標を算出する。

取引所の実際の値動きそのものに基づくため、ニュース見出しの解析よりも裏付けの確実な
補助情報として扱い、上昇期待度に加点・減点する。
"""
import time

import pandas as pd
import yfinance as yf

NIKKEI_TICKER = "^N225"
HISTORY_CHUNK_SIZE = 100
SLEEP_BETWEEN_HISTORY_CHUNKS = 1.5
SLEEP_BETWEEN_INFO_CALLS = 0.3


def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _rsi(closes: pd.Series, period: int = 14):
    delta = closes.diff().dropna()
    if len(delta) < period:
        return None
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def fetch_price_history(codes):
    """銘柄コード一覧(+日経平均)について直近1年の日足終値を取得する。"""
    tickers = [f"{c}.T" for c in codes] + [NIKKEI_TICKER]
    history = {}
    for batch in _chunked(tickers, HISTORY_CHUNK_SIZE):
        try:
            data = yf.download(
                tickers=" ".join(batch),
                period="1y",
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=False,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"history batch failed: {exc}")
            continue

        multi = len(batch) > 1
        for ticker in batch:
            try:
                closes = data[ticker]["Close"].dropna() if multi else data["Close"].dropna()
            except Exception:
                continue
            if len(closes) >= 20:
                history[ticker] = closes
        time.sleep(SLEEP_BETWEEN_HISTORY_CHUNKS)

    return history


def technical_factors_for(closes: pd.Series, nikkei_closes):
    """移動平均・RSI・52週レンジ・騰落率など、価格データのみから計算できる客観指標。"""
    if closes is None or len(closes) < 20:
        return None

    price = float(closes.iloc[-1])
    sma25 = float(closes.tail(25).mean()) if len(closes) >= 25 else None
    sma75 = float(closes.tail(75).mean()) if len(closes) >= 75 else None
    rsi14 = _rsi(closes)

    window = closes.tail(252)
    high52 = float(window.max())
    low52 = float(window.min())
    range_pos = (price - low52) / (high52 - low52) if high52 > low52 else 0.5

    def pct_change(days):
        if len(closes) <= days:
            return None
        base = float(closes.iloc[-days - 1])
        return (price - base) / base * 100 if base else None

    change_1m = pct_change(20)
    change_3m = pct_change(60)

    trend_signal = 0
    if sma25 is not None and sma75 is not None:
        if price > sma25 > sma75:
            trend_signal = 1
        elif price < sma25 < sma75:
            trend_signal = -1

    rel_strength_1m = None
    if nikkei_closes is not None and len(nikkei_closes) > 20 and change_1m is not None:
        nk_price = float(nikkei_closes.iloc[-1])
        nk_base = float(nikkei_closes.iloc[-21])
        if nk_base:
            nk_change = (nk_price - nk_base) / nk_base * 100
            rel_strength_1m = round(change_1m - nk_change, 2)

    return {
        "sma25": round(sma25, 1) if sma25 is not None else None,
        "sma75": round(sma75, 1) if sma75 is not None else None,
        "rsi14": round(rsi14, 1) if rsi14 is not None else None,
        "trend_signal": trend_signal,
        "range_pos_52w": round(range_pos, 3),
        "high_52w": round(high52, 1),
        "low_52w": round(low52, 1),
        "change_1m_pct": round(change_1m, 2) if change_1m is not None else None,
        "change_3m_pct": round(change_3m, 2) if change_3m is not None else None,
        "relative_strength_1m_vs_nikkei": rel_strength_1m,
    }


def technical_score(tf):
    """テクニカル指標から -1〜1 のスコアと、判断根拠の一覧を返す。"""
    if tf is None:
        return 0.0, []

    score = 0.0
    reasons = []

    if tf["trend_signal"] == 1:
        score += 0.4
        reasons.append("25日・75日移動平均線がともに上向き(上昇トレンド)")
    elif tf["trend_signal"] == -1:
        score -= 0.4
        reasons.append("25日・75日移動平均線がともに下向き(下降トレンド)")

    if tf["rsi14"] is not None:
        if tf["rsi14"] < 30:
            score += 0.2
            reasons.append(f"RSI14が{tf['rsi14']}で売られすぎ水準(自律反発の可能性)")
        elif tf["rsi14"] > 70:
            score -= 0.2
            reasons.append(f"RSI14が{tf['rsi14']}で買われすぎ水準(過熱・調整リスク)")

    rel = tf.get("relative_strength_1m_vs_nikkei")
    if rel is not None:
        score += max(-0.3, min(0.3, rel / 20))
        if abs(rel) >= 3:
            direction = "上回って" if rel > 0 else "下回って"
            reasons.append(f"直近1ヶ月の騰落率が日経平均を{abs(rel):.1f}pt{direction}いる")

    if tf["range_pos_52w"] >= 0.95:
        reasons.append("52週高値圏(年初来高値に接近)")
    elif tf["range_pos_52w"] <= 0.05:
        reasons.append("52週安値圏(年初来安値に接近)")

    return max(-1.0, min(1.0, score)), reasons


def fundamentals_for(code, price=None):
    """PER・PBR・配当利回り(参考情報)。yfinanceの情報取得は失敗・欠損しうるため、
    失敗時や未取得の項目は単に含めない(未確認情報として扱う)。

    配当利回りは yfinance の `dividendYield` を直接使わず、1株配当(dividendRate、円建ての
    実額なので単位の曖昧さがない)÷株価 から自前で計算する。`dividendYield` はyfinanceの
    バージョンによって「比率(0.012)」と「%そのもの(1.2)」の混在が報告されており、
    そのまま使うと桁を誤る(例: 49%のような非現実的な値になる)ため採用しない。"""
    try:
        info = yf.Ticker(f"{code}.T").get_info()
    except Exception:
        return {}

    out = {}
    per = info.get("trailingPE")
    if per is not None:
        out["per"] = round(per, 2)
    pbr = info.get("priceToBook")
    if pbr is not None:
        out["pbr"] = round(pbr, 2)

    dividend_rate = info.get("dividendRate")
    ref_price = price or info.get("currentPrice") or info.get("previousClose")
    if dividend_rate and ref_price:
        out["dividend_yield_pct"] = round(dividend_rate / ref_price * 100, 2)
    return out
