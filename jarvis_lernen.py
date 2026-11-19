"""
Jarvis lernt jede Nacht
=======================
Laeuft taeglich auf GitHub:
  1. Laedt die neuesten Kurse (10 Coins, 1h: 2 Jahre, 4h: 4 Jahre).
  2. Testet alle 8 TJR-Varianten neu: Training (70 %) + Pruefung (30 %), mit Gebuehren.
  3. Entscheidet, mit welcher Variante das Paper Trading weiterlaeuft:
       - Die aktuelle Variante besteht noch  -> sie bleibt (keine Hektik).
       - Sie faellt durch, eine andere besteht -> Jarvis wechselt und sagt Bescheid.
       - Keine besteht                         -> Pause: keine neuen Paper-Trades.
  4. Sonntags: Wochenbericht per Telegram (Labor + Paper-Trading-Konto).
"""

import json
import os
import time

import jarvis_stufe1 as jarvis
from jarvis_daten import COINS, ema, kerzen_laden
from jarvis_paper import STAND, STRATEGIE, STANDARD_STRATEGIE, lesen, schreiben, senden

TRAINING_ANTEIL = 0.7
GEBUEHR = 0.001
MAX_WARTEN = 500
ZEITRAHMEN = [("1h", 730, 200), ("4h", 1460, 50)]
ZIELE = [2.0, 3.0]
ORDNER = os.path.dirname(os.path.abspath(__file__))
BERICHT = os.path.join(ORDNER, "lernen", "letzter_test.txt")


def tjr_signale(k):
    s, gesehen = [None] * len(k), set()
    for i in range(198, len(k)):
        sig = jarvis.suche_signal(k[i - 198:i + 1])
        if sig and sig["id"] not in gesehen:
            gesehen.add(sig["id"])
            s[i] = sig
    return s


def trade_r(k, i, kauf, einstieg, stop, ziel):
    risiko = abs(einstieg - stop)
    if risiko <= 0:
        return None, i
    gebuehr_r = 2 * GEBUEHR * einstieg / risiko
    for j in range(i, min(i + MAX_WARTEN, len(k))):
        if (kauf and k[j]["low"] <= stop) or (not kauf and k[j]["high"] >= stop):
            return -1 - gebuehr_r, j
        if (kauf and k[j]["high"] >= ziel) or (not kauf and k[j]["low"] <= ziel):
            return abs(ziel - einstieg) / risiko - gebuehr_r, j
    return None, min(i + MAX_WARTEN, len(k) - 1)


def simulieren(k, roh, trend, ziel_r, mit_filter, trend_ema):
    trades, frei_ab = [], 0
    for i, sig in enumerate(roh):
        if sig is None or i < frei_ab or i < trend_ema:
            continue
        kauf = sig["richtung"] == "KAUF"
        if mit_filter and kauf != (k[i]["close"] > trend[i]):
            continue
        risiko = abs(sig["einstieg"] - sig["stop"])
        ziel = sig["einstieg"] + ziel_r * risiko * (1 if kauf else -1)
        r, ende = trade_r(k, i, kauf, sig["einstieg"], sig["stop"], ziel)
        frei_ab = ende + 1
        if r is not None:
            trades.append({"i": i, "r": r})
    return trades


def kennzahlen(trades):
    n = len(trades)
    summe = sum(t["r"] for t in trades)
    return {"n": n, "quote": 100 * sum(1 for t in trades if t["r"] > 0) / n if n else 0,
            "summe": summe, "pro_trade": summe / n if n else 0}


def variante_name(intervall, ziel_r, filt):
    return f"TJR {intervall} Ziel {ziel_r:.0f}R" + (" + Trendfilter" if filt else "")


def labor():
    sammel = {}
    for intervall, tage, trend_ema in ZEITRAHMEN:
        for coin in COINS:
            try:
                k, _ = kerzen_laden(coin, intervall, tage)
            except Exception as fehler:
                print(f"{coin} {intervall}: keine Daten ({fehler})")
                continue
            if len(k) < 600:
                continue
            print(f"Teste {coin} {intervall} ({len(k)} Kerzen)")
            trend = ema([x["close"] for x in k], trend_ema)
            roh = tjr_signale(k)
            grenze = int(len(k) * TRAINING_ANTEIL)
            for ziel_r in ZIELE:
                for filt in (False, True):
                    name = variante_name(intervall, ziel_r, filt)
                    s = sammel.setdefault(name, {"intervall": intervall, "ziel_r": ziel_r, "trendfilter": filt,
                                                 "trend_ema": trend_ema, "train": [], "pruef": []})
                    for t in simulieren(k, roh, trend, ziel_r, filt, trend_ema):
                        (s["train"] if t["i"] < grenze else s["pruef"]).append(t)
    ergebnisse = []
    for name, s in sammel.items():
        tr, pr = kennzahlen(s["train"]), kennzahlen(s["pruef"])
        ok = tr["n"] >= 40 and pr["n"] >= 15 and tr["summe"] > 0 and pr["summe"] > 0
        ergebnisse.append({"name": name, "intervall": s["intervall"], "ziel_r": s["ziel_r"],
                           "trendfilter": s["trendfilter"], "trend_ema": s["trend_ema"],
                           "train": tr, "pruef": pr, "bestanden": ok})
    return sorted(ergebnisse, key=lambda e: e["pruef"]["pro_trade"], reverse=True)


