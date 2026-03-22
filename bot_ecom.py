import telebot
import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# ============================================================
#  CONFIGURATION
# ============================================================
BOT_TOKEN    = os.environ.get("ECOM_BOT_TOKEN")
ADMIN_ID     = int(os.environ.get("ADMIN_ID", "0"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not BOT_TOKEN:
    raise ValueError("❌ Variable ECOM_BOT_TOKEN manquante !")
if not GROQ_API_KEY:
    raise ValueError("❌ Variable GROQ_API_KEY manquante !")

bot = telebot.TeleBot(BOT_TOKEN)

USERS_FILE   = "ecom_users.json"
PROFILE_FILE = "ecom_profiles.json"

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

def load_profiles():
    if not os.path.exists(PROFILE_FILE):
        return {}
    with open(PROFILE_FILE, "r") as f:
        return json.load(f)

def save_profiles(profiles):
    with open(PROFILE_FILE, "w") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)

def get_profile(uid):
    return load_profiles().get(str(uid), {})

def save_profile(uid, profile):
    profiles = load_profiles()
    profiles[str(uid)] = profile
    save_profiles(profiles)


# ============================================================
#  APPEL GROQ API
# ============================================================

def ask_groq(prompt, system=None):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type":  "application/json"
            },
            json={
                "model":       "llama-3.3-70b-versatile",
                "messages":    messages,
                "max_tokens":  2000,
                "temperature": 0.8,
            },
            timeout=40
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Erreur Groq : {e}")
        return None

def get_system(profile):
    niche  = profile.get("niche", "e-commerce généraliste")
    cible  = profile.get("cible", "acheteurs en ligne 18-45 ans")
    pays   = profile.get("pays", "France")
    budget = profile.get("budget_ads", "500€/mois")
    return (
        f"Tu es un expert e-commerce spécialisé en dropshipping et Shopify. "
        f"Niche du store : {niche}. Cible : {cible}. Marché : {pays}. Budget ads : {budget}. "
        f"Plateformes : TikTok Ads et Facebook/Instagram Ads. "
        f"RÈGLES DE FORMATAGE STRICTES :\n"
        f"- Pour mettre en gras : utilise *texte* (un seul astérisque de chaque côté)\n"
        f"- NE JAMAIS utiliser ** (double astérisque)\n"
        f"- NE JAMAIS utiliser === ou --- comme séparateur\n"
        f"- Utilise des emojis au début de chaque section principale\n"
        f"- Saute une ligne entre chaque section\n"
        f"- Utilise • pour les listes\n"
        f"- Toujours en français, ultra concret et chiffré."
    )

def nettoyer(text):
    import re
    # Supprimer les séparateurs ===== et -----
    text = re.sub(r'={3,}', '', text)
    text = re.sub(r'-{3,}', '', text)
    # Convertir **texte** en *texte* pour Telegram
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    # Supprimer les # markdown
    text = re.sub(r'^#{1,4}\s+', '', text, flags=re.MULTILINE)
    # Convertir - en bullet
    text = re.sub(r'^\s*[-–]\s', '• ', text, flags=re.MULTILINE)
    # Supprimer les lignes vides multiples
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def analyser_vente(profile, produit, prix_achat):
    sys = get_system(profile)
    prompt = (
        f"Fais une analyse de vente complète pour ce produit dropshipping :\n\n"
        f"Produit : {produit}\n"
        f"Prix d'achat fournisseur : {prix_achat}\n\n"
        f"*💰 ANALYSE DES PRIX*\n"
        f"• Prix d'achat : {prix_achat}\n"
        f"• Prix de vente recommandé : [calcul x3 minimum]\n"
        f"• Marge brute : [montant et %]\n"
        f"• Marge nette estimée (après ads) : [montant et %]\n"
        f"• Seuil de rentabilité : [nb de ventes/jour pour être rentable]\n\n"
        f"*📊 POTENTIEL DE MARCHÉ*\n"
        f"• Taille du marché estimée\n"
        f"• Niveau de concurrence : [faible/moyen/fort]\n"
        f"• Saisonnalité : [tout l'année / saisonnier]\n"
        f"• Tendance actuelle : [montante/stable/baissante]\n\n"
        f"*📢 POTENTIEL PUBLICITAIRE*\n"
        f"• CPA cible recommandé (coût par achat)\n"
        f"• ROAS minimum pour être rentable\n"
        f"• Budget test recommandé\n"
        f"• Potentiel TikTok Ads : [score/10 + pourquoi]\n"
        f"• Potentiel Meta Ads : [score/10 + pourquoi]\n\n"
        f"*⚠️ RISQUES*\n"
        f"• Top 3 risques à anticiper\n"
        f"• Comment les minimiser\n\n"
        f"*✅ VERDICT FINAL*\n"
        f"• Note globale : [/10]\n"
        f"• Recommandation : [LANCER / TESTER PRUDEMMENT / ÉVITER]\n"
        f"• Raison principale\n"
        f"• Prochaine étape concrète à faire"
    )
    return ask_groq(prompt, sys)

