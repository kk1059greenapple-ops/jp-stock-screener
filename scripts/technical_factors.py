"""株価の時系列データ(直近1年、yfinance=無料・Yahoo Financeベース)から、
ニュースに依存しない客観的なテクニカル指標・ファンダメンタルズ指標を算出する。

取引所の実際の値動きそのものに基づくため、ニュース見出しの解析よりも裏付けの確実な
補助情報として扱い、上昇期待度に加点・減点する。

ここに実装している考え方は、特定の秘密のノウハウではなく、ファクター投資(バリュー・モメンタム)、
出来高分析、日本市場特有の制度・アノマリー(PBR1倍割れ改善要請、権利付き最終日前の買い需要)として
広く公表・研究されている一般的な手法を、公式データで計算できる範囲に落とし込んだものである。
"""
import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

try:
    from curl_cffi import requests as curl_requests

    # GitHub Actionsの共有IPからyfinanceの銘柄詳細(.get_info()/.calendar)を連続取得すると、
    # Yahoo Finance側のクラム認証がbotとみなして429/401で弾くことを確認した(ローカルでは発生しない)。
    # 実ブラウザのTLSフィンガープリントを模すことで回避する、yfinance公式が推奨する対策。
    _SESSION = curl_requests.Session(impersonate="chrome")
except ImportError:
    _SESSION = None

NIKKEI_TICKER = "^N225"
HISTORY_CHUNK_SIZE = 100
SLEEP_BETWEEN_HISTORY_CHUNKS = 1.5
SLEEP_BETWEEN_INFO_CALLS = 0.5

# 東証は2023年にPBR1倍割れ企業へ資本効率・株価を意識した経営改善を要請しており、
# この水準を切っている銘柄は改善期待の思惑的な資金が入りやすいテーマ性がある(公表済みの制度的事実)。
PBR_IMPROVEMENT_THRESHOLD = 1.0
RIGHTS_WINDOW_DAYS = 20  # 権利付き最終日までの日数がこの範囲なら「接近」とみなす
EARNINGS_WARNING_DAYS = 10  # 決算発表までの日数がこの範囲なら注意喚起を表示


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
    """銘柄コード一覧(+日経平均)について直近1年の日足終値・出来高を取得する。

    戻り値: { "xxxx.T": {"close": Series, "volume": Series}, ... }
    """
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
                session=_SESSION,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"history batch failed: {exc}")
            continue

        multi = len(batch) > 1
        for ticker in batch:
            try:
                frame = data[ticker] if multi else data
                closes = frame["Close"].dropna()
                volumes = frame["Volume"].reindex(closes.index)
            except Exception:
                continue
            if len(closes) >= 20:
                history[ticker] = {"close": closes, "volume": volumes}
        time.sleep(SLEEP_BETWEEN_HISTORY_CHUNKS)

    return history


def technical_factors_for(series, nikkei_series):
    """移動平均・RSI・52週レンジ・騰落率・出来高など、価格データのみから計算できる客観指標。

    series / nikkei_series は fetch_price_history が返す {"close":, "volume":} 形式。
    """
    if series is None:
        return None
    closes = series.get("close")
    volumes = series.get("volume")
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

    nikkei_closes = nikkei_series.get("close") if nikkei_series else None
    rel_strength_1m = None
    if nikkei_closes is not None and len(nikkei_closes) > 20 and change_1m is not None:
        nk_price = float(nikkei_closes.iloc[-1])
        nk_base = float(nikkei_closes.iloc[-21])
        if nk_base:
            nk_change = (nk_price - nk_base) / nk_base * 100
            rel_strength_1m = round(change_1m - nk_change, 2)

    vol_ratio_20d = None
    if volumes is not None and volumes.notna().sum() >= 20:
        recent_vol = volumes.dropna()
        avg_vol20 = float(recent_vol.tail(20).mean())
        latest_vol = float(recent_vol.iloc[-1])
        if avg_vol20:
            vol_ratio_20d = round(latest_vol / avg_vol20, 2)

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
        "volume_ratio_20d": vol_ratio_20d,
    }


