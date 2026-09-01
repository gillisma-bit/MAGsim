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
        lignes.append("== Historique des conversations précédentes (contexte passé — PAS la question actuelle) ==")
        lignes.append(
            "Ces informations décrivent DES SESSIONS TERMINÉES. Ne les traite jamais comme "
            "la demande en cours. Le gestionnaire te parle maintenant d'autre chose : "
            "réponds UNIQUEMENT au dernier message qu'il vient d'envoyer."
        )
        for s in reversed(recentes):
            date     = s.get("date", "?")
            patches  = s.get("patches_appliques", [])
            qs       = s.get("questions_posees", [])
            nb       = s.get("nb_echanges", 0)
            lignes.append(f"Session du {date} ({nb} échange(s)) :")
            if patches:
                lignes.append(f"  Modifications appliquées ce jour-là : {' | '.join(patches)}")
            if qs:
                lignes.append(f"  Sujets abordés (terminé, non pertinent aujourd'hui sauf si le gestionnaire y revient explicitement) : {' | '.join(qs[:3])}")
        lignes.append("")

    # ── Exemples validés par ce gestionnaire ──
    exemples = data.get("exemples", [])
    exemples_labo = [
        e for e in exemples
        if not e.get("labo") or not nom_labo or e.get("labo") == nom_labo
    ]
    if exemples_labo:
        recents = exemples_labo[-MAX_EXEMPLES_INJECTES:]
        lignes.append("== Exemples de TON et de STYLE approuvés par ce gestionnaire (PAS des réponses à réutiliser) ==")
        lignes.append(
            "IMPORTANT : ces exemples servent UNIQUEMENT à calibrer ton ton, ta longueur de phrase "
            "et ton niveau de langage. Ils correspondaient à d'ANCIENNES questions, sur d'anciennes "
            "données de simulation. N'en recopie JAMAIS le contenu factuel ou les chiffres — "
            "génère toujours une réponse neuve basée sur le dernier message du gestionnaire et "
            "les métriques ACTUELLES."
        )
        for ex in recents:
            lignes.append(f"Ancien exemple — Gestionnaire : « {ex['question']} »")
            lignes.append(f"Ancien exemple — Réponse (style à imiter, PAS le contenu) : {ex['reponse']}")
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
#  Profil utilisateur — fichier Markdown lisible, enrichi au fil des échanges
# ─────────────────────────────────────────────────────────────────────────────

PROFIL_MD_PATH = "data/profil_utilisateur.md"
MAX_NOTES_PAR_SECTION = 12
SEUIL_CONSOLIDATION  = 6   # au-delà, l'IA fusionne les notes proches de la section

_SECTIONS_PROFIL = [
    "Style de communication",
    "Humour",
    "Centres d'intérêt",
    "Contexte professionnel",
    "Préférences diverses",
]

_ENTETE_PROFIL_MD = (
    "# Profil du gestionnaire\n\n"
    "Ce fichier est enrichi automatiquement par l'assistant IA au fil des conversations.\n"
    "Il permet d'ajuster le ton, l'humour et le style des réponses au fil du temps.\n"
)


