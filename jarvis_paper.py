"""
Jarvis Stufe 2: Paper Trading (Spielgeld)
=========================================
Laeuft jede Stunde auf GitHub:
  1. Laedt die neuesten Kerzen fuer 10 Coins.
  2. Sucht das TJR-Muster mit der Strategie aus strategie.json
     (die stellt jarvis_lernen.py jede Nacht selbst ein).
  3. Eroeffnet Spielgeld-Trades, prueft offene Trades auf Ziel oder Stop.
  4. Meldet alles per Telegram und speichert das Tagebuch in paper/stand.json.

Es wird KEIN echtes Geld bewegt.
"""

import json
import os
import time

import jarvis_stufe1 as jarvis
from jarvis_daten import COINS, DAUER_MS, ema, kerzen_laden

jarvis.TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
jarvis.TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

ORDNER = os.path.dirname(os.path.abspath(__file__))
STAND = os.path.join(ORDNER, "paper", "stand.json")
STRATEGIE = os.path.join(ORDNER, "strategie.json")

STARTKONTO = 1000.0     # Spielgeld in $
RISIKO_PROZENT = 1.0    # pro Trade riskiert Jarvis 1 % des Kontos
GEBUEHR = 0.001         # 0,1 % pro Seite
MAX_KERZEN_OFFEN = 500  # danach wird der Trade zum aktuellen Preis geschlossen

STANDARD_STRATEGIE = {"name": "TJR 1h Ziel 2R + Trendfilter", "aktiv": True,
                      "intervall": "1h", "ziel_r": 2.0, "trendfilter": True, "trend_ema": 200}


def lesen(pfad, standard):
    if os.path.exists(pfad):
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    return standard


def schreiben(pfad, daten):
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(daten, f, indent=1, ensure_ascii=False)


def senden(text):
    print(text)
    if jarvis.TELEGRAM_TOKEN and jarvis.TELEGRAM_CHAT_ID:
        try:
            jarvis.telegram_senden(text)
        except Exception as fehler:
            print(f"Telegram-Fehler: {fehler}")


def kurz(coin):
    return coin.replace("USDT", "")


def preis(p):
    return f"{p:,.4f}" if p < 10 else f"{p:,.2f}" if p < 1000 else f"{p:,.0f}"


def neue_signale(stand, strat, coin, kerzen):
    if not strat.get("aktiv", True) or len(kerzen) < 220:
        return
    sig = jarvis.suche_signal(kerzen[-199:])
    if not sig:
        return
    sig_id = f"{coin}-{strat['intervall']}-{sig['id']}"
    if sig_id in stand["gemeldet"]:
        return
    stand["gemeldet"] = (stand["gemeldet"] + [sig_id])[-1000:]
    if any(t["coin"] == coin for t in stand["offen"]):
        return  # pro Coin nur ein Trade gleichzeitig (wie im Labor)
    kauf = sig["richtung"] == "KAUF"
    if strat.get("nur_kauf") and not kauf:
        return
    if strat.get("trendfilter"):
        trend = ema([k["close"] for k in kerzen], strat["trend_ema"])[-1]
        if kauf != (kerzen[-1]["close"] > trend):
            return
    risiko_preis = abs(sig["einstieg"] - sig["stop"])
    if risiko_preis <= 0:
        return
    ziel = sig["einstieg"] + strat["ziel_r"] * risiko_preis * (1 if kauf else -1)
    trade = {"coin": coin, "intervall": strat["intervall"], "strategie": strat["name"],
             "richtung": sig["richtung"], "einstieg": sig["einstieg"], "stop": sig["stop"], "ziel": ziel,
             "risiko_usd": round(stand["konto"] * RISIKO_PROZENT / 100, 2),
             "eroeffnet": kerzen[-1]["zeit"], "geprueft_bis": kerzen[-1]["zeit"] - 1, "kerzen": 0}
    stand["offen"].append(trade)
    pfeil = "🟢" if kauf else "🔴"
    senden(f"{strat.get('label', '')}📝 {pfeil} Paper-Trade: {sig['richtung']} {kurz(coin)} ({strat['intervall']})\n"
           f"Einstieg {preis(sig['einstieg'])} $ · Stop {preis(sig['stop'])} $ · Ziel {preis(ziel)} $\n"
           f"Spielgeld-Risiko: {trade['risiko_usd']:.0f} $")


