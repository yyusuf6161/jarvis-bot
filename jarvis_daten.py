"""
Jarvis Datenlader: holt Kerzen fuer viele Coins.
Erst Binance (oeffentliche Kursdaten), wenn gesperrt: Coinbase.
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
         "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]
DAUER_MS = {"15m": 900000, "1h": 3600000, "4h": 14400000}


def _laden(url):
    anfrage = urllib.request.Request(url, headers={"User-Agent": "jarvis-bot"})
    with urllib.request.urlopen(anfrage, timeout=30) as antwort:
        return json.loads(antwort.read())


def _binance(coin, intervall, start_ms, ende_ms):
    kerzen, start = [], start_ms
    while start < ende_ms:
        daten = _laden("https://data-api.binance.vision/api/v3/klines?" + urllib.parse.urlencode(
            {"symbol": coin, "interval": intervall, "startTime": start, "limit": 1000}))
        if not daten:
            break
        kerzen += [{"zeit": k[0], "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4])} for k in daten]
        start = daten[-1][0] + 1
        if len(daten) < 1000:
            break
    return kerzen


def _iso(sek):
    return datetime.fromtimestamp(sek, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coinbase(coin, sek, start_ms, ende_ms):
    produkt = coin.replace("USDT", "-USD")
    kerzen = {}
    ende, anfang_gesamt = ende_ms // 1000, start_ms // 1000
    while ende > anfang_gesamt:
        anfang = max(anfang_gesamt, ende - 300 * sek)
        daten = _laden(f"https://api.exchange.coinbase.com/products/{produkt}/candles?" + urllib.parse.urlencode(
            {"granularity": sek, "start": _iso(anfang), "end": _iso(ende)}))
        if not daten:
            break
        for k in daten:
            kerzen[k[0]] = {"zeit": k[0] * 1000, "open": float(k[3]), "high": float(k[2]),
                            "low": float(k[1]), "close": float(k[4])}
        ende = anfang
        time.sleep(0.15)
    return [kerzen[t] for t in sorted(kerzen)]


def _zusammenfassen(kerzen, dauer_ms):
    gruppen = {}
    for k in kerzen:
        gruppen.setdefault(k["zeit"] // dauer_ms, []).append(k)
    out = []
    for schluessel in sorted(gruppen):
        g = gruppen[schluessel]
        out.append({"zeit": schluessel * dauer_ms, "open": g[0]["open"], "high": max(x["high"] for x in g),
                    "low": min(x["low"] for x in g), "close": g[-1]["close"]})
    return out


def kerzen_laden(coin, intervall, tage):
    """Gibt (kerzen, quelle) zurueck. Nur fertige Kerzen."""
    jetzt = int(time.time() * 1000)
    start = jetzt - int(tage * 86400000)
    try:
        kerzen, quelle = _binance(coin, intervall, start, jetzt), "Binance"
    except Exception:
        if intervall == "4h":
            kerzen = _zusammenfassen(_coinbase(coin, 3600, start, jetzt), DAUER_MS["4h"])
        else:
            kerzen = _coinbase(coin, DAUER_MS[intervall] // 1000, start, jetzt)
        quelle = "Coinbase"
    kerzen = [k for k in kerzen if k["zeit"] + DAUER_MS[intervall] <= jetzt]
    return kerzen, quelle


def ema(werte, n):
    a, out = 2 / (n + 1), []
    e = werte[0] if werte else 0
    for w in werte:
        e = a * w + (1 - a) * e
        out.append(e)
    return out
