"""
sheet_poller.py
---------------
Remplace webhook_server.py
Poll le Google Sheet toutes les 2 min
Détecte les nouvelles lignes → active l'accès automatiquement
"""

import os
import json
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

BOT_TOKEN  = os.environ.get("ECOM_BOT_TOKEN")
ADMIN_BOT  = os.environ.get("ADMIN_BOT_TOKEN")
ADMIN_ID   = int(os.environ.get("ADMIN_ID", "0"))
SHEET_ID   = os.environ.get("SHEET_ID")
USERS_FILE = "users_db.json"
SUBSCRIPTION_DAYS = 30

# ============================================================
#  HELPERS DB
# ============================================================

def load_db():
    if not os.path.exists(USERS_FILE):
        _save_db({"allowed": [], "subscriptions": {}})
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def _save_db(db):
    with open(USERS_FILE, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

def add_user(telegram_username: str, email: str, produit: str):
    db     = load_db()
    today  = datetime.now().strftime("%Y-%m-%d")
    expiry = (datetime.now() + timedelta(days=SUBSCRIPTION_DAYS)).strftime("%Y-%m-%d")

    db["subscriptions"][telegram_username] = {
        "telegram_username": telegram_username,
        "email":       email,
        "produit":     produit,
        "start_date":  today,
        "expiry_date": expiry,
        "notified_3d": False,
        "notified_1d": False,
        "active":      True,
    }
    _save_db(db)
    return expiry

# ============================================================
#  TELEGRAM HELPERS
# ============================================================

def tg_send(token: str, chat_id, text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        print(f"[TG] Erreur envoi {chat_id}: {e}")

# ============================================================
#  GOOGLE SHEET
# ============================================================

def get_sheet():
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        print(f"[DEBUG] GOOGLE_CREDENTIALS trouvé, longueur: {len(creds_json)}")
        creds_dict = json.loads(creds_json)
        print(f"[DEBUG] private_key_id utilisé: {creds_dict.get('private_key_id', 'INTROUVABLE')}")
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        print("[DEBUG] GOOGLE_CREDENTIALS absent, utilise credentials.json")
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)

    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).sheet1

# ============================================================
#  TRAITEMENT NOUVELLES LIGNES
# ============================================================

def process_new_rows():
    sheet   = get_sheet()
    rows    = sheet.get_all_records()
    headers = sheet.row_values(1)

    if "Traité" not in headers:
        print("[POLLER] ⚠️ Colonne 'Traité' introuvable dans le Sheet !")
        return

    col_traite = headers.index("Traité") + 1

    for i, row in enumerate(rows):
        traite = str(row.get("Traité", "")).strip().lower()
        if traite == "oui":
            continue

        email    = str(row.get("Adresse email utilisée pour l'achat", "")).strip().lower()
        telegram = str(row.get("Ton username Telegram (ex: @monpseudo)", "")).strip().lstrip("@")
        produit  = str(row.get("Produit acheté", "")).strip()

        if not email or not telegram:
            continue

        sheet.update_cell(i + 2, col_traite, "oui")
        expiry = add_user(telegram, email, produit)

        tg_send(BOT_TOKEN, f"@{telegram}",
            f"✅ *Accès activé — {produit} !*\n\n"
            f"Bienvenue ! Ton abonnement est actif.\n"
            f"📅 Expiration : *{expiry}*\n\n"
            f"Envoie /start pour commencer 🚀"
        )

        tg_send(ADMIN_BOT, ADMIN_ID,
            f"🎉 *Nouvel accès activé*\n\n"
            f"• @{telegram}\n"
            f"• 📦 {produit}\n"
            f"• 📧 {email}\n"
            f"• 📅 Expire le {expiry}"
        )

        print(f"[POLLER] ✅ Accès activé : @{telegram} ({produit})")

# ============================================================
#  VÉRIFICATION EXPIRATIONS (1x par jour)
# ============================================================

def check_expirations():
    today = datetime.now().date()
    db    = load_db()
    subs  = {uid: s for uid, s in db["subscriptions"].items() if s.get("active")}

    for uid, sub in subs.items():
        telegram  = sub.get("telegram_username", uid)
        expiry    = datetime.strptime(sub["expiry_date"], "%Y-%m-%d").date()
        days_left = (expiry - today).days

        if days_left == 3 and not sub.get("notified_3d"):
            tg_send(BOT_TOKEN, f"@{telegram}",
                f"⏰ *Ton accès expire dans 3 jours !*\n"
                f"📅 Expiration : *{sub['expiry_date']}*\n\n"
                f"🔄 Renouvelle ici 👉 [ton lien Beacons]"
            )
            db["subscriptions"][uid]["notified_3d"] = True

        elif days_left == 1 and not sub.get("notified_1d"):
            tg_send(BOT_TOKEN, f"@{telegram}",
                f"🚨 *Dernier rappel — expire demain !*\n"
                f"🔄 Renouvelle maintenant 👉 [ton lien Beacons]"
            )
            db["subscriptions"][uid]["notified_1d"] = True

        elif days_left <= 0:
            db["subscriptions"][uid]["active"] = False
            tg_send(BOT_TOKEN, f"@{telegram}",
                f"❌ *Ton accès a expiré.*\n"
                f"🔄 Pour retrouver l'accès 👉 [ton lien Beacons]"
            )
            tg_send(ADMIN_BOT, ADMIN_ID,
                f"🔴 *Accès expiré*\n• @{telegram}\n• {sub.get('produit', '')}"
            )

    _save_db(db)
    print(f"[POLLER] Expirations vérifiées — {len(subs)} abonnements actifs")

# ============================================================
#  BOUCLE PRINCIPALE
# ============================================================

def run_poller():
    print("[POLLER] Démarré — vérification toutes les 2 minutes")
    cycle = 0
    while True:
        try:
            process_new_rows()
        except Exception as e:
            print(f"[POLLER] Erreur process_new_rows: {e}")

        cycle += 1
        if cycle >= 720:
            try:
                check_expirations()
            except Exception as e:
                print(f"[POLLER] Erreur check_expirations: {e}")
            cycle = 0

        time.sleep(120)

if __name__ == "__main__":
    run_poller()