def trouver_tendances(profile, categorie=None):
    sys = get_system(profile)
    prompt = (
        f"Trouve 7 produits à haute tendance pour du dropshipping en ce moment"
        + (f" dans la catégorie : {categorie}" if categorie else "")
        + f" pour le marché {profile.get('pays','France')}.\n\n"
        f"Pour chaque produit utilise ce format EXACT :\n\n"
        f"*🔥 [NUMÉRO]. [NOM DU PRODUIT]*\n\n"
        f"• Tendance : [pourquoi c'est tendance]\n"
        f"• Achat : [prix fournisseur]\n"
        f"• Vente : [prix recommandé]\n"
        f"• Marge : [marge brute %]\n"
        f"• TikTok Ads : [score/10]\n"
        f"• Meta Ads : [score/10]\n\n"
        f"• 🔗 Fournisseurs :\n"
        f"  1. AliExpress : https://fr.aliexpress.com/wholesale?SearchText=[mots-clés-produit]\n"
        f"  2. Alibaba : https://www.alibaba.com/trade/search?SearchText=[mots-clés-produit]\n"
        f"  3. CJ Dropshipping : https://cjdropshipping.com/list.html?searchKey=[mots-clés-produit]\n\n"
        f"Remplace [mots-clés-produit] par les vrais mots-clés du produit en anglais dans les URLs. "
        f"Sépare chaque produit par une ligne vide. Classe du plus au moins prometteur."
    )
    return ask_groq(prompt, sys)

def generer_fiche(profile, produit):
    sys = get_system(profile)
    prompt = (
        f"Génère une fiche produit Shopify complète et optimisée pour : '{produit}'.\n\n"
        f"Inclus :\n"
        f"*TITRE SEO* : titre accrocheur + mots-clés (max 70 caractères)\n\n"
        f"*DESCRIPTION COURTE* : 2-3 phrases percutantes pour la page produit\n\n"
        f"*DESCRIPTION LONGUE* : description complète HTML-ready avec :\n"
        f"  - Hook émotionnel d'ouverture\n"
        f"  - 5 bénéfices clés (pas des caractéristiques)\n"
        f"  - Preuves sociales suggérées\n"
        f"  - CTA fort de fermeture\n\n"
        f"*BULLET POINTS* : 5 arguments de vente courts\n\n"
        f"*MÉTA DESCRIPTION* : 155 caractères pour le SEO\n\n"
        f"*TAGS SHOPIFY* : 10 tags pertinents\n\n"
        f"*PRIX SUGGÉRÉ* : stratégie de prix psychologique"
    )
    return ask_groq(prompt, sys)

