"""Mémoire persistante de l'assistant IA MAGsim.

Stocke deux types d'informations dans data/memoire_assistant.json :

1. EXEMPLES VALIDÉS — paires Q/R approuvées via 👍 par le gestionnaire.
   Injectées dans le prompt comme few-shot dynamiques (remplacent progressivement
   les exemples écrits à la main).

2. RÉSUMÉS DE SESSIONS — ce qui a été discuté et décidé dans chaque conversation.
   Injectés pour donner au modèle un fil conducteur entre sessions.
"""

import json
import os
from datetime import datetime

MEMOIRE_PATH        = "data/memoire_assistant.json"
MAX_EXEMPLES_INJECTES = 5   # max d'exemples validés injectés dans le prompt
MAX_SESSIONS_INJECTEES = 3  # max de résumés de sessions injectés


# ─────────────────────────────────────────────────────────────────────────────
#  Lecture / écriture
# ─────────────────────────────────────────────────────────────────────────────

def charger():
    """Charge la mémoire depuis le fichier JSON."""
    if os.path.exists(MEMOIRE_PATH):
        try:
            with open(MEMOIRE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("exemples", [])
            data.setdefault("sessions", [])
            return data
        except Exception:
            pass
    return {"exemples": [], "sessions": []}


def _sauvegarder(data):
    os.makedirs(os.path.dirname(MEMOIRE_PATH), exist_ok=True)
    with open(MEMOIRE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
#  Sauvegarde
# ─────────────────────────────────────────────────────────────────────────────

def sauvegarder_exemple(question, reponse, nom_labo=""):
    """Enregistre une paire Q/R approuvée par le gestionnaire (👍)."""
    data = charger()
    data["exemples"].append({
        "date":     datetime.now().strftime("%Y-%m-%d"),
        "labo":     nom_labo,
        "question": question.strip()[:300],
        "reponse":  reponse.strip()[:600],
    })
    # Garder les 50 derniers exemples
    data["exemples"] = data["exemples"][-50:]
    _sauvegarder(data)


def sauvegarder_resume_session(messages, patches_appliques, nom_labo=""):
    """Enregistre un résumé de la session courante.

    Parameters
    ----------
    messages         : list[dict] — historique complet de la conversation
    patches_appliques: list[str]  — descriptions des changements confirmés
    nom_labo         : str        — nom du projet (identifiant du labo)
    """
    if not messages:
        return

    # Extraire les questions posées par le gestionnaire
    questions = [
        m["content"].strip()[:120]
        for m in messages
        if m["role"] == "user"
    ]

    data = charger()
    data["sessions"].append({
        "date":               datetime.now().strftime("%Y-%m-%d %H:%M"),
        "labo":               nom_labo,
        "nb_echanges":        len(questions),
        "questions_posees":   questions[:5],
        "patches_appliques":  patches_appliques,
    })
    # Garder les 20 dernières sessions
    data["sessions"] = data["sessions"][-20:]
    _sauvegarder(data)


# ─────────────────────────────────────────────────────────────────────────────
#  Construction de la section mémoire pour le prompt
# ─────────────────────────────────────────────────────────────────────────────

def construire_section_memoire(nom_labo=""):
    """Retourne une section texte à injecter dans le prompt système.

    Contient les résumés des sessions récentes et les exemples validés.
    Retourne une chaîne vide si aucune mémoire n'est disponible.
    """
    data    = charger()
    lignes  = []

    # ── Sessions récentes ──
    sessions = data.get("sessions", [])
    sessions_labo = [
        s for s in sessions
        if not s.get("labo") or not nom_labo or s.get("labo") == nom_labo
    ]
    if sessions_labo:
        recentes = sessions_labo[-MAX_SESSIONS_INJECTEES:]
        lignes.append("== Historique des conversations précédentes ==")
        for s in reversed(recentes):
            date     = s.get("date", "?")
            patches  = s.get("patches_appliques", [])
            qs       = s.get("questions_posees", [])
            nb       = s.get("nb_echanges", 0)
            lignes.append(f"Session du {date} ({nb} échange(s)) :")
            if patches:
                lignes.append(f"  Modifications appliquées ce jour-là : {' | '.join(patches)}")
            if qs:
                lignes.append(f"  Sujets abordés : {' | '.join(qs[:3])}")
        lignes.append("")

    # ── Exemples validés par ce gestionnaire ──
    exemples = data.get("exemples", [])
    exemples_labo = [
        e for e in exemples
        if not e.get("labo") or not nom_labo or e.get("labo") == nom_labo
    ]
    if exemples_labo:
        recents = exemples_labo[-MAX_EXEMPLES_INJECTES:]
        lignes.append("== Exemples de réponses validées par ce gestionnaire ==")
        lignes.append("(Ces exemples ont été approuvés — reproduis ce style.)")
        for ex in recents:
            lignes.append(f"Gestionnaire : « {ex['question']} »")
            lignes.append(f"Bonne réponse : {ex['reponse']}")
            lignes.append("")

    return "\n".join(lignes)


def nb_exemples(nom_labo=""):
    """Retourne le nombre d'exemples validés pour ce labo."""
    data = charger()
    exemples = data.get("exemples", [])
    if nom_labo:
        return len([e for e in exemples if not e.get("labo") or e.get("labo") == nom_labo])
    return len(exemples)


# ─────────────────────────────────────────────────────────────────────────────
#  Profil gestionnaire (prénom, préférences, etc.)
# ─────────────────────────────────────────────────────────────────────────────

def get_prenom_gestionnaire():
    """Retourne le prénom mémorisé du gestionnaire, ou None."""
    data = charger()
    return data.get("profil", {}).get("prenom")


def set_prenom_gestionnaire(prenom: str):
    """Mémorise le prénom du gestionnaire de façon persistante."""
    data = charger()
    data.setdefault("profil", {})["prenom"] = _capitaliser_prenom(prenom.strip())
    _sauvegarder(data)


def _capitaliser_prenom(prenom: str) -> str:
    """Capitalise chaque segment d'un prénom, y compris les prénoms composés (Marc-Antoine)."""
    return "-".join(part.capitalize() for part in prenom.split("-"))


def detecter_et_sauver_prenom(texte_utilisateur: str) -> str | None:
    """Détecte si le message contient une présentation du type 'je m'appelle X' ou 'mon prénom est X'.
    Si trouvé, sauvegarde et retourne le prénom. Sinon retourne None.
    """
    import re
    # Capture un prénom simple ou composé avec tiret (Marc, Marc-Antoine, Jean-Pierre...)
    # IMPORTANT : le nom doit commencer par une MAJUSCULE pour éviter les faux positifs
    NOM = r"([A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+(?:-[A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+)*)"
    # Les déclencheurs sont insensibles à la casse, mais le NOM garde la casse pour forcer une majuscule
    TRIGGER = r"(?:je m['\u2019]appelle|mon pr[e\u00e9]nom est|mon nom est|appelle[- ]moi|pas juste|pas seulement)"
    patterns = [
        rf"(?i:{TRIGGER})\s+{NOM}",
        rf"^{NOM}\s+(?:ici|\u00e0 l'appareil|au bout du fil|qui te parle|qui vous parle)",
    ]
    for pat in patterns:
        m = re.search(pat, texte_utilisateur)  # pas de IGNORECASE global
        if m:
            prenom = _capitaliser_prenom(m.group(1).strip())
            set_prenom_gestionnaire(prenom)
            return prenom
    return None
