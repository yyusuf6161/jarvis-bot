"""
Jarvis Trading-Bot – Stufe 1: Signale aufs Handy
================================================

Was das Skript macht:
  1. Laedt alle 15 Minuten die Bitcoin-Kurse von Binance (kostenlos, ohne Konto).
  2. Sucht das TJR-Muster:  Liquidity Sweep -> Break of Structure -> Fair Value Gap.
  3. Wenn der Kurs zurueck in die Luecke (Fair Value Gap) kommt,
     schickt es dir eine Nachricht ueber deinen Telegram-Bot.

Der Bot handelt NICHT selbst. Er meldet nur. Du entscheidest.

Starten (Doppelklick):
  TEST_JARVIS.bat     -> schickt nur eine Test-Nachricht
  START_JARVIS.bat    -> Bot laeuft dauerhaft

Braucht nur Python 3, keine zusaetzlichen Pakete.
"""

import json
import sys
import time
import urllib.parse
import urllib.request

# ------------------------------------------------------------
# EINSTELLUNGEN  (nur hier etwas aendern)
# ------------------------------------------------------------

# Dein Telegram-Bot: Token und Chat-ID werden automatisch aus meme_bot.py
# im selben Ordner gelesen. Du musst hier nichts eintragen.
# WICHTIG: Den Token niemandem zeigen und nirgends hochladen!
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""


def telegram_daten_aus_memebot():
    """Liest TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID aus meme_bot.py."""
    import os
    import re
    pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meme_bot.py")
    if not os.path.exists(pfad):
        return "", ""
    with open(pfad, encoding="utf-8") as f:
        inhalt = f.read()
    token = re.search(r'^TELEGRAM_BOT_TOKEN\s*=\s*["\']([^"\']*)["\']', inhalt, re.M)
    chat = re.search(r'^TELEGRAM_CHAT_ID\s*=\s*["\']([^"\']*)["\']', inhalt, re.M)
    return (token.group(1) if token else ""), (chat.group(1) if chat else "")


if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID = telegram_daten_aus_memebot()

COIN = "BTCUSDT"          # Bitcoin gegen Dollar. Spaeter z. B. "ETHUSDT", "SOLUSDT"
ZEITRAHMEN = "15m"        # Eine Kerze = 15 Minuten
ANZAHL_KERZEN = 200       # So viele Kerzen schaut der Bot zurueck
SWING_BREITE = 3          # Ein Hoch/Tief zaehlt, wenn 3 Kerzen links und rechts niedriger/hoeher sind
PRUEFEN_ALLE_SEKUNDEN = 60


# ------------------------------------------------------------
# 1. KURSE LADEN
# ------------------------------------------------------------

def kurse_laden():
    """Holt die letzten Kerzen von Binance. Jede Kerze: open, high, low, close, zeit."""
    url = (
        "https://api.binance.com/api/v3/klines?"
        + urllib.parse.urlencode({"symbol": COIN, "interval": ZEITRAHMEN, "limit": ANZAHL_KERZEN})
    )
    with urllib.request.urlopen(url, timeout=15) as antwort:
        daten = json.loads(antwort.read())

    kerzen = []
    for k in daten:
        kerzen.append({
            "zeit": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
        })
    # Die letzte Kerze ist noch nicht fertig -> weglassen
    return kerzen[:-1]


# ------------------------------------------------------------
# 2. MUSTER ERKENNEN
# ------------------------------------------------------------

def swing_punkte(kerzen):
    """Findet Swing-Hochs und Swing-Tiefs (die 'Spitzen' und 'Taeler' im Chart)."""
    hochs, tiefs = [], []
    b = SWING_BREITE
    for i in range(b, len(kerzen) - b):
        nachbarn = kerzen[i - b:i] + kerzen[i + 1:i + b + 1]
        if all(kerzen[i]["high"] > n["high"] for n in nachbarn):
            hochs.append(i)
        if all(kerzen[i]["low"] < n["low"] for n in nachbarn):
            tiefs.append(i)
    return hochs, tiefs


