"""
Jarvis in der Cloud (GitHub Actions)
====================================
Laeuft alle 15 Minuten auf GitHub, auch wenn dein PC aus ist.
Prueft die neueste fertige Kerze und schickt bei einem Signal eine Telegram-Nachricht.

Token und Chat-ID kommen aus den GitHub-Secrets
TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID (nie in den Code schreiben!).
"""

import json
import os
import urllib.request

import jarvis_stufe1 as jarvis

jarvis.TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
jarvis.TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def laden(url):
    anfrage = urllib.request.Request(url, headers={"User-Agent": "jarvis-bot"})
    with urllib.request.urlopen(anfrage, timeout=20) as antwort:
        return json.loads(antwort.read())


def kurse_laden():
    """Erst Binance (oeffentliche Kursdaten), falls gesperrt: Coinbase."""
    try:
        daten = laden("https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=200")
        kerzen = [{"zeit": k[0], "open": float(k[1]), "high": float(k[2]),
                   "low": float(k[3]), "close": float(k[4])} for k in daten]
        return kerzen[:-1], "Binance"
    except Exception as fehler:
        print(f"Binance nicht erreichbar ({fehler}), nehme Coinbase.")
    daten = laden("https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=900")
    daten = sorted(daten, key=lambda k: k[0])          # Coinbase liefert neueste zuerst
    kerzen = [{"zeit": k[0] * 1000, "open": float(k[3]), "high": float(k[2]),
               "low": float(k[1]), "close": float(k[4])} for k in daten]
    return kerzen[:-1][-199:], "Coinbase"


def main():
    if not jarvis.TELEGRAM_TOKEN or not jarvis.TELEGRAM_CHAT_ID:
        raise SystemExit("Secrets TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID fehlen.")

    kerzen, quelle = kurse_laden()
    preis = kerzen[-1]["close"]
    signal = jarvis.suche_signal(kerzen)

    # Gleiches Muster schon bei der Kerze davor gemeldet? Dann nicht nochmal schicken.
    if signal:
        vorher = jarvis.suche_signal(kerzen[:-1])
        if vorher and vorher["id"] == signal["id"]:
            print("Signal wurde schon gemeldet.")
            signal = None

    if signal:
        jarvis.telegram_senden(jarvis.nachricht_bauen(signal))
        print(f"SIGNAL gesendet: {signal['richtung']} bei {preis:,.0f} $ ({quelle})")
    else:
        print(f"BTC {preis:,.0f} $ ({quelle}) - kein Signal")
        if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
            jarvis.telegram_senden(f"☁️ Jarvis laeuft in der Cloud. BTC: {preis:,.0f} $ - gerade kein Signal.")


if __name__ == "__main__":
    main()