def paper_zusammenfassung(seit_ms=None):
    stand = lesen(STAND, None)
    if not stand:
        return "Paper Trading: noch keine Daten."
    zu = [t for t in stand["geschlossen"] if seit_ms is None or t["geschlossen"] >= seit_ms]
    alle = stand["geschlossen"]
    def zeile(ts):
        if not ts:
            return "0 Trades"
        gew = sum(1 for t in ts if t["r"] > 0)
        return f"{len(ts)} Trades, {100 * gew / len(ts):.0f} % Treffer, {sum(t['r'] for t in ts):+.1f} R"
    return (f"Paper Trading\n  Diese Woche: {zeile(zu)}\n  Seit Start:  {zeile(alle)}\n"
            f"  Offen: {len(stand['offen'])}\n  Spielgeld-Konto: {stand['konto']:,.2f} $ (Start 1.000 $)")


def main():
    ergebnisse = labor()
    alt = lesen(STRATEGIE, STANDARD_STRATEGIE)
    bestanden = [e for e in ergebnisse if e["bestanden"]]
    alt_jetzt = next((e for e in ergebnisse if e["name"] == alt["name"]), None)

    if alt_jetzt and alt_jetzt["bestanden"]:
        neu = alt_jetzt
        meldung = None if alt.get("aktiv", True) else f"▶️ Jarvis macht weiter: {neu['name']} besteht wieder."
    elif bestanden:
        neu = bestanden[0]
        meldung = (f"🧠 Jarvis hat dazugelernt: '{alt['name']}' besteht den Test nicht mehr.\n"
                   f"Neu: {neu['name']} (Pruefung: {neu['pruef']['n']} Trades, "
                   f"{neu['pruef']['quote']:.0f} % Treffer, {neu['pruef']['summe']:+.1f} R)")
    else:
        neu = None
        meldung = ("⏸️ Jarvis macht Pause: Heute besteht keine Variante den Test.\n"
                   "Keine neuen Paper-Trades, bis wieder eine besteht. Offene Trades laufen weiter.")

    if neu:
        strat = {"name": neu["name"], "aktiv": True, "intervall": neu["intervall"], "ziel_r": neu["ziel_r"],
                 "trendfilter": neu["trendfilter"], "trend_ema": neu["trend_ema"]}
    else:
        strat = dict(alt, aktiv=False)
    if not neu and not alt.get("aktiv", True):
        meldung = None  # Pause wurde schon gemeldet
    strat["getestet"] = time.strftime("%Y-%m-%d")
    schreiben(STRATEGIE, strat)

    z = [f"Jarvis-Test vom {strat['getestet']} (10 Coins, inkl. Gebuehren)",
         f"{'Variante':<30}{'Training':>20}{'Pruefung':>20}"]
    for e in ergebnisse:
        t, p = e["train"], e["pruef"]
        z.append(f"{e['name']:<30}{t['n']:>5} {t['quote']:>3.0f}% {t['summe']:>+6.1f}R"
                 f"{p['n']:>6} {p['quote']:>3.0f}% {p['summe']:>+6.1f}R  {'OK' if e['bestanden'] else '--'}")
    text = "\n".join(z)
    print(text)
    schreiben(BERICHT.replace(".txt", ".json"), ergebnisse)
    os.makedirs(os.path.dirname(BERICHT), exist_ok=True)
    with open(BERICHT, "w", encoding="utf-8") as f:
        f.write(text)

    if meldung:
        senden(meldung)
    wochentag = time.gmtime().tm_wday  # 6 = Sonntag
    if wochentag == 6 or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        woche = int(time.time() * 1000) - 7 * 86400000
        status = f"Aktive Strategie: {strat['name']}" if strat.get("aktiv") else "Status: Pause"
        bester = bestanden[0]["name"] if bestanden else "keine"
        senden(f"📊 Jarvis Wochenbericht\n\n{status}\nHeute bestanden: {len(bestanden)} von {len(ergebnisse)} "
               f"Varianten (beste: {bester})\n\n{paper_zusammenfassung(woche)}\n\nKein echtes Geld im Spiel.")


if __name__ == "__main__":
    main()