def generer_ads(profile, produit):
    sys = get_system(profile)
    prompt = (
        f"Crée des textes publicitaires complets pour '{produit}'.\n\n"
        f"*TIKTOK ADS*\n"
        f"• Hook vidéo (0-3s) : 3 variantes qui arrêtent le scroll\n"
        f"• Script vidéo 15s : texte complet à dire/afficher\n"
        f"• Script vidéo 30s : texte complet storytelling\n"
        f"• Caption TikTok : texte + hashtags\n\n"
        f"*FACEBOOK/INSTAGRAM ADS*\n"
        f"• Accroche principale : 3 variantes (max 40 caractères)\n"
        f"• Texte principal : 3 variantes (court/moyen/long)\n"
        f"• Description : 2 variantes\n"
        f"• CTA recommandé\n\n"
        f"*EMAIL MARKETING*\n"
        f"• Objet email : 3 variantes A/B\n"
        f"• Email de lancement (300 mots)\n\n"
        f"Adapte le ton pour la cible {profile.get('cible','acheteurs en ligne')}."
    )
    return ask_groq(prompt, sys)

def generer_page_vente(profile, produit):
    sys = get_system(profile)
    prompt = (
        f"Crée une page de vente Shopify complète et haute conversion pour : '{produit}'.\n\n"
        f"Structure :\n\n"
        f"*HERO SECTION*\n"
        f"• Titre principal (H1) accrocheur\n"
        f"• Sous-titre bénéfice\n"
        f"• CTA bouton\n\n"
        f"*PROBLÈME & SOLUTION*\n"
        f"• Le problème que ressent le client\n"
        f"• Comment ce produit le résout\n\n"
        f"*BÉNÉFICES CLÉS* (5 bénéfices avec icônes suggérées)\n\n"
        f"*PREUVES SOCIALES*\n"
        f"• 3 avis clients fictifs réalistes à adapter\n"
        f"• Chiffres clés à afficher\n\n"
        f"*FAQ* : 5 questions/réponses fréquentes\n\n"
        f"*OFFRE & URGENCE*\n"
        f"• Formulation de l'offre\n"
        f"• Éléments d'urgence/rareté\n"
        f"• Garantie suggérée\n\n"
        f"*CTA FINAL* : texte du bouton + phrase d'appui"
    )
    return ask_groq(prompt, sys)

def generer_offre_flash(profile, produit):
    sys = get_system(profile)
    prompt = (
        f"Crée une offre flash complète pour '{produit}'.\n\n"
        f"*STRATÉGIE DE L'OFFRE*\n"
        f"• Type d'offre recommandé (réduction %, bundle, cadeau...)\n"
        f"• Durée optimale\n"
        f"• Prix avant/après\n\n"
        f"*TEXTES PROMO*\n"
        f"• Titre de l'offre flash (court et percutant)\n"
        f"• Bannière site web (texte)\n"
        f"• Pop-up de sortie (texte)\n"
        f"• Email d'annonce (objet + corps)\n"
        f"• SMS/WhatsApp (160 caractères)\n\n"
        f"*POSTS RÉSEAUX SOCIAUX*\n"
        f"• Post Instagram/Facebook\n"
        f"• Story Instagram\n"
        f"• TikTok caption\n\n"
        f"*COMPTE À REBOURS* : phrase d'urgence à afficher sur le site"
    )
    return ask_groq(prompt, sys)

def analyser_concurrent(profile, concurrent):
    sys = get_system(profile)
    prompt = (
        f"Analyse ce concurrent e-commerce : '{concurrent}'.\n\n"
        f"*1. FORCES*\n"
        f"• Ce qu'il fait bien (produits, prix, marketing, UX)\n\n"
        f"*2. FAIBLESSES*\n"
        f"• Ce qu'il ne couvre pas ou mal\n\n"
        f"*3. STRATÉGIE ADS*\n"
        f"• Comment il probable ment fait ses pubs TikTok/Meta\n"
        f"• Angles créatifs qu'il utilise\n\n"
        f"*4. OPPORTUNITÉS*\n"
        f"• Comment le surpasser concrètement\n"
        f"• Produits complémentaires qu'il ne vend pas\n\n"
        f"*5. PLAN D'ACTION*\n"
        f"• 5 actions concrètes pour voler ses clients\n"
        f"• Angle de différenciation principal"
    )
    return ask_groq(prompt, sys)