def offene_pruefen(stand, coin, kerzen, label=""):
    for t in [t for t in stand["offen"] if t["coin"] == coin]:
        kauf = t["richtung"] == "KAUF"
        ergebnis = None
        for k in kerzen:
            if k["zeit"] <= t["geprueft_bis"]:
                continue
            t["geprueft_bis"] = k["zeit"]
            t["kerzen"] += 1
            if (kauf and k["low"] <= t["stop"]) or (not kauf and k["high"] >= t["stop"]):
                ergebnis, ausstieg = "STOP", t["stop"]
            elif (kauf and k["high"] >= t["ziel"]) or (not kauf and k["low"] <= t["ziel"]):
                ergebnis, ausstieg = "ZIEL", t["ziel"]
            elif t["kerzen"] >= MAX_KERZEN_OFFEN:
                ergebnis, ausstieg = "ZEIT", k["close"]
            if ergebnis:
                break
        if not ergebnis:
            continue
        risiko_preis = abs(t["einstieg"] - t["stop"])
        r = (ausstieg - t["einstieg"]) / risiko_preis * (1 if kauf else -1)
        r -= 2 * GEBUEHR * t["einstieg"] / risiko_preis
        gewinn = r * t["risiko_usd"]
        stand["konto"] = round(stand["konto"] + gewinn, 2)
        t.update({"ergebnis": ergebnis, "ausstieg": ausstieg, "r": round(r, 3),
                  "gewinn_usd": round(gewinn, 2), "geschlossen": t["geprueft_bis"]})
        stand["offen"].remove(t)
        stand["geschlossen"].append(t)
        zeichen = {"ZIEL": "✅ Ziel erreicht", "STOP": "❌ Stop-Loss", "ZEIT": "⏱️ Zeit abgelaufen"}[ergebnis]
        senden(f"{label}{zeichen}: {kurz(coin)} {t['richtung']} {r:+.2f} R ({gewinn:+.2f} $)\n"
               f"Spielgeld-Konto: {stand['konto']:,.2f} $")


# Zweite Spur: nur Kaeufe, wie sie auf einem normalen Krypto-Konto moeglich sind.
KAUF_SPUR = {"name": "NUR KAUF 4h Ziel 2R + Trendfilter", "aktiv": True, "intervall": "4h",
             "ziel_r": 2.0, "trendfilter": True, "trend_ema": 50, "nur_kauf": True,
             "label": "🛒 Kauf-Spur\n"}
STAND_KAUF = os.path.join(ORDNER, "paper", "stand_kauf.json")


def spur(strat, stand_pfad, cache):
    neu = not os.path.exists(stand_pfad)
    stand = lesen(stand_pfad, {"start": int(time.time() * 1000), "konto": STARTKONTO,
                               "offen": [], "geschlossen": [], "gemeldet": []})
    label = strat.get("label", "")
    for coin in COINS:
        intervalle = {strat["intervall"]} | {t["intervall"] for t in stand["offen"] if t["coin"] == coin}
        for intervall in intervalle:
            schluessel = (coin, intervall)
            if schluessel not in cache:
                try:
                    tage = 520 * DAUER_MS[intervall] / 86400000
                    cache[schluessel] = kerzen_laden(coin, intervall, tage)
                except Exception as fehler:
                    print(f"{coin} {intervall}: keine Daten ({fehler})")
                    cache[schluessel] = ([], "-")
            kerzen, quelle = cache[schluessel]
            if not kerzen:
                continue
            if intervall == strat["intervall"]:
                if neu:
                    # Beim ersten Start alte Muster nur merken, nicht nachtraeglich handeln
                    sig = jarvis.suche_signal(kerzen[-199:])
                    if sig:
                        stand["gemeldet"].append(f"{coin}-{intervall}-{sig['id']}")
                else:
                    neue_signale(stand, strat, coin, kerzen)
            offene_pruefen(stand, coin, kerzen, label)
            print(f"{label.strip()} {kurz(coin)} {intervall}: {preis(kerzen[-1]['close'])} $ ({quelle})")
    if neu:
        senden(f"{label}🚀 Paper Trading gestartet\nStrategie: {strat['name']}\n"
               f"Coins: {', '.join(kurz(c) for c in COINS)}\nSpielgeld: {STARTKONTO:,.0f} $")
    elif os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        senden(f"{label}☁️ Jarvis laeuft. Strategie: {strat['name']}\n"
               f"Offene Trades: {len(stand['offen'])} · Abgeschlossen: {len(stand['geschlossen'])}\n"
               f"Spielgeld-Konto: {stand['konto']:,.2f} $")
    schreiben(stand_pfad, stand)


def main():
    cache = {}
    spur(lesen(STRATEGIE, STANDARD_STRATEGIE), STAND, cache)
    spur(KAUF_SPUR, STAND_KAUF, cache)


if __name__ == "__main__":
    main()
