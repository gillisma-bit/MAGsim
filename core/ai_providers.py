"""Clients API (Ollama, GitHub Models) et gestion de la configuration IA.
Extrait de ai_assistant.py pour garder les fichiers a taille raisonnable.
"""

import json
import os
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434/api/chat"


# ─────────────────────────────────────────────────────────────────────────────
#  Client Ollama
# ─────────────────────────────────────────────────────────────────────────────

def lister_modeles():
    """Retourne la liste des modèles disponibles dans Ollama."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def ollama_disponible():
    """Vérifie si Ollama répond sur localhost:11434."""
    return bool(lister_modeles())


def envoyer_messages(messages, model="llama3", on_token=None, timeout=120, stop_event=None):
    """Envoie une liste de messages à Ollama et retourne la réponse complète.

    Parameters
    ----------
    messages : list[dict]  — [{"role": "system"|"user"|"assistant", "content": str}]
    model    : str         — nom du modèle Ollama
    on_token : callable    — appelé avec chaque token (str) si streaming
    timeout  : int         — secondes avant abandon

    Returns
    -------
    str — réponse complète du modèle
    """
    payload = {
        "model":    model,
        "messages": messages,
        "stream":   on_token is not None,
        "options": {"temperature": 0},
    }
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    reponse_complete = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if on_token:
                # Streaming ligne par ligne
                for ligne in resp:
                    if stop_event and stop_event.is_set():
                        break
                    chunk = json.loads(ligne.decode("utf-8"))
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        reponse_complete.append(token)
                        on_token(token)
                    if chunk.get("done"):
                        break
            else:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("message", {}).get("content", "")
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"Impossible de joindre Ollama sur {OLLAMA_URL}.\n"
            f"Vérifiez qu'Ollama est lancé (commande : ollama serve).\nDétail : {e}"
        ) from e

    return "".join(reponse_complete)


# ─────────────────────────────────────────────────────────────────────────────
#  Gestionnaire de clé API (Anthropic / autres futurs providers)
# ─────────────────────────────────────────────────────────────────────────────

_CONFIG_API_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "config_api.json"
)


def lire_config_api():
    """Retourne le dict de config API ({provider: {cle, modele...}})."""
    try:
        with open(_CONFIG_API_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def sauver_config_api(config_api):
    """Sauvegarde la config API dans data/config_api.json."""
    os.makedirs(os.path.dirname(_CONFIG_API_PATH), exist_ok=True)
    with open(_CONFIG_API_PATH, "w", encoding="utf-8") as f:
        json.dump(config_api, f, indent=2, ensure_ascii=False)


def get_cle_github():
    """Retourne le token GitHub (Personal Access Token) ou None."""
    return lire_config_api().get("github", {}).get("cle", "").strip() or None


def set_cle_github(cle):
    """Enregistre le token GitHub dans data/config_api.json."""
    cfg = lire_config_api()
    cfg.setdefault("github", {})["cle"] = cle.strip()
    sauver_config_api(cfg)


_STYLE_DEFAUT = {
    "reponses_courtes":    False,   # Réponses brèves et directes
    "questions_proactives": True,   # Poser une question en fin de réponse
}

def get_style_ia():
    """Retourne les préférences de style de l'IA (dict)."""
    sauvegarde = lire_config_api().get("style_ia", {})
    style = dict(_STYLE_DEFAUT)
    style.update(sauvegarde)
    return style

def set_style_ia(style):
    """Sauvegarde les préférences de style dans data/config_api.json."""
    cfg = lire_config_api()
    cfg["style_ia"] = {k: bool(v) for k, v in style.items()}
    sauver_config_api(cfg)

def _construire_regles_style():
    """Génère les règles de style à injecter dans le prompt système."""
    style = get_style_ia()
    regles = []
    if style.get("reponses_courtes"):
        regles.append(
            "STYLE — CONCISION : Tes réponses doivent être COURTES et DIRECTES. "
            "Va droit au but : état + chiffre clé + action. "
            "Maximum 3-4 phrases sauf si on te demande un détail. "
            "Pas d'introduction, pas de conclusion, pas de formule de politesse."
        )
    if not style.get("questions_proactives", True):
        regles.append(
            "STYLE — QUESTIONS : Ne pose JAMAIS de question en fin de réponse, "
            "sauf si l'utilisateur te le demande explicitement ou si une information "
            "absolument indispensable manque pour effectuer l'action demandée. "
            "Si tu as toutes les infos, agis directement sans demander confirmation."
        )
    return "\n".join(regles)


# ─────────────────────────────────────────────────────────────────────────────
#  Client GitHub Models  (format OpenAI — inclus dans GitHub Copilot)
# ─────────────────────────────────────────────────────────────────────────────
#
#  Endpoint : https://models.inference.ai.azure.com/chat/completions
#  Auth     : Bearer <github_personal_access_token>
#  Modèles  : https://github.com/marketplace/models

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"

