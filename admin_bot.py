"""
admin_bot.py
------------
Bot Telegram admin pour gérer les abonnements manuellement.
Commandes : /liste /adduser /removeuser /prolonger /info /stats
"""

import os
import json
import telebot
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN")   # token du bot admin (bot séparé)
ADMIN_ID        = int(os.environ.get("ADMIN_ID", "0"))
ECOM_BOT_TOKEN  = os.environ.get("ECOM_BOT_TOKEN")    # pour notifier les users via le bot principal
USERS_FILE      = "users_db.json"
SUBSCRIPTION_DAYS = 30

if not ADMIN_BOT_TOKEN:
    raise ValueError("❌ Variable ADMIN_BOT_TOKEN manquante !")

bot = telebot.TeleBot(ADMIN_BOT_TOKEN)

# ============================================================
#  HELPERS DB (partagé avec webhook_server.py)
# ============================================================

def load_db():
    if not os.path.exists(USERS_FILE):
        _save_db({"allowed": [], "subscriptions": {}})
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def _save_db(db):
    with open(USERS_FILE, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

def is_admin(uid):
    return uid == ADMIN_ID

def tg_notify_user(telegram_id: int, text: str):
    """Notifie un user via le bot principal (ecom bot)"""
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{ECOM_BOT_TOKEN}/sendMessage",
            json={"chat_id": telegram_id, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        print(f"Erreur notif user {telegram_id}: {e}")

def add_user_manual(telegram_id: int, name: str = "Manuel", days: int = SUBSCRIPTION_DAYS):
    db = load_db()
    uid = str(telegram_id)
    today  = datetime.now().strftime("%Y-%m-%d")
    expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

    if telegram_id not in db["allowed"]:
        db["allowed"].append(telegram_id)

    db["subscriptions"][uid] = {
        "telegram_id": telegram_id,
        "email":       "",
        "name":        name,
        "order_id":    "MANUEL",
        "start_date":  today,
        "expiry_date": expiry,
        "notified_3d": False,
        "notified_1d": False,
        "active":      True,
    }
    _save_db(db)
    return expiry

def remove_user_manual(telegram_id: int):
    db = load_db()
    uid = str(telegram_id)
    removed = False
    if telegram_id in db["allowed"]:
        db["allowed"].remove(telegram_id)
        removed = True
    if uid in db["subscriptions"]:
        db["subscriptions"][uid]["active"] = False
        removed = True
    _save_db(db)
    return removed

def extend_user(telegram_id: int, days: int):
    db = load_db()
    uid = str(telegram_id)
    if uid not in db["subscriptions"]:
        return None
    sub    = db["subscriptions"][uid]
    # Prolonger depuis aujourd'hui ou depuis l'expiry si dans le futur
    base   = max(datetime.now(), datetime.strptime(sub["expiry_date"], "%Y-%m-%d"))
    expiry = (base + timedelta(days=days)).strftime("%Y-%m-%d")
    db["subscriptions"][uid]["expiry_date"] = expiry
    db["subscriptions"][uid]["active"]      = True
    if telegram_id not in db["allowed"]:
        db["allowed"].append(telegram_id)
    _save_db(db)
    return expiry

# ============================================================
#  COMMANDES ADMIN
# ============================================================

@bot.message_handler(commands=["start", "help"])
def cmd_help(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Accès refusé."); return
    bot.reply_to(message,
        "🛠️ *Bot Admin — Gestion Abonnements*\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "👥 *UTILISATEURS*\n"
        "/liste — Tous les abonnés actifs\n"
        "/info [ID] — Détails d'un abonné\n"
        "/stats — Statistiques globales\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "✏️ *GESTION*\n"
        "/adduser [ID] — Ajouter 30 jours\n"
        "/adduser [ID] [jours] — Ajouter N jours\n"
        "/adduser [ID] [jours] [nom] — Avec nom\n"
        "/removeuser [ID] — Supprimer l'accès\n"
        "/prolonger [ID] [jours] — Prolonger\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📢 *COMMUNICATION*\n"
        "/message [ID] [texte] — Envoyer un message\n"
        "/broadcast [texte] — Message à tous\n",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["liste"])
def cmd_liste(message):
    if not is_admin(message.from_user.id): return
    db   = load_db()
    subs = {uid: s for uid, s in db["subscriptions"].items() if s.get("active")}

    if not subs:
        bot.reply_to(message, "📭 Aucun abonné actif."); return

    today = datetime.now().date()
    lines = [f"👥 *Abonnés actifs : {len(subs)}*\n"]
    for uid, sub in sorted(subs.items(), key=lambda x: x[1]["expiry_date"]):
        expiry    = datetime.strptime(sub["expiry_date"], "%Y-%m-%d").date()
        days_left = (expiry - today).days
        emoji     = "🔴" if days_left <= 3 else "🟡" if days_left <= 7 else "🟢"
        name      = sub.get("name", "—")[:20]
        lines.append(f"{emoji} `{uid}` — {name} — J-{days_left} ({sub['expiry_date']})")

    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["info"])
def cmd_info(message):
    if not is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage : /info [ID Telegram]"); return

    db  = load_db()
    uid = parts[1]
    sub = db["subscriptions"].get(uid)
    if not sub:
        bot.reply_to(message, f"❌ Aucun abonné avec l'ID `{uid}`.", parse_mode="Markdown"); return

    today     = datetime.now().date()
    expiry    = datetime.strptime(sub["expiry_date"], "%Y-%m-%d").date()
    days_left = (expiry - today).days
    status    = "✅ Actif" if sub.get("active") and days_left > 0 else "❌ Expiré"

    bot.reply_to(message,
        f"👤 *Fiche abonné*\n\n"
        f"• ID Telegram : `{uid}`\n"
        f"• Nom : {sub.get('name','—')}\n"
        f"• Email : {sub.get('email','—')}\n"
        f"• Commande : `{sub.get('order_id','—')}`\n"
        f"• Début : {sub.get('start_date','—')}\n"
        f"• Expiration : {sub['expiry_date']}\n"
        f"• Jours restants : *{days_left}j*\n"
        f"• Statut : {status}",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    if not is_admin(message.from_user.id): return
    db    = load_db()
    today = datetime.now().date()
    subs  = db["subscriptions"]

    total    = len(subs)
    actifs   = sum(1 for s in subs.values() if s.get("active"))
    expires  = sum(1 for s in subs.values() if s.get("active") and
                   (datetime.strptime(s["expiry_date"], "%Y-%m-%d").date() - today).days <= 0)
    soon     = sum(1 for s in subs.values() if s.get("active") and
                   0 < (datetime.strptime(s["expiry_date"], "%Y-%m-%d").date() - today).days <= 7)

    bot.reply_to(message,
        f"📊 *Statistiques*\n\n"
        f"• Total abonnés : {total}\n"
        f"• Actifs : {actifs}\n"
        f"• Expirent dans 7j : ⚠️ {soon}\n"
        f"• Expirés (à supprimer) : 🔴 {expires}\n"
        f"• Inactifs/supprimés : {total - actifs}",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["adduser"])
def cmd_adduser(message):
    if not is_admin(message.from_user.id): return
    parts = message.text.split()
    # /adduser ID [jours] [nom...]
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message,
            "Usage :\n"
            "/adduser [ID] — 30 jours par défaut\n"
            "/adduser [ID] [jours]\n"
            "/adduser [ID] [jours] [nom]"); return

    telegram_id = int(parts[1])
    days        = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else SUBSCRIPTION_DAYS
    name        = " ".join(parts[3:]) if len(parts) > 3 else "Manuel"

    expiry = add_user_manual(telegram_id, name=name, days=days)

    bot.reply_to(message,
        f"✅ Accès ajouté !\n\n"
        f"• ID : `{telegram_id}`\n"
        f"• Nom : {name}\n"
        f"• Durée : {days} jours\n"
        f"• Expiration : {expiry}",
        parse_mode="Markdown"
    )

    tg_notify_user(telegram_id,
        f"✅ *Accès activé !*\n\n"
        f"Ton accès au Bot E-Commerce est maintenant actif.\n"
        f"📅 Expiration : *{expiry}*\n\n"
        f"Envoie /start pour commencer 🚀"
    )


@bot.message_handler(commands=["removeuser"])
def cmd_removeuser(message):
    if not is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage : /removeuser [ID]"); return

    telegram_id = int(parts[1])
    ok = remove_user_manual(telegram_id)

    if ok:
        bot.reply_to(message, f"🗑️ Accès supprimé pour `{telegram_id}`.", parse_mode="Markdown")
        tg_notify_user(telegram_id,
            "❌ *Ton accès a été révoqué.*\n\n"
            "Contacte le support si tu penses que c'est une erreur."
        )
    else:
        bot.reply_to(message, f"❌ ID `{telegram_id}` introuvable.", parse_mode="Markdown")


@bot.message_handler(commands=["prolonger"])
def cmd_prolonger(message):
    if not is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        bot.reply_to(message, "Usage : /prolonger [ID] [jours]\nEx : /prolonger 123456789 30"); return

    telegram_id = int(parts[1])
    days        = int(parts[2])
    expiry = extend_user(telegram_id, days)

    if expiry:
        bot.reply_to(message,
            f"✅ Prolongé de {days} jours.\n"
            f"• ID : `{telegram_id}`\n"
            f"• Nouvelle expiration : *{expiry}*",
            parse_mode="Markdown"
        )
        tg_notify_user(telegram_id,
            f"🎉 *Ton abonnement a été prolongé !*\n\n"
            f"📅 Nouvelle expiration : *{expiry}*\n\n"
            f"Continue à utiliser le bot sans interruption 🚀"
        )
    else:
        bot.reply_to(message, f"❌ ID `{telegram_id}` introuvable.", parse_mode="Markdown")


@bot.message_handler(commands=["message"])
def cmd_message(message):
    if not is_admin(message.from_user.id): return
    parts = message.text.split(" ", 2)
    if len(parts) < 3 or not parts[1].isdigit():
        bot.reply_to(message, "Usage : /message [ID] [texte]"); return

    telegram_id = int(parts[1])
    texte       = parts[2]
    tg_notify_user(telegram_id, f"📩 *Message du support :*\n\n{texte}")
    bot.reply_to(message, f"✅ Message envoyé à `{telegram_id}`.", parse_mode="Markdown")


@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if not is_admin(message.from_user.id): return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /broadcast [texte]"); return

    texte = parts[1]
    db    = load_db()
    subs  = [s for s in db["subscriptions"].values() if s.get("active")]

    bot.reply_to(message, f"📢 Envoi à {len(subs)} abonnés...")
    ok, fail = 0, 0
    for sub in subs:
        try:
            tg_notify_user(sub["telegram_id"], f"📢 *Annonce :*\n\n{texte}")
            ok += 1
        except:
            fail += 1

    bot.send_message(message.chat.id,
        f"✅ Broadcast terminé.\n• Envoyés : {ok}\n• Échecs : {fail}",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: True)
def fallback(message):
    if not is_admin(message.from_user.id): return
    bot.reply_to(message, "❓ Commande inconnue. Envoie /help.")


# ============================================================
#  LANCEMENT
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  BOT ADMIN DÉMARRÉ")
    print(f"  Admin ID : {ADMIN_ID}")
    print("=" * 50)
    bot.infinity_polling()
