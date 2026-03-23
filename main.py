"""
main.py — Point d'entrée Railway
Lance le poller Google Sheet + admin bot + ecom bot en parallèle
"""

import threading

def run_poller():
    from sheet_poller import run_poller as _run
    _run()

def run_admin_bot():
    import admin_bot  # noqa

def run_ecom_bot():
    import bot_ecom_fixed # noqa — adapte le nom si différent

if __name__ == "__main__":
    threads = [
        threading.Thread(target=run_poller,    daemon=False, name="sheet_poller"),
        threading.Thread(target=run_admin_bot, daemon=False, name="admin_bot"),
        threading.Thread(target=run_ecom_bot,  daemon=False, name="ecom_bot"),
    ]
    for t in threads:
        print(f"[MAIN] Démarrage : {t.name}")
        t.start()
    for t in threads:
        t.join()


