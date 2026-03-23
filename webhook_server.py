"""
webhook_server.py
-----------------
Reçoit les commandes Beacons → ajoute l'utilisateur automatiquement
Scheduler journalier → vérifie les expirations et notifie/supprime
"""

import os
import json
import threading
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

BOT_TOKEN       = os.environ.get("ECOM_BOT_TOKEN")
ADMIN_ID        = int(os.environ.get("ADMIN_ID", "0"))
BEACONS_SECRET  = os.environ.get("BEACONS_SECRET", "")   # Header secret Beacons (optionnel)
USERS_FILE      = "users_db.json"
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

def add_user(telegram_id: int, email: str = "", name: str = "", order_id: str = ""):
    db = load_db()
    uid = str(telegram_id)
    today = datetime.now().strftime("%Y-%m-%d")
    expiry = (datetime.now() + timedelta(days=SUBSCRIPTION_DAYS)).strftime("%Y-%m-%d")

    # Ajouter à la liste allowed si pas déjà présent
    if telegram_id not in db["allowed"]:
        db["allowed"].append(telegram_id)

    # Enregistrer l'abonnement (remplace si renouvellement)
    db["subscriptions"][uid] = {
        "telegram_id": telegram_id,
        "email":       email,
        "name":        name,
        "order_id":    order_id,
        "start_date":  today,
        "expiry_date": expiry,
        "notified_3d": False,   # notification à J-3
        "notified_1d": False,   # notification à J-1
        "active":      True,
    }
    _save_db(db)
    return expiry

def remove_user(telegram_id: int):
    db = load_db()
    uid = str(telegram_id)
    if telegram_id in db["allowed"]:
        db["allowed"].remove(telegram_id)
    if uid in db["subscriptions"]:
        db["subscriptions"][uid]["active"] = False
    _save_db(db)

def get_all_active():
    db = load_db()
    return {uid: sub for uid, sub in db["subscriptions"].items() if sub.get("active")}

# ============================================================
#  TELEGRAM HELPERS
# ============================================================

