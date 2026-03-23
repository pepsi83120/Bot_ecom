"""
main.py
-------
Point d'entrée unique pour Railway.
Lance en parallèle :
  - webhook_server (Flask + scheduler)
  - admin_bot (polling Telegram)
  - ecom_bot (polling Telegram) — optionnel si tu veux tout en 1 process
"""

import threading
import os

def run_webhook():
    from webhook_server import app, check_expirations
    port = int(os.environ.get("PORT", 5000))
    check_expirations()
    app.run(host="0.0.0.0", port=port)

def run_admin_bot():
    import admin_bot  # noqa — démarre le polling via le module

def run_ecom_bot():
    import bot_ecom_fixed  # noqa — démarre le polling via le module

if __name__ == "__main__":
    threads = [
        threading.Thread(target=run_webhook,   daemon=False, name="webhook"),
        threading.Thread(target=run_admin_bot, daemon=False, name="admin_bot"),
        threading.Thread(target=run_ecom_bot,  daemon=False, name="ecom_bot"),
    ]
    for t in threads:
        print(f"[MAIN] Démarrage : {t.name}")
        t.start()
    for t in threads:
        t.join()
