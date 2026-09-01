"""Extraction et application des patches de configuration proposes par le LLM.
Extrait de ai_assistant.py pour garder les fichiers a taille raisonnable.
"""

import json
import copy

PATCH_DEBUT = "```config_patch"
PATCH_FIN   = "```"

def extraire_patch(texte):
    """Extrait le bloc JSON patch de la réponse LLM.

    Retourne list[dict] ou None si aucun patch présent.
    Chaque dict : {"chemin": "machines.b1.nom", "valeur": ...}
    """
    debut = texte.find(PATCH_DEBUT)
    if debut == -1:
        return None
    debut_json = debut + len(PATCH_DEBUT)
    fin_json   = texte.find(PATCH_FIN, debut_json)
    if fin_json == -1:
        return None

    brut = texte[debut_json:fin_json].strip()
    try:
        parsed = json.loads(brut)
    except json.JSONDecodeError:
        return None

    # Normaliser en liste
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return None

    # Valider la structure minimale
    for op in parsed:
        if "chemin" not in op or "valeur" not in op:
            return None

    return parsed


def texte_sans_patch(texte):
    """Retourne le texte de la réponse sans le bloc config_patch."""
    debut = texte.find(PATCH_DEBUT)
    if debut == -1:
        return texte
    fin = texte.find(PATCH_FIN, debut + len(PATCH_DEBUT))
    if fin == -1:
        return texte
    return (texte[:debut] + texte[fin + len(PATCH_FIN):]).strip()


def appliquer_patch(config_data, patch_ops):
    """Applique une liste d'opérations de patch sur config_data (en place).

    Retourne (config_modifie, liste_descriptions) :
    - config_modifie : copie modifiée (config_data original non touché)
    - liste_descriptions : texte lisible de chaque changement effectué

    Lève ValueError si un chemin est interdit ou invalide.
    """
    CHEMINS_INTERDITS = {"sol"}   # ne jamais toucher le plan du labo

    config_copy  = copy.deepcopy(config_data)
    descriptions = []

    for op in patch_ops:
        chemin = op["chemin"]
        valeur = op["valeur"]

        parties = chemin.split(".")
        if parties[0] in CHEMINS_INTERDITS:
            raise ValueError(f"Chemin interdit : '{chemin}'")

        # Navigation jusqu'au parent
        noeud = config_copy
        for cle in parties[:-1]:
            if not isinstance(noeud, dict):
                raise ValueError(f"Chemin invalide : '{chemin}'")
            if cle not in noeud:
                noeud[cle] = {}
            noeud = noeud[cle]

        cle_finale  = parties[-1]
        ancienne    = noeud.get(cle_finale, "<absent>")
        noeud[cle_finale] = valeur

        # Description lisible : évite d'afficher tout un dict imbriqué
        if isinstance(valeur, dict) and valeur.get("type") == "TECH_OFFICE":
            nom = valeur.get("nom", cle_finale)
            desc = f"• Nouveau technicien '{nom}' ajouté (fiche complète)"
        elif isinstance(valeur, dict) and "jours" in valeur and "heure_debut" in valeur:
            jours_noms = ["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"]
            jours_str = ", ".join(jours_noms[j] for j in valeur.get("jours", []) if j < 7)
            desc = f"• Horaires créés : {jours_str} de {valeur.get('heure_debut',0):.0f}h à {valeur.get('heure_fin',0):.0f}h"
        elif isinstance(ancienne, dict) and ancienne == {} and isinstance(valeur, dict):
            desc = f"• {chemin} : créé ({len(valeur)} champs)"
        else:
            desc = f"• {chemin} : {ancienne!r} → {valeur!r}"
        descriptions.append(desc)

    return config_copy, descriptions