def technical_score(tf, fundamentals=None):
    """テクニカル・ファンダメンタルズ指標から -1〜1 のスコアと、判断根拠の一覧を返す。"""
    fundamentals = fundamentals or {}
    score = 0.0
    reasons = []

    if tf is not None:
        if tf["trend_signal"] == 1:
            score += 0.35
            reasons.append("25日・75日移動平均線がともに上向き(上昇トレンド)")
        elif tf["trend_signal"] == -1:
            score -= 0.35
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
            score += max(-0.25, min(0.25, rel / 24))
            if abs(rel) >= 3:
                direction = "上回って" if rel > 0 else "下回って"
                reasons.append(f"直近1ヶ月の騰落率が日経平均を{abs(rel):.1f}pt{direction}いる")

        if tf["range_pos_52w"] >= 0.95:
            reasons.append("52週高値圏(年初来高値に接近)")
        elif tf["range_pos_52w"] <= 0.05:
            reasons.append("52週安値圏(年初来安値に接近)")

        # 出来高分析: 「出来高は価格に先行する」という相場格言どおり、トレンドが出来高を
        # 伴っているかで信頼性を調整する(プロのトレーダーがブレイクアウトの真偽判定に使う基本原則)。
        vol_ratio = tf.get("volume_ratio_20d")
        if vol_ratio is not None and tf["trend_signal"] == 1:
            if vol_ratio >= 1.5:
                score += 0.15
                reasons.append(f"直近出来高が20日平均の{vol_ratio}倍に増加(上昇の信頼性が高い)")
            elif vol_ratio < 0.6:
                score -= 0.1
                reasons.append(f"直近出来高が20日平均の{vol_ratio}倍と低調(上昇の持続性に注意)")
        elif vol_ratio is not None and tf["trend_signal"] == -1 and vol_ratio >= 1.5:
            score -= 0.1
            reasons.append(f"直近出来高が20日平均の{vol_ratio}倍に増加(下落の信頼性が高く、下値不安)")

    pbr = fundamentals.get("pbr")
    if pbr is not None and pbr < PBR_IMPROVEMENT_THRESHOLD:
        score += 0.1
        reasons.append(f"PBR{pbr}倍で1倍割れ(東証が要請する資本効率・株価意識経営の改善テーマ性あり)")

    days_to_rights = fundamentals.get("days_to_ex_dividend")
    if days_to_rights is not None and 0 <= days_to_rights <= RIGHTS_WINDOW_DAYS:
        score += 0.1
        reasons.append(
            f"権利付き最終日(配当・優待)まで約{days_to_rights}日で、権利取り需要が入りやすい時期"
        )

    return max(-1.0, min(1.0, score)), reasons


def fundamentals_for(code, price=None):
    """PER・PBR・配当利回り・権利確定日・決算発表予定日(参考情報)。

    yfinanceの情報取得は失敗・欠損しうるため、失敗時や未取得の項目は単に含めない
    (未確認情報として扱い、無理に埋め合わせない)。

    配当利回りは yfinance の `dividendYield` を直接使わず、1株配当(dividendRate、円建ての
    実額なので単位の曖昧さがない)÷株価 から自前で計算する。`dividendYield` はyfinanceの
    バージョンによって「比率(0.012)」と「%そのもの(1.2)」の混在が報告されており、
    そのまま使うと桁を誤る(例: 49%のような非現実的な値になる)ため採用しない。
    """
    ticker = yf.Ticker(f"{code}.T", session=_SESSION)
    info = None
    for attempt in range(2):
        try:
            info = ticker.get_info()
            break
        except Exception as exc:  # noqa: BLE001
            print(f"fundamentals fetch failed for {code} (attempt {attempt + 1}): {exc}")
            time.sleep(1.0)
    if not info:
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

    now = datetime.now(timezone.utc)

    # yfinanceは銘柄によって「次回の予定日」ではなく、更新が止まった古い実績日を返すことがある
    # (配当停止銘柄などで2019年等の日付が返る例を確認済み)。無関係に古い/先すぎる日付は
    # 「次回の目安」として意味を持たないため、直近の妥当な範囲のみ採用する。
    ex_div_ts = info.get("exDividendDate")
    if ex_div_ts:
        try:
            ex_div_date = datetime.fromtimestamp(ex_div_ts, tz=timezone.utc)
            days_to_ex_dividend = (ex_div_date - now).days
            if -30 <= days_to_ex_dividend <= 400:
                out["ex_dividend_date"] = ex_div_date.date().isoformat()
                out["days_to_ex_dividend"] = days_to_ex_dividend
        except (OverflowError, OSError, ValueError):
            pass

    try:
        calendar = ticker.calendar or {}
        earnings_dates = calendar.get("Earnings Date") or []
        if earnings_dates:
            next_earnings = min(earnings_dates)
            days_to_earnings = (
                datetime.combine(next_earnings, datetime.min.time(), tzinfo=timezone.utc) - now
            ).days
            if -5 <= days_to_earnings <= 400:
                out["next_earnings_date"] = next_earnings.isoformat()
                out["days_to_earnings"] = days_to_earnings
    except Exception:
        pass

    return out


def sector_relative_valuation(stocks):
    """同業種(東証33業種区分)内でのPER・PBRの相対順位から、割安・割高の度合いを算出する。

    絶対水準のPER/PBRは業種によって適正レンジが大きく異なるため(例: 電力株と成長株を
    同じ閾値で比較するのは不適切)、同業種内での相対比較はプロの運用現場で広く使われる
    標準的な手法である。各グループ3銘柄未満の場合はノイズが大きいためスコアに反映しない。

    stocks の各要素は {"sector":, "fundamentals": {"per":, "pbr":}} を想定し、
    戻り値は銘柄コードをキーに {"percentile": 0-1(低いほど割安), "reason": str|None} を返す。
    0.5 を基準に ±(0.5-percentile)*2 のスコア(-1〜1、低percentile=割安=プラス)として使う。
    """
    from collections import defaultdict

    by_sector = defaultdict(list)
    for s in stocks:
        sector = s.get("sector") or "不明"
        per = (s.get("fundamentals") or {}).get("per")
        if per is not None and per > 0:
            by_sector[sector].append((s["code"], per))

    result = {}
    for sector, entries in by_sector.items():
        if len(entries) < 3:
            continue
        ordered = sorted(entries, key=lambda e: e[1])
        n = len(ordered)
        for rank, (code, per) in enumerate(ordered):
            percentile = rank / (n - 1) if n > 1 else 0.5
            result[code] = {
                "sector": sector,
                "per_percentile": round(percentile, 3),
                "peer_count": n,
            }
    return result