def suche_kauf_signal(kerzen):
    """
    Kauf-Muster (bullish):
      a) Sweep: Kerze sticht unter ein altes Tief, schliesst aber wieder darueber.
      b) Break of Structure: Danach schliesst eine Kerze ueber dem letzten Hoch.
      c) Fair Value Gap: In dieser Aufwaertsbewegung gibt es eine Luecke.
      d) Signal: Die neueste Kerze kommt zurueck in diese Luecke.
    """
    hochs, tiefs = swing_punkte(kerzen)
    letzte = len(kerzen) - 1

    # Neueste Muster zuerst pruefen
    for tief in reversed(tiefs):
        tief_preis = kerzen[tief]["low"]

        # a) Sweep suchen
        sweep = None
        for i in range(tief + SWING_BREITE + 1, letzte):
            if kerzen[i]["low"] < tief_preis and kerzen[i]["close"] > tief_preis:
                sweep = i
                break
            if kerzen[i]["close"] < tief_preis:
                break  # Tief wurde richtig gebrochen, kein Sweep
        if sweep is None:
            continue

        # Letztes Swing-Hoch vor dem Sweep
        hochs_davor = [h for h in hochs if h < sweep]
        if not hochs_davor:
            continue
        hoch_preis = kerzen[hochs_davor[-1]]["high"]

        # b) Break of Structure suchen
        bos = None
        for j in range(sweep + 1, letzte):
            if kerzen[j]["close"] > hoch_preis:
                bos = j
                break
            if kerzen[j]["low"] < kerzen[sweep]["low"]:
                break  # Neues Tief -> Muster kaputt
        if bos is None:
            continue

        # c) Fair Value Gap zwischen Sweep und Break of Structure
        for k in range(bos - 1, sweep, -1):
            luecke_unten = kerzen[k - 1]["high"]
            luecke_oben = kerzen[k + 1]["low"]
            if luecke_oben > luecke_unten:
                # Wurde die Luecke schon vor der neuesten Kerze gefuellt?
                schon_benutzt = any(kerzen[m]["low"] <= luecke_oben for m in range(k + 2, letzte))
                if schon_benutzt:
                    break
                # d) Neueste Kerze kommt zurueck in die Luecke
                neu = kerzen[letzte]
                if neu["low"] <= luecke_oben and neu["close"] >= luecke_unten:
                    stop = kerzen[sweep]["low"]
                    einstieg = luecke_oben
                    ziel = einstieg + 2 * (einstieg - stop)
                    return {
                        "richtung": "KAUF",
                        "einstieg": einstieg,
                        "stop": stop,
                        "ziel": ziel,
                        "luecke": (luecke_unten, luecke_oben),
                        "id": f"kauf-{kerzen[sweep]['zeit']}",
                    }
                break
        # Nur das neueste passende Muster zaehlt
        return None
    return None


def spiegeln(kerzen):
    """Dreht den Chart auf den Kopf. So findet die Kauf-Suche auch Verkaufs-Muster."""
    return [
        {"zeit": k["zeit"], "open": -k["open"], "high": -k["low"], "low": -k["high"], "close": -k["close"]}
        for k in kerzen
    ]


def suche_signal(kerzen):
    signal = suche_kauf_signal(kerzen)
    if signal:
        return signal

    signal = suche_kauf_signal(spiegeln(kerzen))
    if signal:
        return {
            "richtung": "VERKAUF",
            "einstieg": -signal["einstieg"],
            "stop": -signal["stop"],
            "ziel": -signal["ziel"],
            "luecke": (-signal["luecke"][1], -signal["luecke"][0]),
            "id": signal["id"].replace("kauf", "verkauf"),
        }
    return None


# ------------------------------------------------------------
# 3. NACHRICHT AUFS HANDY
# ------------------------------------------------------------

def telegram_senden(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    daten = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode()
    with urllib.request.urlopen(url, data=daten, timeout=15) as antwort:
        return json.loads(antwort.read())


def nachricht_bauen(s):
    pfeil = "🟢" if s["richtung"] == "KAUF" else "🔴"
    return (
        f"{pfeil} Jarvis: {s['richtung']}-Signal {COIN} ({ZEITRAHMEN})\n\n"
        f"Muster: Sweep -> Break of Structure -> zurueck im Fair Value Gap\n"
        f"Einstieg ca.: {s['einstieg']:,.0f} $\n"
        f"Stop-Loss:    {s['stop']:,.0f} $\n"
        f"Ziel (2:1):   {s['ziel']:,.0f} $\n\n"
        f"Nur ein Hinweis, kein Finanzrat. Du entscheidest selbst."
    )


# ------------------------------------------------------------
# 4. HAUPTSCHLEIFE
# ------------------------------------------------------------

def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Keine Telegram-Daten gefunden. Liegt meme_bot.py im selben Ordner")
        print("und sind dort TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID eingetragen?")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        telegram_senden(f"✅ Jarvis ist verbunden und beobachtet {COIN}.")
        print("Test-Nachricht gesendet. Schau auf dein Handy.")
        return

    print(f"Jarvis beobachtet {COIN} ({ZEITRAHMEN}). Stoppen mit Strg+C.")
    schon_gemeldet = set()

    while True:
        try:
            kerzen = kurse_laden()
            signal = suche_signal(kerzen)
            preis = kerzen[-1]["close"]
            zeit = time.strftime("%H:%M")

            if signal and signal["id"] not in schon_gemeldet:
                telegram_senden(nachricht_bauen(signal))
                schon_gemeldet.add(signal["id"])
                print(f"[{zeit}] SIGNAL gesendet: {signal['richtung']} bei {preis:,.0f} $")
            else:
                print(f"[{zeit}] {COIN}: {preis:,.0f} $ - kein Signal")
        except Exception as fehler:
            print(f"Fehler: {fehler} - neuer Versuch gleich")

        time.sleep(PRUEFEN_ALLE_SEKUNDEN)


if __name__ == "__main__":
    main()