def analyser_store(profile, description):
    sys = get_system(profile)
    prompt = (
        f"Analyse ce store Shopify et donne un audit complet :\n\n"
        f"Description : {description}\n\n"
        f"*1. AUDIT CONVERSION*\n"
        f"• Points qui freinent les ventes\n"
        f"• Taux de conversion estimé et objectif\n\n"
        f"*2. AUDIT PRODUITS*\n"
        f"• Sélection de produits (pertinence, prix, marges)\n\n"
        f"*3. AUDIT MARKETING*\n"
        f"• Stratégie ads actuelle vs optimale\n"
        f"• Canaux sous-exploités\n\n"
        f"*4. AUDIT TECHNIQUE*\n"
        f"• Vitesse, mobile, SEO\n"
        f"• Apps Shopify recommandées\n\n"
        f"*5. PLAN D'ACTION PRIORITAIRE*\n"
        f"• Top 5 actions à faire cette semaine\n"
        f"• Top 5 actions à faire ce mois\n"
        f"• Objectif CA à 90 jours réaliste"
    )
    return ask_groq(prompt, sys)

def strategie_lancement(profile, produit):
    sys = get_system(profile)
    prompt = (
        f"Crée une stratégie de lancement complète pour '{produit}' sur Shopify.\n\n"
        f"*PHASE 1 — PRÉPARATION (Semaine 1-2)*\n"
        f"• Validation du produit (méthode)\n"
        f"• Setup store Shopify (checklist)\n"
        f"• Création des visuels (brief créatif)\n\n"
        f"*PHASE 2 — TEST (Semaine 3-4)*\n"
        f"• Budget test recommandé\n"
        f"• Structure campagne TikTok Ads\n"
        f"• Structure campagne Meta Ads\n"
        f"• KPIs à surveiller (CPA cible, ROAS minimum)\n\n"
        f"*PHASE 3 — SCALE (Mois 2)*\n"
        f"• Critères pour passer au scale\n"
        f"• Comment augmenter le budget\n"
        f"• Nouveaux angles créatifs\n\n"
        f"*PHASE 4 — OPTIMISATION (Mois 3)*\n"
        f"• Upsell/cross-sell à ajouter\n"
        f"• Email flows à mettre en place\n"
        f"• Stratégie de rétention\n\n"
        f"*BUDGET TOTAL ESTIMÉ* et *CA PROJETÉ* par phase"
    )
    return ask_groq(prompt, sys)

def plan_contenu(profile, produit=None):
    sys = get_system(profile)
    mois = datetime.now().strftime("%B %Y")
    prompt = (
        f"Crée un plan de contenu e-commerce complet pour {mois}"
        + (f" autour du produit : '{produit}'" if produit else "")
        + f" pour {profile.get('niche','e-commerce')}.\n\n"
        f"*RÉPARTITION HEBDOMADAIRE*\n"
        f"• Lundi : type de contenu + sujet\n"
        f"• Mardi : type de contenu + sujet\n"
        f"• Mercredi : type de contenu + sujet\n"
        f"• Jeudi : type de contenu + sujet\n"
        f"• Vendredi : type de contenu + sujet\n"
        f"• Weekend : type de contenu + sujet\n\n"
        f"*CALENDRIER 30 JOURS*\n"
        f"Pour chaque semaine : thème principal, 5 idées de posts, 2 idées de vidéos TikTok\n\n"
        f"*CONTENUS EVERGREEN* : 5 idées de contenus qui fonctionnent toujours\n\n"
        f"*ÉVÉNEMENTS DU MOIS* : dates importantes à exploiter (promos, fêtes...)"
    )
    return ask_groq(prompt, sys)