# Modèles disponibles via GitHub Models (catalogue réel au 2026-04)
# IDs au format "publisher/modele"  — tier: low=150 req/j, high=50 req/j
GITHUB_MODELES = [
    "openai/gpt-4.1-mini",              # low tier  — 150 req/j, 1M ctx  ← défaut recommandé
    "openai/gpt-4.1",                   # high tier — 50 req/j,  1M ctx
    "meta/llama-3.3-70b-instruct",      # high tier — 50 req/j, 128k ctx
    "meta/llama-4-scout-17b-16e-instruct",  # high tier — 50 req/j, 10M ctx
    "deepseek/deepseek-v3-0324",        # high tier — 50 req/j, 128k ctx
    "mistral-ai/mistral-medium-2505",   # high tier — 50 req/j, 128k ctx  ← plus gros Mistral dispo
    "mistral-ai/mistral-small-2503",    # low tier  — 150 req/j, 128k ctx
    "microsoft/phi-4",                  # low tier  — 150 req/j, 16k ctx
]


def github_models_disponible():
    """Vérifie qu'un token GitHub est enregistré (sans test réseau)."""
    return bool(get_cle_github())


def envoyer_messages_github(messages, model="openai/gpt-4.1-mini",
                             on_token=None, timeout=120, stop_event=None,
                             _max_retries=3):
    """Envoie une conversation à GitHub Models (format OpenAI compatible).
    Réessaie automatiquement jusqu'à _max_retries fois sur erreurs 5xx / 429.

    Le message système est INCLUS dans la liste messages avec role="system",
    exactement comme pour Ollama — aucun changement de structure nécessaire.

    Parameters
    ----------
    messages  : list[dict]  — messages complets (system + user + assistant)
    model     : str          — identifiant modèle GitHub Models
    on_token  : callable     — appelé avec chaque token si streaming
    timeout   : int          — secondes avant abandon
    """
    cle = get_cle_github()
    if not cle:
        raise ConnectionError(
            "Token GitHub manquant.\n"
            "Saisissez votre token dans Paramètres → Assistant IA."
        )

    payload = {
        "model":       model,
        "max_tokens":  2048,
        "messages":    messages,
        "stream":      on_token is not None,
        "temperature": 0,
    }
    body = json.dumps(payload).encode("utf-8")

    reponse_complete = []
    _derniere_erreur = None
    for _tentative in range(max(1, _max_retries)):
        # Reconstruire la requête à chaque tentative (le body est consommé par urlopen)
        _req = urllib.request.Request(
            GITHUB_MODELS_URL,
            data=body,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {cle}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(_req, timeout=timeout) as resp:
                if on_token:
                    # Streaming SSE — format identique à OpenAI
                    for ligne in resp:
                        if stop_event and stop_event.is_set():
                            break
                        ligne_str = ligne.decode("utf-8").strip()
                        if not ligne_str.startswith("data:"):
                            continue
                        data_str = ligne_str[len("data:"):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices")
                        if not choices:
                            continue
                        token = (
                            choices[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if token:
                            reponse_complete.append(token)
                            on_token(token)
                else:
                    data = json.loads(resp.read().decode("utf-8"))
                    choices = data.get("choices")
                    if not choices:
                        raise ValueError(
                            f"Réponse inattendue de GitHub Models : {json.dumps(data)[:300]}"
                        )
                    return choices[0]["message"]["content"]
            # Succès streaming — sortir de la boucle retry
            break
        except urllib.error.HTTPError as e:
            corps = e.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(corps).get("error", {}).get("message", corps)
            except Exception:
                detail = corps
            # Erreurs transitoires : retry (5xx, 429 rate-limit)
            if e.code in (429, 500, 502, 503, 504) and _tentative < _max_retries - 1:
                import time as _time
                if e.code == 429:
                    # Respecter le header Retry-After si présent, sinon backoff long
                    retry_after = e.headers.get("Retry-After") or e.headers.get("x-ratelimit-reset-after")
                    try:
                        _delai = max(15, int(retry_after))
                    except (TypeError, ValueError):
                        _delai = 15 * (2 ** _tentative)  # 15s, 30s, 60s
                else:
                    _delai = 2 ** _tentative  # 1s, 2s, 4s pour les 5xx
                _derniere_erreur = ConnectionError(f"Erreur GitHub Models ({e.code}) : {detail}")
                _time.sleep(_delai)
                reponse_complete.clear()
                continue
            # 410 = service retiré définitivement — inutile de réessayer
            if e.code == 410:
                raise ConnectionError(
                    "GitHub Models a été retiré définitivement (erreur 410).\n"
                    "Utilisez Ollama en local ou configurez un autre fournisseur IA.\n"
                    f"Détail : {detail}"
                ) from e
            raise ConnectionError(f"Erreur GitHub Models ({e.code}) : {detail}") from e
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Impossible de joindre GitHub Models.\n"
                f"Vérifiez votre connexion Internet.\nDétail : {e}"
            ) from e

    return "".join(reponse_complete)
