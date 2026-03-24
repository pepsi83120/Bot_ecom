import telebot
import json
import os
import schedule
import time
import threading
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv(r"C:\Users\leoqu\Desktop\.env")

# ============================================================
#  CONFIGURATION
# ============================================================
BOT_TOKEN    = os.environ.get("CRM_BOT_TOKEN")
ADMIN_ID     = int(os.environ.get("ADMIN_ID", "0"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not BOT_TOKEN:
    raise ValueError("❌ Variable CRM_BOT_TOKEN manquante !")
if not GROQ_API_KEY:
    raise ValueError("❌ Variable GROQ_API_KEY manquante !")

bot = telebot.TeleBot(BOT_TOKEN)

USERS_FILE    = "crm_users.json"
PROSPECTS_FILE = "prospects.json"

# Statuts pipeline dans l'ordre
STATUTS = ["Contacté", "Intéressé", "Hésitation", "Converti", "Perdu"]
STATUTS_EMOJI = {
    "Contacté":  "📨",
    "Intéressé": "🔥",
    "Hésitation":"⚠️",
    "Converti":  "💰",
    "Perdu":     "❌"
}

OBJECTIONS = [
    "Trop cher",
    "Pas le bon moment",
    "Pas confiance",
    "Besoin de réfléchir",
    "Pas convaincu du résultat",
    "Autre"
]

THEMES_FORMATIONS = ["E-commerce", "Trading", "Marketing digital", "Autre"]

# ============================================================
#  GESTION UTILISATEURS
# ============================================================

def load_users():
    if not os.path.exists(USERS_FILE):
        save_users([])
    with open(USERS_FILE, "r") as f:
        return json.load(f).get("allowed", [])

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump({"allowed": users}, f, indent=2)

def is_admin(uid):      return uid == ADMIN_ID
def is_authorized(uid): return is_admin(uid) or uid in load_users()

def notify_unauthorized(message):
    if not ADMIN_ID:
        return
    user = message.from_user
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    try:
        bot.send_message(
            ADMIN_ID,
            f"⚠️ *Tentative d'accès non autorisé*\n\n"
            f"👤 {user.first_name or ''} {user.last_name or ''} (@{user.username or 'aucun'})\n"
            f"🆔 ID : `{user.id}`\n"
            f"💬 Message : `{message.text or '(non-texte)'}`\n"
            f"🕐 {now}\n\n"
            f"➡️ Pour autoriser : `/adduser {user.id}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Erreur notification admin : {e}")

# ============================================================
#  GESTION PROSPECTS (CRM)
# ============================================================

def load_prospects():
    if not os.path.exists(PROSPECTS_FILE):
        return {}
    with open(PROSPECTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_prospects(data):
    with open(PROSPECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_prospect(pseudo):
    return load_prospects().get(pseudo.lower().strip("@"))

def upsert_prospect(pseudo, data):
    prospects = load_prospects()
    key = pseudo.lower().strip("@")
    prospects[key] = data
    save_prospects(prospects)

def delete_prospect(pseudo):
    prospects = load_prospects()
    key = pseudo.lower().strip("@")
    if key in prospects:
        del prospects[key]
        save_prospects(prospects)
        return True
    return False

def tous_prospects():
    return load_prospects()

def prospect_card(pseudo, p):
    """Retourne une fiche prospect formatée"""
    statut = p.get("statut", "Contacté")
    emoji = STATUTS_EMOJI.get(statut, "📨")
    jours = ""
    if p.get("derniere_action"):
        try:
            d = datetime.strptime(p["derniere_action"], "%d/%m/%Y")
            delta = (datetime.now() - d).days
            jours = f" (il y a {delta}j)"
        except: pass
    notes = p.get("notes", "")
    score = p.get("score", 0)
    etoiles = "⭐" * min(score, 5) if score else ""
    return (
        f"{emoji} *@{pseudo}*  {etoiles}\n"
        f"📚 Formation : {p.get('theme', 'N/A')}\n"
        f"💬 Objection : {p.get('objection', 'N/A')}\n"
        f"📊 Statut : *{statut}*{jours}\n"
        f"💰 Budget : {p.get('budget', 'N/A')}\n"
        + (f"📝 Notes : _{notes}_\n" if notes else "")
        + f"📅 Ajouté le : {p.get('date_ajout', 'N/A')}"
    )

# ============================================================
#  IA — GROQ
# ============================================================

def ask_groq(prompt, system=None, max_tokens=800):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": messages, "max_tokens": max_tokens, "temperature": 0.8},
            timeout=30
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Erreur Groq : {e}")
        return None

def generer_message_relance(pseudo, prospect):
    system = (
        "Tu es un expert en vente et closing pour des formations en ligne. "
        "Tu génères des messages DM Instagram/TikTok naturels, courts (5-8 lignes max), "
        "chaleureux et personnalisés. Pas de spam, pas de pression excessive. "
        "Le but est de relancer la conversation et lever l'objection subtilement. "
        "Réponds uniquement avec le message, sans explication."
    )
    prompt = (
        f"Génère un message de relance DM pour ce prospect :\n"
        f"- Pseudo : @{pseudo}\n"
        f"- Formation intéressé : {prospect.get('theme', 'formation en ligne')}\n"
        f"- Son objection principale : {prospect.get('objection', 'hésitation')}\n"
        f"- Statut actuel : {prospect.get('statut', 'Hésitation')}\n"
        f"- Notes : {prospect.get('notes', 'aucune')}\n\n"
        f"Le message doit lever l'objection sans être agressif, "
        f"créer de la confiance et inciter à reprendre la conversation."
    )
    return ask_groq(prompt, system)

def generer_pitch(pseudo, prospect):
    system = (
        "Tu es un expert en vente de formations en ligne. "
        "Tu génères des pitchs de vente courts, percutants et personnalisés pour DM. "
        "Maximum 8 lignes. Naturel, pas robotique."
    )
    prompt = (
        f"Génère un pitch de vente pour convaincre ce prospect d'acheter :\n"
        f"- Pseudo : @{pseudo}\n"
        f"- Formation : {prospect.get('theme', 'formation en ligne')}\n"
        f"- Budget estimé : {prospect.get('budget', 'inconnu')}\n"
        f"- Objection : {prospect.get('objection', 'aucune')}\n"
        f"- Notes : {prospect.get('notes', 'aucune')}\n\n"
        f"Mets en avant la transformation, la valeur, et lève l'objection."
    )
    return ask_groq(prompt, system)

def generer_analyse_pipeline():
    prospects = tous_prospects()
    if not prospects:
        return None
    system = (
        "Tu es un consultant en vente spécialisé en formations en ligne. "
        "Tu analyses un pipeline de prospection et donnes des conseils actionnables. "
        "Sois direct, concret, court (max 15 lignes)."
    )
    resume = []
    for pseudo, p in prospects.items():
        resume.append(f"@{pseudo} | {p.get('statut')} | {p.get('theme')} | objection: {p.get('objection')} | {p.get('derniere_action','?')}")
    prompt = (
        f"Voici mon pipeline de prospection ({len(prospects)} prospects) :\n\n"
        + "\n".join(resume)
        + "\n\nDonne-moi :\n"
        "1. Les 3 prospects les plus chauds à contacter EN PREMIER\n"
        "2. Les prospects à risque de partir (à relancer d'urgence)\n"
        "3. 3 conseils concrets pour améliorer mes conversions\n"
        "4. Mon taux de conversion estimé et comment l'améliorer"
    )
    return ask_groq(prompt, system, max_tokens=1000)

def generer_script_closing(pseudo, prospect):
    system = (
        "Tu es un expert en closing téléphonique et DM pour des formations en ligne. "
        "Tu génères des scripts de closing courts et naturels. Max 12 lignes."
    )
    prompt = (
        f"Génère un script de closing complet pour ce prospect :\n"
        f"- @{pseudo} | Formation : {prospect.get('theme')}\n"
        f"- Objection : {prospect.get('objection')}\n"
        f"- Budget : {prospect.get('budget', 'inconnu')}\n"
        f"- Notes : {prospect.get('notes', 'aucune')}\n\n"
        "Inclus : ouverture, reformulation du besoin, réponse à l'objection, closing avec urgence douce."
    )
    return ask_groq(prompt, system, max_tokens=900)

def generer_conseil_quotidien():
    system = "Tu es un coach en vente de formations en ligne. Donne un conseil actionnable du jour en 4-5 lignes max. Direct et motivant."
    prompt = "Donne un conseil de vente/prospection du jour pour quelqu'un qui vend des formations en ligne via DM Instagram/TikTok."
    return ask_groq(prompt, system, max_tokens=300)

# ============================================================
#  STATS
# ============================================================

def calculer_stats():
    prospects = tous_prospects()
    total = len(prospects)
    if total == 0:
        return None
    par_statut = {s: 0 for s in STATUTS}
    revenus_estimes = 0
    this_month = datetime.now().strftime("%m/%Y")
    convertis_mois = 0

    for p in prospects.values():
        s = p.get("statut", "Contacté")
        par_statut[s] = par_statut.get(s, 0) + 1
        if s == "Converti":
            budget = p.get("budget", "0").replace("€","").replace(" ","").split("-")[0]
            try: revenus_estimes += int(budget)
            except: pass
            if p.get("date_conversion", "").endswith(this_month):
                convertis_mois += 1

    convertis = par_statut.get("Converti", 0)
    perdus = par_statut.get("Perdu", 0)
    actifs = total - perdus
    taux = round((convertis / actifs * 100), 1) if actifs > 0 else 0

    return {
        "total": total,
        "par_statut": par_statut,
        "taux_conversion": taux,
        "revenus_estimes": revenus_estimes,
        "convertis_mois": convertis_mois,
        "actifs": actifs
    }

# ============================================================
#  RAPPELS QUOTIDIENS
# ============================================================

def rappel_quotidien():
    if not ADMIN_ID:
        return
    prospects = tous_prospects()
    a_relancer = []
    urgents = []

    for pseudo, p in prospects.items():
        if p.get("statut") in ["Perdu", "Converti"]:
            continue
        if p.get("derniere_action"):
            try:
                d = datetime.strptime(p["derniere_action"], "%d/%m/%Y")
                delta = (datetime.now() - d).days
                if delta >= 7:
                    urgents.append((pseudo, p, delta))
                elif delta >= 3:
                    a_relancer.append((pseudo, p, delta))
            except: pass

    if not a_relancer and not urgents:
        conseil = generer_conseil_quotidien()
        try:
            bot.send_message(
                ADMIN_ID,
                f"☀️ *Bonjour ! Rien à relancer aujourd'hui.*\n\n"
                f"💡 *Conseil du jour :*\n{conseil or 'Continue comme ça !'}",
                parse_mode="Markdown"
            )
        except: pass
        return

    lines = [f"☀️ *Rappel prospection du {datetime.now().strftime('%d/%m/%Y')}*\n"]

    if urgents:
        lines.append("🚨 *URGENT — Sans nouvelles depuis +7 jours :*")
        for pseudo, p, delta in urgents[:5]:
            lines.append(f"  • @{pseudo} ({p.get('statut')}) — {delta} jours\n    👉 /relance @{pseudo}")
        lines.append("")

    if a_relancer:
        lines.append("⚠️ *À relancer (3-7 jours) :*")
        for pseudo, p, delta in a_relancer[:5]:
            lines.append(f"  • @{pseudo} ({p.get('statut')}) — {delta} jours\n    👉 /relance @{pseudo}")
        lines.append("")

    conseil = generer_conseil_quotidien()
    if conseil:
        lines.append(f"💡 *Conseil du jour :*\n{conseil}")

    try:
        bot.send_message(ADMIN_ID, "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        print(f"Erreur rappel : {e}")

def run_scheduler():
    schedule.every().day.at("08:00").do(rappel_quotidien)
    while True:
        schedule.run_pending()
        time.sleep(60)

# ============================================================
#  ÉTAPES D'AJOUT D'UN PROSPECT
# ============================================================

user_states = {}  # stocke l'état de conversation par user

def start_add_prospect(message, pseudo):
    uid = message.from_user.id
    user_states[uid] = {"step": "theme", "pseudo": pseudo.strip("@").lower()}
    themes_str = "\n".join([f"{i+1}. {t}" for i, t in enumerate(THEMES_FORMATIONS)])
    msg = bot.reply_to(message,
        f"➕ *Ajout de @{pseudo}*\n\n"
        f"Quelle formation l'intéresse ?\n{themes_str}\n\n"
        "_Réponds avec le numéro ou le nom_",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, step_theme)

def step_theme(message):
    uid = message.from_user.id
    state = user_states.get(uid, {})
    texte = message.text.strip()
    theme = texte
    try:
        idx = int(texte) - 1
        if 0 <= idx < len(THEMES_FORMATIONS):
            theme = THEMES_FORMATIONS[idx]
    except: pass
    state["theme"] = theme

    objections_str = "\n".join([f"{i+1}. {o}" for i, o in enumerate(OBJECTIONS)])
    msg = bot.reply_to(message,
        f"Son objection principale ?\n{objections_str}\n\n_Réponds avec le numéro_",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, step_objection)
    user_states[uid] = state

def step_objection(message):
    uid = message.from_user.id
    state = user_states.get(uid, {})
    texte = message.text.strip()
    objection = texte
    try:
        idx = int(texte) - 1
        if 0 <= idx < len(OBJECTIONS):
            objection = OBJECTIONS[idx]
    except: pass
    state["objection"] = objection

    msg = bot.reply_to(message,
        "Son budget estimé ?\n_Ex : 500€, 200-500€, inconnu_",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, step_budget)
    user_states[uid] = state

def step_budget(message):
    uid = message.from_user.id
    state = user_states.get(uid, {})
    state["budget"] = message.text.strip()

    msg = bot.reply_to(message,
        "Note rapide sur ce prospect ?\n_Ex : très motivé, a déjà acheté une formation, méfiant..._\n\n"
        "_Envoie 'non' pour passer_",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, step_notes)
    user_states[uid] = state

def step_notes(message):
    uid = message.from_user.id
    state = user_states.get(uid, {})
    notes = message.text.strip()
    state["notes"] = "" if notes.lower() == "non" else notes

    # Score automatique
    score = 1
    if state.get("objection") in ["Besoin de réfléchir", "Pas le bon moment"]: score = 3
    if state.get("objection") in ["Trop cher"]: score = 2
    if "motivé" in state.get("notes","").lower(): score += 1
    if state.get("budget", "inconnu") != "inconnu": score += 1

    now = datetime.now().strftime("%d/%m/%Y")
    prospect = {
        "theme": state["theme"],
        "objection": state["objection"],
        "budget": state["budget"],
        "notes": state["notes"],
        "statut": "Contacté",
        "score": min(score, 5),
        "date_ajout": now,
        "derniere_action": now,
        "historique": [f"{now} — Prospect ajouté"]
    }
    pseudo = state["pseudo"]
    upsert_prospect(pseudo, prospect)
    user_states.pop(uid, None)

    etoiles = "⭐" * prospect["score"]
    bot.reply_to(message,
        f"✅ *@{pseudo} ajouté !*\n\n"
        + prospect_card(pseudo, prospect) + f"\n\n"
        f"Score de chaleur : {etoiles}\n\n"
        f"👉 /relance @{pseudo} — Générer un message\n"
        f"👉 /avance @{pseudo} — Faire avancer dans le pipeline",
        parse_mode="Markdown"
    )

# ============================================================
#  COMMANDES TELEGRAM
# ============================================================

@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    stats = calculer_stats()
    resume = ""
    if stats:
        resume = (
            f"\n📊 Pipeline : *{stats['total']}* prospects | "
            f"Taux : *{stats['taux_conversion']}%* | "
            f"Revenus estimés : *{stats['revenus_estimes']}€*\n"
        )
    bot.reply_to(message,
        "💼 *CRM Prospection — Bot Commercial*\n"
        + resume +
        "\n━━━━━━━━━━━━━━━━\n"
        "➕ *GÉRER LES PROSPECTS*\n"
        "/add @pseudo — Ajouter un prospect\n"
        "/fiche @pseudo — Voir la fiche complète\n"
        "/edit @pseudo — Modifier un prospect\n"
        "/del @pseudo — Supprimer un prospect\n"
        "/note @pseudo [texte] — Ajouter une note\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📋 *PIPELINE*\n"
        "/pipeline — Vue globale par statut\n"
        "/avance @pseudo — Passer au statut suivant\n"
        "/statut @pseudo — Changer le statut\n"
        "/chauds — Top prospects à contacter\n"
        "/relancer — Liste des prospects à relancer\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🤖 *IA — MESSAGES*\n"
        "/relance @pseudo — Générer un DM de relance\n"
        "/pitch @pseudo — Générer un pitch de vente\n"
        "/closing @pseudo — Script de closing complet\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📊 *STATS & ANALYSE*\n"
        "/stats — Statistiques complètes\n"
        "/analyse — Analyse IA de ton pipeline\n"
        "/conseil — Conseil du jour\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "⚙️ *ADMIN*\n"
        "/adduser ID — Autoriser un utilisateur\n"
        "/myid — Ton ID Telegram\n",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["add"])
def cmd_add(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /add @pseudo\nEx : /add @jean_dupont"); return
    pseudo = parts[1].strip("@").lower()
    if get_prospect(pseudo):
        bot.reply_to(message,
            f"ℹ️ @{pseudo} existe déjà.\n"
            f"👉 /fiche @{pseudo} pour le voir\n"
            f"👉 /edit @{pseudo} pour le modifier"
        ); return
    start_add_prospect(message, pseudo)


@bot.message_handler(commands=["fiche"])
def cmd_fiche(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /fiche @pseudo"); return
    pseudo = parts[1].strip("@").lower()
    p = get_prospect(pseudo)
    if not p:
        bot.reply_to(message, f"❌ @{pseudo} introuvable. Utilise /add @{pseudo} pour l'ajouter."); return

    historique = p.get("historique", [])
    histo_str = "\n".join([f"  • {h}" for h in historique[-5:]]) if historique else "  Aucun"

    bot.reply_to(message,
        prospect_card(pseudo, p) + f"\n\n"
        f"📖 *Historique (5 derniers) :*\n{histo_str}\n\n"
        f"👉 /relance @{pseudo}\n"
        f"👉 /pitch @{pseudo}\n"
        f"👉 /avance @{pseudo}",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["note"])
def cmd_note(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    parts = message.text.split(None, 2)
    if len(parts) < 3:
        bot.reply_to(message, "Usage : /note @pseudo [texte]\nEx : /note @jean très motivé, rappeler jeudi"); return
    pseudo = parts[1].strip("@").lower()
    note = parts[2]
    p = get_prospect(pseudo)
    if not p:
        bot.reply_to(message, f"❌ @{pseudo} introuvable."); return
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    p["notes"] = (p.get("notes", "") + f"\n[{now}] {note}").strip()
    p.setdefault("historique", []).append(f"{now} — Note : {note[:50]}")
    p["derniere_action"] = datetime.now().strftime("%d/%m/%Y")
    upsert_prospect(pseudo, p)
    bot.reply_to(message, f"✅ Note ajoutée pour @{pseudo}.")


@bot.message_handler(commands=["del"])
def cmd_del(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /del @pseudo"); return
    pseudo = parts[1].strip("@").lower()
    if delete_prospect(pseudo):
        bot.reply_to(message, f"🗑️ @{pseudo} supprimé.")
    else:
        bot.reply_to(message, f"❌ @{pseudo} introuvable.")


@bot.message_handler(commands=["pipeline"])
def cmd_pipeline(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    prospects = tous_prospects()
    if not prospects:
        bot.reply_to(message, "📭 Aucun prospect. Commence avec /add @pseudo"); return

    lines = ["📋 *PIPELINE DE PROSPECTION*\n"]
    for statut in STATUTS:
        emoji = STATUTS_EMOJI[statut]
        groupe = [(ps, p) for ps, p in prospects.items() if p.get("statut") == statut]
        lines.append(f"{emoji} *{statut}* ({len(groupe)})")
        for ps, p in groupe:
            score_str = "⭐" * p.get("score", 0)
            lines.append(f"  • @{ps} — {p.get('theme','?')} {score_str}")
        if not groupe:
            lines.append("  _Aucun_")
        lines.append("")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["avance"])
def cmd_avance(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /avance @pseudo"); return
    pseudo = parts[1].strip("@").lower()
    p = get_prospect(pseudo)
    if not p:
        bot.reply_to(message, f"❌ @{pseudo} introuvable."); return
    statut_actuel = p.get("statut", "Contacté")
    idx = STATUTS.index(statut_actuel) if statut_actuel in STATUTS else 0
    if idx >= len(STATUTS) - 1:
        bot.reply_to(message, f"ℹ️ @{pseudo} est déjà au statut final : *{statut_actuel}*", parse_mode="Markdown"); return
    nouveau_statut = STATUTS[idx + 1]
    now = datetime.now().strftime("%d/%m/%Y")
    p["statut"] = nouveau_statut
    p["derniere_action"] = now
    p.setdefault("historique", []).append(f"{now} — Statut → {nouveau_statut}")
    if nouveau_statut == "Converti":
        p["date_conversion"] = now
    upsert_prospect(pseudo, p)
    emoji = STATUTS_EMOJI.get(nouveau_statut, "")
    bot.reply_to(message,
        f"✅ @{pseudo} avancé !\n\n"
        f"{STATUTS_EMOJI.get(statut_actuel,'')} {statut_actuel} → {emoji} *{nouveau_statut}*",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["statut"])
def cmd_statut(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    parts = message.text.split()
    if len(parts) < 3:
        statuts_str = " | ".join(STATUTS)
        bot.reply_to(message, f"Usage : /statut @pseudo [statut]\nStatuts : {statuts_str}"); return
    pseudo = parts[1].strip("@").lower()
    nouveau = " ".join(parts[2:])
    # Recherche flexible
    match = next((s for s in STATUTS if s.lower() == nouveau.lower()), None)
    if not match:
        bot.reply_to(message, f"❌ Statut invalide.\nStatuts disponibles : {' | '.join(STATUTS)}"); return
    p = get_prospect(pseudo)
    if not p:
        bot.reply_to(message, f"❌ @{pseudo} introuvable."); return
    now = datetime.now().strftime("%d/%m/%Y")
    ancien = p.get("statut")
    p["statut"] = match
    p["derniere_action"] = now
    p.setdefault("historique", []).append(f"{now} — Statut changé : {ancien} → {match}")
    if match == "Converti":
        p["date_conversion"] = now
    upsert_prospect(pseudo, p)
    bot.reply_to(message,
        f"✅ Statut de @{pseudo} mis à jour :\n"
        f"{STATUTS_EMOJI.get(ancien,'')} {ancien} → {STATUTS_EMOJI.get(match,'')} *{match}*",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["chauds"])
def cmd_chauds(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    prospects = tous_prospects()
    chauds = [(ps, p) for ps, p in prospects.items()
              if p.get("statut") not in ["Converti", "Perdu"]]
    chauds.sort(key=lambda x: x[1].get("score", 0), reverse=True)
    if not chauds:
        bot.reply_to(message, "📭 Aucun prospect actif."); return
    lines = ["🔥 *TOP PROSPECTS CHAUDS*\n"]
    for ps, p in chauds[:8]:
        score = "⭐" * p.get("score", 0)
        emoji = STATUTS_EMOJI.get(p.get("statut",""), "")
        lines.append(
            f"{score} *@{ps}*\n"
            f"  {emoji} {p.get('statut')} | {p.get('theme')} | {p.get('budget','?')}\n"
            f"  Objection : {p.get('objection','?')}\n"
            f"  👉 /relance @{ps}\n"
        )
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["relancer"])
def cmd_relancer(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    prospects = tous_prospects()
    a_relancer = []
    for ps, p in prospects.items():
        if p.get("statut") in ["Converti", "Perdu"]:
            continue
        if p.get("derniere_action"):
            try:
                d = datetime.strptime(p["derniere_action"], "%d/%m/%Y")
                delta = (datetime.now() - d).days
                if delta >= 2:
                    a_relancer.append((ps, p, delta))
            except: pass
    if not a_relancer:
        bot.reply_to(message, "✅ Tout est à jour, aucun prospect à relancer !"); return
    a_relancer.sort(key=lambda x: x[2], reverse=True)
    lines = [f"⚠️ *PROSPECTS À RELANCER ({len(a_relancer)})*\n"]
    for ps, p, delta in a_relancer[:10]:
        urgence = "🚨" if delta >= 7 else "⚠️"
        lines.append(
            f"{urgence} *@{ps}* — {delta} jours sans contact\n"
            f"  {STATUTS_EMOJI.get(p.get('statut'),'')} {p.get('statut')} | {p.get('theme')}\n"
            f"  👉 /relance @{ps}\n"
        )
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["relance"])
def cmd_relance(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /relance @pseudo"); return
    pseudo = parts[1].strip("@").lower()
    p = get_prospect(pseudo)
    if not p:
        bot.reply_to(message, f"❌ @{pseudo} introuvable."); return
    bot.reply_to(message, f"⏳ Génération du message de relance pour @{pseudo}...")
    msg = generer_message_relance(pseudo, p)
    if msg:
        now = datetime.now().strftime("%d/%m/%Y")
        p.setdefault("historique", []).append(f"{now} — Message de relance généré")
        p["derniere_action"] = now
        upsert_prospect(pseudo, p)
        bot.reply_to(message,
            f"💬 *Message de relance pour @{pseudo}*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{msg}\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"_Copie ce message et envoie-le en DM_\n"
            f"👉 /avance @{pseudo} après l'avoir envoyé",
            parse_mode="Markdown"
        )
    else:
        bot.reply_to(message, "❌ Erreur génération. Réessaie.")


@bot.message_handler(commands=["pitch"])
def cmd_pitch(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /pitch @pseudo"); return
    pseudo = parts[1].strip("@").lower()
    p = get_prospect(pseudo)
    if not p:
        bot.reply_to(message, f"❌ @{pseudo} introuvable."); return
    bot.reply_to(message, f"⏳ Génération du pitch pour @{pseudo}...")
    msg = generer_pitch(pseudo, p)
    if msg:
        now = datetime.now().strftime("%d/%m/%Y")
        p.setdefault("historique", []).append(f"{now} — Pitch généré")
        upsert_prospect(pseudo, p)
        bot.reply_to(message,
            f"🎯 *Pitch de vente pour @{pseudo}*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{msg}\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"_Adapte et envoie en DM !_",
            parse_mode="Markdown"
        )
    else:
        bot.reply_to(message, "❌ Erreur génération. Réessaie.")


@bot.message_handler(commands=["closing"])
def cmd_closing(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /closing @pseudo"); return
    pseudo = parts[1].strip("@").lower()
    p = get_prospect(pseudo)
    if not p:
        bot.reply_to(message, f"❌ @{pseudo} introuvable."); return
    bot.reply_to(message, f"⏳ Génération du script de closing pour @{pseudo}...")
    msg = generer_script_closing(pseudo, p)
    if msg:
        now = datetime.now().strftime("%d/%m/%Y")
        p.setdefault("historique", []).append(f"{now} — Script closing généré")
        upsert_prospect(pseudo, p)
        bot.reply_to(message,
            f"🔐 *Script de closing pour @{pseudo}*\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{msg}\n"
            f"━━━━━━━━━━━━━━━━",
            parse_mode="Markdown"
        )
    else:
        bot.reply_to(message, "❌ Erreur génération. Réessaie.")


@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    stats = calculer_stats()
    if not stats:
        bot.reply_to(message, "📭 Aucun prospect. Commence avec /add @pseudo"); return
    lines = ["📊 *STATISTIQUES CRM*\n"]
    lines.append(f"👥 Total prospects : *{stats['total']}*")
    lines.append(f"✅ Actifs : *{stats['actifs']}*")
    lines.append(f"📈 Taux de conversion : *{stats['taux_conversion']}%*")
    lines.append(f"💰 Revenus estimés : *{stats['revenus_estimes']}€*")
    lines.append(f"🏆 Convertis ce mois : *{stats['convertis_mois']}*\n")
    lines.append("*Répartition pipeline :*")
    for statut in STATUTS:
        emoji = STATUTS_EMOJI[statut]
        n = stats["par_statut"].get(statut, 0)
        barre = "█" * n + "░" * max(0, 10-n)
        lines.append(f"{emoji} {statut} : *{n}* {barre}")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["analyse"])
def cmd_analyse(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    prospects = tous_prospects()
    if not prospects:
        bot.reply_to(message, "📭 Aucun prospect à analyser."); return
    bot.reply_to(message, "⏳ Analyse IA de ton pipeline en cours...")
    analyse = generer_analyse_pipeline()
    if analyse:
        bot.reply_to(message,
            f"🧠 *ANALYSE IA DE TON PIPELINE*\n\n{analyse}",
            parse_mode="Markdown"
        )
    else:
        bot.reply_to(message, "❌ Erreur analyse. Réessaie.")


@bot.message_handler(commands=["conseil"])
def cmd_conseil(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    bot.reply_to(message, "⏳ Génération du conseil...")
    conseil = generer_conseil_quotidien()
    if conseil:
        bot.reply_to(message, f"💡 *Conseil du jour*\n\n{conseil}", parse_mode="Markdown")
    else:
        bot.reply_to(message, "❌ Erreur. Réessaie.")


@bot.message_handler(commands=["edit"])
def cmd_edit(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /edit @pseudo"); return
    pseudo = parts[1].strip("@").lower()
    p = get_prospect(pseudo)
    if not p:
        bot.reply_to(message, f"❌ @{pseudo} introuvable."); return
    # Relancer le flow d'ajout avec les données existantes
    bot.reply_to(message, f"✏️ Modification de @{pseudo} — réponds aux questions pour mettre à jour.")
    start_add_prospect(message, pseudo)


@bot.message_handler(commands=["adduser"])
def cmd_adduser(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Admin seulement."); return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage : /adduser ID"); return
    uid = int(parts[1])
    users = load_users()
    if uid in users:
        bot.reply_to(message, "ℹ️ Déjà autorisé."); return
    users.append(uid); save_users(users)
    bot.reply_to(message, f"✅ {uid} ajouté.")
    try: bot.send_message(uid, "✅ Accès accordé ! Envoie /start")
    except: pass


@bot.message_handler(commands=["removeuser"])
def cmd_removeuser(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Admin seulement."); return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage : /removeuser ID"); return
    uid = int(parts[1])
    users = load_users()
    if uid not in users:
        bot.reply_to(message, "ℹ️ Pas dans la liste."); return
    users.remove(uid); save_users(users)
    bot.reply_to(message, f"🗑️ {uid} retiré.")


@bot.message_handler(commands=["myid"])
def cmd_myid(message):
    bot.reply_to(message, f"Ton ID : `{message.from_user.id}`", parse_mode="Markdown")


@bot.message_handler(func=lambda m: True)
def handle_unknown(message):
    if not is_authorized(message.from_user.id):
        notify_unauthorized(message)
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    bot.reply_to(message, "❓ Commande inconnue. Envoie /help.")


# ============================================================
#  LANCEMENT
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  BOT CRM PROSPECTION DÉMARRÉ")
    print(f"  Admin : {ADMIN_ID}")
    print("=" * 50)

    # Rappel quotidien dans un thread séparé
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    bot.infinity_polling()