def tg_send(chat_id: int, text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        print(f"[TG] Erreur envoi {chat_id}: {e}")

def notify_admin(text: str):
    tg_send(ADMIN_ID, text)

# ============================================================
#  WEBHOOK BEACONS
# ============================================================

@app.route("/webhook/beacons", methods=["POST"])
def beacons_webhook():
    # Vérification du secret header (si configuré sur Beacons)
    if BEACONS_SECRET:
        received = request.headers.get("X-Beacons-Secret", "")
        if received != BEACONS_SECRET:
            return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    print(f"[BEACONS] Payload reçu : {json.dumps(data, indent=2)}")

    # ---- Parser le payload Beacons ----
    # Beacons envoie : event, order { id, buyer { email, name }, line_items [...], custom_fields [...] }
    event = data.get("event", "")

    # On traite uniquement les nouvelles commandes
    if event not in ("order.created", "order.paid", ""):
        return jsonify({"status": "ignored", "event": event}), 200

    order   = data.get("order", data)   # fallback si payload flat
    order_id = order.get("id", "N/A")
    buyer   = order.get("buyer", {})
    email   = buyer.get("email", "")
    name    = buyer.get("name", "")

    # Récupérer l'ID Telegram depuis les custom fields
    telegram_id = None
    for field in order.get("custom_fields", []):
        label = field.get("label", "").lower()
        if "telegram" in label or "id" in label:
            try:
                telegram_id = int(str(field.get("value", "")).strip())
            except ValueError:
                pass
            break

    if not telegram_id:
        notify_admin(
            f"⚠️ *Nouvelle commande sans ID Telegram*\n\n"
            f"• Commande : `{order_id}`\n"
            f"• Nom : {name}\n"
            f"• Email : {email}\n\n"
            f"Ajoute manuellement avec `/adduser [ID]`"
        )
        return jsonify({"status": "missing_telegram_id"}), 200

    expiry = add_user(telegram_id, email=email, name=name, order_id=order_id)

    # Notifier le client
    tg_send(telegram_id,
        f"✅ *Accès activé !*\n\n"
        f"Bonjour {name or 'toi'} ! Ton accès au Bot E-Commerce est maintenant actif.\n\n"
        f"📅 Expiration : *{expiry}*\n\n"
        f"Envoie /start pour commencer 🚀"
    )

    # Notifier l'admin
    notify_admin(
        f"🎉 *Nouvelle vente !*\n\n"
        f"• Nom : {name}\n"
        f"• Email : {email}\n"
        f"• ID Telegram : `{telegram_id}`\n"
        f"• Commande : `{order_id}`\n"
        f"• Expiration : {expiry}"
    )

    return jsonify({"status": "ok", "expiry": expiry}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running", "time": datetime.now().isoformat()}), 200


# ============================================================
#  SCHEDULER — vérifie les expirations chaque jour
# ============================================================

def check_expirations():
    """Lance la vérification quotidienne des abonnements"""
    import time

    def _run():
        while True:
            print(f"[SCHEDULER] Vérification expirations — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            try:
                _process_expirations()
            except Exception as e:
                print(f"[SCHEDULER] Erreur: {e}")
            # Attendre 24h
            time.sleep(86400)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _process_expirations():
    today = datetime.now().date()
    subs  = get_all_active()
    db    = load_db()

    for uid, sub in subs.items():
        telegram_id = sub["telegram_id"]
        name        = sub.get("name", "toi")
        expiry      = datetime.strptime(sub["expiry_date"], "%Y-%m-%d").date()
        days_left   = (expiry - today).days

        # ---- J-3 : premier rappel ----
        if days_left == 3 and not sub.get("notified_3d"):
            tg_send(telegram_id,
                f"⏰ *Ton accès expire dans 3 jours !*\n\n"
                f"📅 Date d'expiration : *{sub['expiry_date']}*\n\n"
                f"🔄 Pour continuer à utiliser le Bot E-Commerce, "
                f"renouvelle ton abonnement ici :\n"
                f"👉 [Renouveler maintenant](https://beacons.ai/ton-lien)\n\n"
                f"Des questions ? Contacte le support."
            )
            db["subscriptions"][uid]["notified_3d"] = True
            notify_admin(f"⏰ Rappel J-3 envoyé à {name} (ID: `{telegram_id}`)")

        # ---- J-1 : dernier rappel ----
        elif days_left == 1 and not sub.get("notified_1d"):
            tg_send(telegram_id,
                f"🚨 *Dernier rappel — accès expire demain !*\n\n"
                f"📅 Expiration : *{sub['expiry_date']}*\n\n"
                f"Ne perds pas l'accès à tes outils e-commerce !\n"
                f"🔄 [Renouveler maintenant](https://beacons.ai/ton-lien)\n\n"
                f"Après expiration, tu devras racheter l'accès."
            )
            db["subscriptions"][uid]["notified_1d"] = True
            notify_admin(f"🚨 Rappel J-1 envoyé à {name} (ID: `{telegram_id}`)")

        # ---- J=0 : expiration → suppression ----
        elif days_left <= 0 and sub.get("active"):
            remove_user(telegram_id)
            tg_send(telegram_id,
                f"❌ *Ton accès a expiré*\n\n"
                f"Ton abonnement au Bot E-Commerce est terminé.\n\n"
                f"🔄 Pour retrouver l'accès :\n"
                f"👉 [Renouveler ici](https://beacons.ai/ton-lien)\n\n"
                f"Merci d'avoir utilisé le bot ! 🙏"
            )
            notify_admin(
                f"🗑️ *Accès expiré et supprimé*\n\n"
                f"• Nom : {name}\n"
                f"• ID : `{telegram_id}`\n"
                f"• Expiré le : {sub['expiry_date']}"
            )

    _save_db(db)
    print(f"[SCHEDULER] Vérification terminée. {len(subs)} abonnements actifs traités.")


# ============================================================
#  LANCEMENT
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[WEBHOOK] Démarrage sur port {port}")
    check_expirations()   # lance le thread scheduler
    app.run(host="0.0.0.0", port=port)