def _lire_profil_md_brut():
    if os.path.exists(PROFIL_MD_PATH):
        try:
            with open(PROFIL_MD_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return _ENTETE_PROFIL_MD + "".join(f"\n## {s}\n" for s in _SECTIONS_PROFIL)


def lire_profil_md():
    """Retourne le contenu complet du profil Markdown (crée le fichier si absent)."""
    contenu = _lire_profil_md_brut()
    if not os.path.exists(PROFIL_MD_PATH):
        os.makedirs(os.path.dirname(PROFIL_MD_PATH), exist_ok=True)
        with open(PROFIL_MD_PATH, "w", encoding="utf-8") as f:
            f.write(contenu)
    return contenu


def ajouter_note_profil(section: str, note: str):
    """Ajoute une note (une ligne) sous la section donnée du profil Markdown.

    Ignore silencieusement si une note similaire existe déjà (évite les doublons
    exacts ET les reformulations proches) ou si la section n'est pas reconnue.
    Limite chaque section à MAX_NOTES_PAR_SECTION lignes (les plus anciennes retirées).
    """
    if section not in _SECTIONS_PROFIL or not note.strip():
        return
    note = note.strip().rstrip(".")
    contenu = _lire_profil_md_brut()
    lignes  = contenu.splitlines()

    # Localiser la section
    try:
        idx_section = next(i for i, l in enumerate(lignes) if l.strip() == f"## {section}")
    except StopIteration:
        lignes.append(f"\n## {section}")
        idx_section = len(lignes) - 1

    # Trouver la fin de la section (prochain "## " ou fin de fichier)
    idx_fin = len(lignes)
    for i in range(idx_section + 1, len(lignes)):
        if lignes[i].startswith("## "):
            idx_fin = i
            break

    notes_existantes = [l for l in lignes[idx_section + 1:idx_fin] if l.strip().startswith("- ")]
    if _note_similaire_existe(note, notes_existantes):
        return  # déjà noté (exact ou reformulation proche)

    notes_existantes.append(f"- {note}")
    notes_existantes = notes_existantes[-MAX_NOTES_PAR_SECTION:]

    nouvelles_lignes = lignes[:idx_section + 1] + [""] + notes_existantes + [""] + lignes[idx_fin:]
    os.makedirs(os.path.dirname(PROFIL_MD_PATH), exist_ok=True)
    with open(PROFIL_MD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(nouvelles_lignes).strip() + "\n")


def _note_similaire_existe(note: str, notes_existantes: list) -> bool:
    """Détecte les doublons exacts ET les reformulations proches (ratio de similarité)."""
    import difflib
    note_low = note.lower()
    for l in notes_existantes:
        texte = l.strip().lstrip("- ").lower()
        if note_low in texte or texte in note_low:
            return True
        if difflib.SequenceMatcher(None, note_low, texte).ratio() > 0.55:
            return True
    return False


def nb_notes_section(section: str) -> int:
    """Retourne le nombre de notes actuellement enregistrées dans une section."""
    contenu = _lire_profil_md_brut()
    lignes  = contenu.splitlines()
    try:
        idx_section = next(i for i, l in enumerate(lignes) if l.strip() == f"## {section}")
    except StopIteration:
        return 0
    idx_fin = len(lignes)
    for i in range(idx_section + 1, len(lignes)):
        if lignes[i].startswith("## "):
            idx_fin = i
            break
    return len([l for l in lignes[idx_section + 1:idx_fin] if l.strip().startswith("- ")])


def lister_notes_section(section: str) -> list:
    """Retourne la liste des notes (texte, sans le tiret) d'une section."""
    contenu = _lire_profil_md_brut()
    lignes  = contenu.splitlines()
    try:
        idx_section = next(i for i, l in enumerate(lignes) if l.strip() == f"## {section}")
    except StopIteration:
        return []
    idx_fin = len(lignes)
    for i in range(idx_section + 1, len(lignes)):
        if lignes[i].startswith("## "):
            idx_fin = i
            break
    return [l.strip().lstrip("- ").strip() for l in lignes[idx_section + 1:idx_fin] if l.strip().startswith("- ")]


def remplacer_notes_section(section: str, notes: list):
    """Remplace intégralement les notes d'une section (utilisé par la consolidation IA)."""
    if section not in _SECTIONS_PROFIL:
        return
    contenu = _lire_profil_md_brut()
    lignes  = contenu.splitlines()
    try:
        idx_section = next(i for i, l in enumerate(lignes) if l.strip() == f"## {section}")
    except StopIteration:
        lignes.append(f"\n## {section}")
        idx_section = len(lignes) - 1
    idx_fin = len(lignes)
    for i in range(idx_section + 1, len(lignes)):
        if lignes[i].startswith("## "):
            idx_fin = i
            break
    notes_propres = [f"- {n.strip().lstrip('- ').strip()}" for n in notes if n.strip()]
    notes_propres = notes_propres[-MAX_NOTES_PAR_SECTION:]
    nouvelles_lignes = lignes[:idx_section + 1] + [""] + notes_propres + [""] + lignes[idx_fin:]
    os.makedirs(os.path.dirname(PROFIL_MD_PATH), exist_ok=True)
    with open(PROFIL_MD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(nouvelles_lignes).strip() + "\n")


def construire_section_profil_md():
    """Retourne le contenu du profil formaté pour injection dans le prompt système.
    Retourne une chaîne vide si aucune note n'a encore été enregistrée.
    """
    contenu = lire_profil_md()
    if not any(l.strip().startswith("- ") for l in contenu.splitlines()):
        return ""
    return (
        "== Profil du gestionnaire (appris au fil des conversations) ==\n"
        "Adapte ton ton, ton humour et ton style de réponse à ces observations :\n"
        f"{contenu.strip()}\n"
    )



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