# ============================================================
#  UTILITAIRES
# ============================================================

def nettoyer(text):
    import re
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    text = re.sub(r'^#{1,4}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\- ', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def send_long(chat_id, text, reply_to=None):
    text = nettoyer(text)
    MAX = 4000
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MAX:
            if current: chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line
    if current: chunks.append(current)
    for i, chunk in enumerate(chunks):
        try:
            if i == 0 and reply_to:
                bot.reply_to(reply_to, chunk, parse_mode="Markdown")
            else:
                bot.send_message(chat_id, chunk, parse_mode="Markdown")
        except:
            try:
                if i == 0 and reply_to:
                    bot.reply_to(reply_to, chunk)
                else:
                    bot.send_message(chat_id, chunk)
            except Exception as e:
                print(f"Erreur envoi: {e}")


# ============================================================
#  COMMANDES TELEGRAM
# ============================================================

@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    configured = "✅ Configuré" if profile else "⚠️ Non configuré — fais /profil"
    bot.reply_to(message,
        "🛒 Bot E-Commerce\n\n"
        f"Profil : {configured}\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "⚙️ CONFIGURATION\n"
        "/profil — Configurer ton store\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🔥 PRODUITS\n"
        "/tendances — Produits tendance à vendre\n"
        "/tendances [catégorie] — Par catégorie\n"
        "/analyse [produit] | [prix] — Analyse de vente\n"
        "/fiche [produit] — Fiche produit complète\n"
        "/page [produit] — Page de vente Shopify\n"
        "/flash [produit] — Offre flash complète\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📢 PUBLICITÉ\n"
        "/ads [produit] — Textes TikTok + Meta Ads\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📊 STRATÉGIE\n"
        "/lancement [produit] — Stratégie lancement\n"
        "/contenu — Plan de contenu 30 jours\n"
        "/contenu [produit] — Plan autour d'un produit\n"
        "/concurrent [nom] — Analyse concurrence\n"
        "/store [description] — Audit de ton store\n"
    )


@bot.message_handler(commands=["profil"])
def cmd_profil(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    profil_actuel = (
        f"Profil actuel :\n"
        f"• Niche : {profile.get('niche','Non défini')}\n"
        f"• Cible : {profile.get('cible','Non défini')}\n"
        f"• Pays : {profile.get('pays','Non défini')}\n"
        f"• Budget ads : {profile.get('budget_ads','Non défini')}"
        if profile else "⚠️ Aucun profil configuré"
    )
    bot.reply_to(message,
        "⚙️ Configuration de ton store\n\n"
        "/setniche [ta niche]\n"
        "Ex : /setniche Accessoires fitness et bien-être\n\n"
        "/setcible [ta cible]\n"
        "Ex : /setcible Femmes 25-40 ans sportives\n\n"
        "/setpays [ton marché]\n"
        "Ex : /setpays France\n\n"
        "/setbudget [budget ads/mois]\n"
        "Ex : /setbudget 500€/mois\n\n"
        + profil_actuel
    )


@bot.message_handler(commands=["setniche"])
def cmd_setniche(message):
    if not is_authorized(message.from_user.id): return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /setniche [ta niche]"); return
    profile = get_profile(message.from_user.id)
    profile["niche"] = parts[1]
    save_profile(message.from_user.id, profile)
    bot.reply_to(message, f"✅ Niche : {parts[1]}")

@bot.message_handler(commands=["setcible"])
def cmd_setcible(message):
    if not is_authorized(message.from_user.id): return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /setcible [ta cible]"); return
    profile = get_profile(message.from_user.id)
    profile["cible"] = parts[1]
    save_profile(message.from_user.id, profile)
    bot.reply_to(message, f"✅ Cible : {parts[1]}")

@bot.message_handler(commands=["setpays"])
def cmd_setpays(message):
    if not is_authorized(message.from_user.id): return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /setpays [pays]"); return
    profile = get_profile(message.from_user.id)
    profile["pays"] = parts[1]
    save_profile(message.from_user.id, profile)
    bot.reply_to(message, f"✅ Pays : {parts[1]}")

@bot.message_handler(commands=["setbudget"])
def cmd_setbudget(message):
    if not is_authorized(message.from_user.id): return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /setbudget [budget]"); return
    profile = get_profile(message.from_user.id)
    profile["budget_ads"] = parts[1]
    save_profile(message.from_user.id, profile)
    bot.reply_to(message, f"✅ Budget ads : {parts[1]}")


@bot.message_handler(commands=["tendances"])
def cmd_tendances(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    if not profile:
        bot.reply_to(message, "⚠️ Configure ton profil avec /profil"); return
    parts = message.text.split(" ", 1)
    cat = parts[1] if len(parts) > 1 else None
    bot.reply_to(message, "⏳ Recherche des produits tendance...")
    result = trouver_tendances(profile, cat)
    if result:
        send_long(message.chat.id, f"🔥 PRODUITS TENDANCE\n\n{result}", reply_to=message)
    else:
        bot.reply_to(message, "❌ Erreur. Réessaie.")


@bot.message_handler(commands=["fiche"])
def cmd_fiche(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    if not profile:
        bot.reply_to(message, "⚠️ Configure ton profil avec /profil"); return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /fiche [produit]\nEx : /fiche Ceinture de massage électrique"); return
    bot.reply_to(message, "⏳ Génération de la fiche produit...")
    result = generer_fiche(profile, parts[1])
    if result:
        send_long(message.chat.id, f"📦 FICHE PRODUIT\n\n{result}", reply_to=message)
    else:
        bot.reply_to(message, "❌ Erreur. Réessaie.")


@bot.message_handler(commands=["ads"])
def cmd_ads(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    if not profile:
        bot.reply_to(message, "⚠️ Configure ton profil avec /profil"); return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /ads [produit]\nEx : /ads Lampe LED gaming"); return
    bot.reply_to(message, "⏳ Création des textes publicitaires...")
    result = generer_ads(profile, parts[1])
    if result:
        send_long(message.chat.id, f"📢 TEXTES PUBLICITAIRES\n\n{result}", reply_to=message)
    else:
        bot.reply_to(message, "❌ Erreur. Réessaie.")


@bot.message_handler(commands=["page"])
def cmd_page(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    if not profile:
        bot.reply_to(message, "⚠️ Configure ton profil avec /profil"); return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /page [produit]\nEx : /page Montre connectée sport"); return
    bot.reply_to(message, "⏳ Création de la page de vente... (30 secondes)")
    result = generer_page_vente(profile, parts[1])
    if result:
        send_long(message.chat.id, f"🛍️ PAGE DE VENTE SHOPIFY\n\n{result}", reply_to=message)
    else:
        bot.reply_to(message, "❌ Erreur. Réessaie.")


@bot.message_handler(commands=["flash"])
def cmd_flash(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    if not profile:
        bot.reply_to(message, "⚠️ Configure ton profil avec /profil"); return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /flash [produit]\nEx : /flash Écouteurs sans fil"); return
    bot.reply_to(message, "⏳ Création de l'offre flash...")
    result = generer_offre_flash(profile, parts[1])
    if result:
        send_long(message.chat.id, f"⚡ OFFRE FLASH\n\n{result}", reply_to=message)
    else:
        bot.reply_to(message, "❌ Erreur. Réessaie.")


@bot.message_handler(commands=["concurrent"])
def cmd_concurrent(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    if not profile:
        bot.reply_to(message, "⚠️ Configure ton profil avec /profil"); return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /concurrent [nom du site]\nEx : /concurrent gymshark.com"); return
    bot.reply_to(message, "⏳ Analyse de la concurrence...")
    result = analyser_concurrent(profile, parts[1])
    if result:
        send_long(message.chat.id, f"🔍 ANALYSE CONCURRENCE\n\n{result}", reply_to=message)
    else:
        bot.reply_to(message, "❌ Erreur. Réessaie.")


@bot.message_handler(commands=["store"])
def cmd_store(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    if not profile:
        bot.reply_to(message, "⚠️ Configure ton profil avec /profil"); return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message,
            "Usage : /store [description de ton store]\n"
            "Ex : /store Shopify mode femme, 50 produits, 300 visites/jour, 1% conversion, dépense 300€/mois Meta Ads, CA 800€/mois"); return
    bot.reply_to(message, "⏳ Audit de ton store en cours...")
    result = analyser_store(profile, parts[1])
    if result:
        send_long(message.chat.id, f"📊 AUDIT DE TON STORE\n\n{result}", reply_to=message)
    else:
        bot.reply_to(message, "❌ Erreur. Réessaie.")


@bot.message_handler(commands=["lancement"])
def cmd_lancement(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    if not profile:
        bot.reply_to(message, "⚠️ Configure ton profil avec /profil"); return
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage : /lancement [produit]\nEx : /lancement Tapis de yoga antidérapant"); return
    bot.reply_to(message, "⏳ Création de la stratégie de lancement... (30 secondes)")
    result = strategie_lancement(profile, parts[1])
    if result:
        send_long(message.chat.id, f"🚀 STRATÉGIE DE LANCEMENT\n\n{result}", reply_to=message)
    else:
        bot.reply_to(message, "❌ Erreur. Réessaie.")


@bot.message_handler(commands=["contenu"])
def cmd_contenu(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    if not profile:
        bot.reply_to(message, "⚠️ Configure ton profil avec /profil"); return
    parts = message.text.split(" ", 1)
    produit = parts[1] if len(parts) > 1 else None
    bot.reply_to(message, "⏳ Création du plan de contenu... (30 secondes)")
    result = plan_contenu(profile, produit)
    if result:
        send_long(message.chat.id, f"📅 PLAN DE CONTENU 30 JOURS\n\n{result}", reply_to=message)
    else:
        bot.reply_to(message, "❌ Erreur. Réessaie.")


@bot.message_handler(commands=["analyse"])
def cmd_analyse(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    profile = get_profile(message.from_user.id)
    if not profile:
        bot.reply_to(message, "⚠️ Configure ton profil avec /profil"); return
    parts = message.text.split(" ", 1)
    if len(parts) < 2 or "|" not in parts[1]:
        bot.reply_to(message,
            "Usage : /analyse [produit] | [prix achat]\n\n"
            "Ex : /analyse Ceinture massage électrique | 8€\n"
            "Ex : /analyse Écouteurs sans fil | 12.50€"); return

    infos = parts[1].split("|", 1)
    produit    = infos[0].strip()
    prix_achat = infos[1].strip()

    bot.reply_to(message, f"⏳ Analyse de vente en cours pour *{produit}*...")
    result = analyser_vente(profile, produit, prix_achat)
    if result:
        send_long(message.chat.id, f"📊 ANALYSE DE VENTE\n\n{result}", reply_to=message)
    else:
        bot.reply_to(message, "❌ Erreur. Réessaie.")


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
    bot.reply_to(message, f"Ton ID : {message.from_user.id}")


@bot.message_handler(func=lambda m: True)
def handle_unknown(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ Accès non autorisé."); return
    bot.reply_to(message, "❓ Commande inconnue. Envoie /help.")


# ============================================================
#  LANCEMENT
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  BOT E-COMMERCE DÉMARRÉ")
    print(f"  Admin : {ADMIN_ID}")
    print("=" * 50)
    bot.infinity_polling()
