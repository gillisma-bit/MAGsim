"""Client LLM pour l'assistant IA de MAGsim.

Responsabilités
---------------
- Construire le contexte (config + stats) à injecter dans le prompt système
- Envoyer les messages à Ollama (local) OU à GitHub Models (Claude/GPT via Copilot)
- Extraire les patches de configuration proposés par le LLM
- Appliquer les patches à config_manager avec validation

Ollama       : https://ollama.com  — ollama pull qwen2.5:32b
GitHub Models: https://github.com/marketplace/models — token GitHub (inclus Copilot)
"""

import json
import os
import urllib.request
import urllib.error
import copy

OLLAMA_URL     = "http://localhost:11434/api/chat"
PATCH_DEBUT    = "```config_patch"
PATCH_FIN      = "```"

# ─────────────────────────────────────────────────────────────────────────────
#  Prompt système
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Tu es l'assistant IA de MAGsim, un logiciel de simulation de jumeaux virtuels pour laboratoires médicaux.

IMPORTANT : Tu dois TOUJOURS répondre en français, sans exception. Même si le gestionnaire t'écrit en anglais, réponds en français. N'utilise jamais l'anglais dans tes réponses.

Ton rôle est d'aider les gestionnaires — sans aucune compétence technique — à maintenir la configuration du labo à jour, en leur posant des questions simples en langage naturel et en leur proposant des mises à jour concrètes basées sur les données réelles de simulation.

Ton de communication : tu es décontracte, parfois légèrement humoristique, mais TOUJOURS rigoureux sur les chiffres et les faits. Pense à un collègue expert qui vulgarise avec humour — la blague ne remplace jamais le diagnostic, elle l'accompagne. Ne sois jamais lourd ni forcé dans l'humour : une touche suffit.

== Contexte actuel du laboratoire ==
{contexte}

== Ce que tu dois surveiller en priorité ==
1. COUVERTURE HORAIRE : Y a-t-il des jours de la semaine sans aucun technicien disponible ? Si oui, c'est un risque direct de retard.
2. CHARGE DE TRAVAIL : Y a-t-il des techniciens qui absorbent trop de tubes seuls ? Un technicien surchargé fait plus d'erreurs.
3. EXPÉRIENCE : L'expérience d'un technicien (1-5) affecte directement son taux d'erreur et sa vitesse. Un départ à la retraite non remplacé dégrade la qualité.
4. ÉQUIPEMENTS SATURÉS : Une machine à plus de 85% d'utilisation est un goulot d'étranglement. En dessous de 15%, elle est sous-utilisée.
5. PICS PÉRIODIQUES : Des retards qui se répètent régulièrement (ex. chaque semaine) indiquent presque toujours une absence de couverture ce jour-là.

== Clés techniques pour les mises à jour ==
IMPORTANT : Pour modifier la configuration, tu dois utiliser les clés exactes listées ci-dessous.
{mapping_ids}

Les horaires sont stockés sous la clé "horaires.NOM_TECHNICIEN" (par exemple "horaires.Marc").
Les jours sont des chiffres : 0=Lundi, 1=Mardi, 2=Mercredi, 3=Jeudi, 4=Vendredi, 5=Samedi, 6=Dimanche.

== Format d'une mise à jour proposée ==
Quand tu proposes un changement, inclus EXACTEMENT ce bloc :

```config_patch
[
  {"chemin": "machines.CLE_MACHINE.nom", "valeur": "Nouveau Nom"},
  {"chemin": "machines.CLE_MACHINE.experience", "valeur": 4},
  {"chemin": "horaires.Nouveau Nom.jours", "valeur": [0,1,2,3,4]},
  {"chemin": "horaires.Nouveau Nom.heure_debut", "valeur": 8.0},
  {"chemin": "horaires.Nouveau Nom.heure_fin", "valeur": 16.0}
]
```

== Règles de conduite ==
- Réponds TOUJOURS en français, c'est obligatoire
- Ton décontracté et légèrement humoristique si l'occasion s'y prête, mais les chiffres et analyses restent TOUJOURS précis et complets
- L'humour ne remplace JAMAIS une information : s'il y a un problème, dis-le clairement, même si tu le formules avec légèreté
- N'utilise JAMAIS de jargon technique (JSON, clé, paramètre, variable, etc.)
- Pose UNE seule question à la fois pour collecter les informations manquantes
- Explique toujours ce que tu vas changer et POURQUOI (cite les données de simulation)
- Ne modifie JAMAIS la section "sol" (plan physique du laboratoire)
- Si tu n'es pas sûr d'une clé de machine, pose la question plutôt que de supposer
- BASE-TOI UNIQUEMENT sur le contexte fourni — ne suppose jamais qu'un protocole manque sur une machine sans l'avoir vérifié dans la liste des protocoles de cette machine
- Ne recommande JAMAIS d'ajouter un protocole à une machine si ce protocole est déjà listé pour cette machine dans le contexte
- Si le contexte contient [AUCUNE_SIMULATION_DISPONIBLE], tu n'as AUCUN chiffre réel : réponds avec UNE SEULE phrase courte expliquant qu'il faut d'abord lancer une simulation. NE DONNE PAS de conseils généraux, NE LISTE PAS de points à surveiller, NE parle PAS de charge de travail ni de protocoles. Une phrase, c'est tout.
- Si le gestionnaire te signale qu'un chiffre que tu as cité est incorrect, ne cherche pas d'excuses : reconnaître simplement l'erreur et ne citer que les données du contexte
- Chaque chiffre NUMÉRIQUE que tu cites DOIT provenir MOT POUR MOT d'une ligne de la section "MÉTRIQUES VÉRIFIABLES" — note son numéro [Mx] entre parenthèses à la suite, ex: "3h47min (→ [M6])"
- Chaque numéro [Mx] correspond à UNE SEULE valeur dans les métriques. INTERDICTION ABSOLUE de citer deux chiffres différents avec le même numéro [Mx].
- Ne calcule JAMAIS un chiffre toi-même à partir du contexte (pas de moyenne, pas de ratio, pas de dérivé) : si ce n'est pas déjà calculé dans MÉTRIQUES VÉRIFIABLES avec son [Mx], ne le cite pas.
- Si tu ne peux pas associer un chiffre à un [Mx] unique et précis, ne le cite pas — mets plutôt une phrase qualitative sans chiffre
- Les métriques marquées [CONFIG] décrivent la configuration du labo, PAS ce qui s'est passé pendant la simulation. Ne les cite comme problème observé QUE si la durée simulée est suffisante pour que ces jours aient réellement eu lieu. Par exemple : si la simulation ne dure que 2 jours, NE MENTIONNE PAS les problèmes de couverture du week-end comme cause des dégradations observées — ces jours n'ont tout simplement pas été simulés

== DIAGNOSTIC PROACTIF (RÈGLE ABSOLUE) ==
Dès que le gestionnaire envoie un premier message général ("bonjour", "comment va le labo", "analyse les résultats", "quoi de neuf", "tout va bien ?", etc.) ET que des données de simulation sont disponibles dans le contexte :
1. NE PAS donner de généralités — aller DIRECTEMENT aux problèmes identifiés
2. Lire la section "MÉTRIQUES VÉRIFIABLES" et identifier les valeurs les plus critiques (utilisation machine > 85%, fatigue > 0.5, rejets élevés, jours sans couverture)
3. Citer ces valeurs EXACTEMENT telles qu'elles apparaissent dans MÉTRIQUES VÉRIFIABLES — aucun chiffre inventé
4. Proposer immédiatement une action concrète pour le problème le plus urgent
5. Terminer par UNE question pour confirmer ou prioriser

Structure attendue de la réponse :
- Phrase 1 : nombre de problèmes urgents identifiés
- Phrase 2 : premier problème + chiffre exact de MÉTRIQUES VÉRIFIABLES + conséquence concrète
- Phrase 3 : deuxième problème + chiffre exact de MÉTRIQUES VÉRIFIABLES + conséquence concrète
- Phrase 4 : action proposée pour le problème le plus urgent
- Phrase 5 : question pour prioriser

{metriques}

{memoire}"""

# ─────────────────────────────────────────────────────────────────────────────
#  Constructeur de contexte
# ─────────────────────────────────────────────────────────────────────────────

def _construire_mapping_ids(machines):
    """Construit le tableau de correspondance clé_machine → nom technicien."""
    lignes = ["Correspondance entre identifiants techniques et noms :"]
    for cle, m in machines.items():
        if m.get("type") == "TECH_OFFICE":
            nom = m.get("nom") or cle
            lignes.append(f"  • Technicien '{nom}' → clé : machines.{cle}")
        elif m.get("type") in ("Centrifugeuse", "Automate", "Paillasse"):
            lignes.append(f"  • Équipement '{cle}' ({m.get('type')}) → clé : machines.{cle}")
    return "\n".join(lignes)


# ─── Helpers statistiques pour les métriques ────────────────────────────────

def _fmt_min(mn):
    """Formate un nombre de minutes en '2h05min'."""
    mn = int(mn)
    return f"{mn//60}h{mn%60:02d}min"


def _fmt_t(t_min, JOUR=1440.0):
    """Formate un timestamp SimPy (minutes) en 'j3 à 14h30'."""
    j = int(t_min // JOUR) + 1
    r = int(t_min % JOUR)
    return f"j{j} à {r//60:02d}h{r%60:02d}"


def _serie_resume(vals, times=None):
    """Calcule les stats descriptives d'une série numérique (ignore None).
    Retourne None si vide, sinon dict :
      min, max, moy, fin, tendance (delta moy 1re vs 2e moitié), peak_t (str ou None)
    """
    data = [(i, v) for i, v in enumerate(vals) if v is not None]
    if not data:
        return None
    indices, values = zip(*data)
    vmin = min(values)
    vmax = max(values)
    vmoy = sum(values) / len(values)
    vfin = values[-1]
    peak_local = values.index(vmax)
    global_idx = indices[peak_local]
    peak_t = _fmt_t(times[global_idx]) if (times and global_idx < len(times)) else None
    mid = len(values) // 2
    moy1 = sum(values[:mid]) / mid if mid else vmoy
    moy2 = sum(values[mid:]) / (len(values) - mid) if len(values) - mid else vmoy
    return dict(min=vmin, max=vmax, moy=vmoy, fin=vfin,
                tendance=moy2 - moy1, peak_t=peak_t)


def _detecter_cycles_hebdomadaires(stats_history, times, JOUR=1440.0):
    """Détecte si certains jours de la semaine (relatifs au démarrage de la sim)
    montrent systématiquement des valeurs plus élevées que la moyenne globale.
    Nécessite au moins 2 semaines de données pour être fiable.
    Retourne une liste de chaînes décrivant les patterns trouvés.
    """
    alertes = []
    if not times or times[-1] < 14 * JOUR:
        return alertes  # Moins de 2 semaines → pas assez pour détecter un cycle

    NOMS_J = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

    # Séries temporelles à analyser (clé dans stats_history, label)
    series_scalaires = [
        ("transit_time_pending_max", "Retard max en attente"),
        ("entry",                    "File d'entrée"),
        ("transit_time_rolling",     "Transit glissant"),
    ]
    # + files par machine
    for nom_m in stats_history.get("queues", {}):
        series_scalaires.append((f"__queues__{nom_m}", f"File machine {nom_m}"))
    for nom_m in stats_history.get("busy", {}):
        series_scalaires.append((f"__busy__{nom_m}", f"Utilisation {nom_m}"))

    for cle, label in series_scalaires:
        # Résoudre la série
        if cle.startswith("__queues__"):
            vals = stats_history.get("queues", {}).get(cle[len("__queues__"):], [])
        elif cle.startswith("__busy__"):
            vals = stats_history.get("busy", {}).get(cle[len("__busy__"):], [])
        else:
            vals = stats_history.get(cle, [])

        if not vals or len(vals) != len(times):
            continue

        # Grouper par jour-de-semaine relatif (0 = jour de démarrage)
        par_dow: dict[int, list] = {}
        for t, v in zip(times, vals):
            if v is None:
                continue
            dow = int(t // JOUR) % 7
            par_dow.setdefault(dow, []).append(v)

        # Garder seulement les jours avec au moins 2 occurrences (= au moins 2 semaines)
        moy_par_dow = {d: sum(vs) / len(vs)
                       for d, vs in par_dow.items() if len(vs) >= 2}
        if len(moy_par_dow) < 4:
            continue  # Pas assez de jours différents pour un pattern fiable

        glob_moy = sum(moy_par_dow.values()) / len(moy_par_dow)
        if glob_moy < 1e-6:
            continue  # Série quasi nulle

        # Jours systématiquement ≥ 150% de la moyenne globale
        seuil = glob_moy * 1.5
        jours_critiques = sorted(d for d, m in moy_par_dow.items() if m >= seuil)
        if not jours_critiques:
            continue

        ratio_max = max(moy_par_dow[d] for d in jours_critiques) / glob_moy
        noms_j = [NOMS_J[d % 7] for d in jours_critiques]
        alertes.append(
            f"⚠ Pattern hebdomadaire [{label}] : les {', '.join(noms_j)} montrent "
            f"systématiquement {ratio_max:.1f}x la charge moyenne ({len(par_dow[jours_critiques[0]])} semaines observées)"
        )

    # ── Pattern sur le bien-être par jour de semaine ──
    for nom_t, jours_b in stats_history.get("bienetre", {}).items():
        if not jours_b or len(jours_b) < 14:
            continue
        # jours_b est {jour_num: valeur}
        par_dow_b: dict[int, list] = {}
        for j, v in jours_b.items():
            dow = (j - 1) % 7  # j commence à 1
            par_dow_b.setdefault(dow, []).append(v)
        moy_b = {d: sum(vs) / len(vs) for d, vs in par_dow_b.items() if len(vs) >= 2}
        if len(moy_b) < 4:
            continue
        glob_b = sum(moy_b.values()) / len(moy_b)
        if glob_b < 1e-6:
            continue
        jours_pic = sorted(d for d, m in moy_b.items() if m >= glob_b * 1.4)
        if jours_pic:
            ratio_b = max(moy_b[d] for d in jours_pic) / glob_b
            noms_j  = [NOMS_J[d % 7] for d in jours_pic]
            alertes.append(
                f"⚠ Pattern hebdomadaire [Fatigue {nom_t}] : niveau {ratio_b:.1f}x plus élevé "
                f"les {', '.join(noms_j)} — possiblement lié à la charge ce(s) jour(s)"
            )

    return alertes


def _construire_metriques(stats_history, config):
    """Construit la liste numérotée [M1], [M2]... de tous les chiffres réels de la simulation.
    Chaque série temporelle est résumée avec min, max, moyenne, valeur finale,
    tendance (1re vs 2e moitié) et horodatage du pic — pour permettre au LLM
    d'identifier seul les problèmes sans qu'on lui pré-mâche les conclusions.
    """
    metriques = []
    idx = 1
    JOUR = 1440.0
    JOURS_NOM = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    times = stats_history.get("time", [])

    def add(txt):
        nonlocal idx
        metriques.append(f"  [M{idx}] {txt}")
        idx += 1

    # ── Couverture par jour de semaine (depuis config — pas de calcul LLM) ──
    # IMPORTANT : ces données décrivent la configuration, PAS ce qui a été observé
    # pendant la simulation. Elles sont valides quelle que soit la durée simulée.
    machines = config.get("machines", {}) if config else {}
    horaires = config.get("horaires", {}) if config else {}
    techs = [(n, m) for n, m in machines.items() if m.get("type") == "TECH_OFFICE"]
    if techs:
        couverture_j = {j: [] for j in range(7)}
        for _, m in techs:
            nom = m.get("nom") or "?"
            h_tech = horaires.get(nom, {})
            for j in h_tech.get("jours", list(range(5))):
                couverture_j[j].append(nom)
        metriques.append("  --- Couverture du personnel (configuration) ---")
        for j in range(7):
            noms_j = couverture_j[j]
            if noms_j:
                add(f"[CONFIG] Couverture {JOURS_NOM[j]} : {len(noms_j)} technicien(s) — {', '.join(noms_j)}")
            else:
                add(f"[CONFIG] Couverture {JOURS_NOM[j]} : 0 technicien — AUCUNE COUVERTURE")
        # Résumés précalculés semaine / week-end (évite tout calcul de la part du LLM)
        nb_semaine  = sum(len(couverture_j[j]) for j in range(5))   # lun-ven
        nb_weekend  = sum(len(couverture_j[j]) for j in range(5, 7))
        moy_semaine = nb_semaine / 5
        moy_weekend = nb_weekend / 2
        add(f"[CONFIG] Moyenne techniciens lundi→vendredi : {moy_semaine:.1f} techniciens/jour")
        add(f"[CONFIG] Moyenne techniciens samedi+dimanche : {moy_weekend:.1f} techniciens/jour")
        if moy_semaine > 0 and moy_weekend < moy_semaine:
            ratio_wk = moy_semaine / max(moy_weekend, 0.01)
            add(f"[CONFIG] Écart couverture semaine/week-end : {ratio_wk:.1f}x moins de personnel le week-end")

    nb_j  = times[-1] / JOUR if times else 0

    # ── Durée simulée ──
    if nb_j:
        add(f"Durée simulée : {nb_j:.1f} jours")

    # ── Distribution complète des transits (brut) ──
    raw = [v for v in stats_history.get("transit_times_raw", []) if v is not None]
    if raw:
        raw_s = sorted(raw)
        n = len(raw_s)
        add(f"Nombre total de tubes traités : {n}")
        add(f"Durée de transit minimale : {_fmt_min(raw_s[0])}")
        add(f"Durée de transit moyenne : {_fmt_min(sum(raw_s) / n)}")
        add(f"Durée de transit médiane : {_fmt_min(raw_s[n // 2])}")
        add(f"Durée de transit 95e percentile : {_fmt_min(raw_s[min(int(n * 0.95), n - 1)])}")
        add(f"Durée de transit maximale (âge max d'un tube) : {_fmt_min(raw_s[-1])}")

    # ── Transit glissant : tendance dans le temps ──
    r = _serie_resume(stats_history.get("transit_time_rolling", []), times)
    if r:
        add(f"Transit glissant (20 tubes) — final : {_fmt_min(r['fin'])}, moy : {_fmt_min(r['moy'])}, "
            f"min : {_fmt_min(r['min'])}, max : {_fmt_min(r['max'])} (pic {r['peak_t'] or 'N/A'})")
        sens = "se dégrade" if r['tendance'] > 5 else ("s'améliore" if r['tendance'] < -5 else "stable")
        add(f"Tendance du transit glissant : {sens} ({r['tendance']:+.0f} min entre 1re et 2e moitié)")

    # ── Âge max des tubes en attente (pending_max) ──
    r = _serie_resume(stats_history.get("transit_time_pending_max", []), times)
    if r:
        add(f"Retard max en attente — final : {_fmt_min(r['fin'])}, moy : {_fmt_min(r['moy'])}, "
            f"pic absolu : {_fmt_min(r['max'])} ({r['peak_t'] or 'N/A'})")
        sens = "en hausse" if r['tendance'] > 2 else ("en baisse" if r['tendance'] < -2 else "stable")
        add(f"Tendance du retard maximal : {sens} ({r['tendance']:+.0f} min entre 1re et 2e moitié)")

    # ── File d'entrée ──
    r = _serie_resume(stats_history.get("entry", []), times)
    if r:
        add(f"File d'entrée — moy : {r['moy']:.1f} tubes, pic : {r['max']:.0f} tubes ({r['peak_t'] or 'N/A'}), "
            f"final : {r['fin']:.0f} tubes")
        sens = "s'allonge" if r['tendance'] > 0.5 else ("se réduit" if r['tendance'] < -0.5 else "stable")
        add(f"File d'entrée tendance : {sens}")

    # ── Files par machine (queues + output) ──
    for cle_q, label in (("queues", "File entrée machine"), ("output", "File sortie machine")):
        for nom_m, vals in stats_history.get(cle_q, {}).items():
            r = _serie_resume(vals, times)
            if r and r['max'] > 0:
                add(f"{label} {nom_m} — moy : {r['moy']:.1f}, pic : {r['max']:.0f} ({r['peak_t'] or 'N/A'}), "
                    f"final : {r['fin']:.0f}")
                if r['moy'] > 3 and cle_q == "queues":
                    add(f"  → ⚠ {nom_m} : file d'attente chroniquement longue (moy {r['moy']:.1f} tubes)")

    # ── Utilisation machines ──
    for nom_m, vals in stats_history.get("busy", {}).items():
        r = _serie_resume(vals, times)
        if r is None:
            continue
        pct_moy = r['moy'] * 100
        pct_fin = r['fin'] * 100
        pct_max = r['max'] * 100
        sens = "en hausse" if r['tendance'] > 0.05 else ("en baisse" if r['tendance'] < -0.05 else "stable")
        alerte = " ⚠ SURCHARGÉ" if pct_moy > 85 else (" (sous-utilisé)" if pct_moy < 15 else "")
        add(f"Utilisation {nom_m} : {pct_moy:.0f}% moy / {pct_fin:.0f}% fin / {pct_max:.0f}% max "
            f"— tendance {sens}{alerte}")

    # ── Rejets / dégradés ──
    rejetes  = stats_history.get("rejetes",  [])
    degrades = stats_history.get("degrades", [])
    nb_rej = rejetes[-1]  if rejetes  else 0
    nb_deg = degrades[-1] if degrades else 0
    nb_traites = len(raw) if raw else 1
    if nb_rej or nb_deg:
        add(f"Tubes rejetés : {nb_rej} ({nb_rej / nb_traites * 100:.1f}% des tubes traités)")
        add(f"Tubes dégradés : {nb_deg} ({nb_deg / nb_traites * 100:.1f}% des tubes traités)")
        if nb_j > 0:
            add(f"Rythme de rejets : {nb_rej / nb_j:.1f} rejets/jour en moyenne")

    # ── Pannes ──
    for nom_m, ts in stats_history.get("pannes", {}).items():
        if ts:
            jours_pannes = sorted(set(int(t / JOUR) + 1 for t in ts))
            add(f"Pannes {nom_m} : {len(ts)} panne(s) aux jours {jours_pannes}")
            if len(ts) > 1:
                intervalle_h = (ts[-1] - ts[0]) / max(len(ts) - 1, 1) / 60
                add(f"  → Intervalle moyen entre pannes {nom_m} : {intervalle_h:.0f}h")

    # ── Distances techniciens (avec profil du tech pour contextualiser) ──
    distances  = stats_history.get("distances_tech", {})
    totaux_dist = {}
    # Construire un index rapide nom → (age, experience) depuis la config
    profil_tech = {}
    for _, m in machines.items():
        if m.get("type") == "TECH_OFFICE":
            nom = m.get("nom") or "?"
            profil_tech[nom] = (m.get("age", "?"), m.get("experience", "?"))

    for nom_t, jours_d in distances.items():
        if not jours_d:
            continue
        vals    = list(jours_d.values())
        total_m = sum(vals)
        moy_m   = total_m / len(vals)
        totaux_dist[nom_t] = total_m
        jours_ord = sorted(jours_d.keys())
        vals_ord  = [jours_d[j] for j in jours_ord]
        pic_val   = max(vals_ord)
        j_pic     = jours_ord[vals_ord.index(pic_val)]
        age_t, exp_t = profil_tech.get(nom_t, ("?", "?"))
        add(f"Distance totale {nom_t} (âge {age_t} ans, expérience {exp_t}/5) : "
            f"{total_m:.0f} m — {moy_m:.0f} m/jour — pic j{j_pic} : {pic_val:.0f} m")
        mid2 = len(vals_ord) // 2
        if mid2 and len(vals_ord) - mid2:
            moy1d = sum(vals_ord[:mid2]) / mid2
            moy2d = sum(vals_ord[mid2:]) / (len(vals_ord) - mid2)
            if moy2d > moy1d * 1.2:
                add(f"  → ⚠ {nom_t} marche de plus en plus ({moy1d:.0f} → {moy2d:.0f} m/jour)")
    if len(totaux_dist) >= 2:
        plus_loin  = max(totaux_dist, key=totaux_dist.get)
        moins_loin = min(totaux_dist, key=totaux_dist.get)
        ratio = totaux_dist[plus_loin] / max(totaux_dist[moins_loin], 1)
        if ratio > 1.5:
            age_pl, exp_pl = profil_tech.get(plus_loin, ("?", "?"))
            age_ml, exp_ml = profil_tech.get(moins_loin, ("?", "?"))
            add(f"Écart de distance : {plus_loin} (âge {age_pl}, exp {exp_pl}/5) marche {ratio:.1f}x "
                f"plus que {moins_loin} (âge {age_ml}, exp {exp_ml}/5) — poste potentiellement mal positionné")

    # ── Bien-être techniciens ──
    for nom_t, jours_b in stats_history.get("bienetre", {}).items():
        if not jours_b:
            continue
        vals      = list(jours_b.values())
        debut     = vals[0]
        fin       = vals[-1]
        vmax_b    = max(vals)
        jours_ord = sorted(jours_b.keys())
        deltas    = [jours_b[jours_ord[i + 1]] - jours_b[jours_ord[i]] for i in range(len(jours_ord) - 1)]
        alerte    = " ⚠ CRITIQUE" if fin > 0.7 else (" ⚠ élevé" if fin > 0.5 else "")
        add(f"Fatigue/mécontentement {nom_t} : début {debut:.2f} → fin {fin:.2f} (pic {vmax_b:.2f}){alerte}")
        add(f"  → Variation totale {nom_t} : {fin - debut:+.2f} sur la période")
        if deltas:
            pire_val = max(deltas)
            pire_j   = jours_ord[deltas.index(pire_val)]
            if pire_val > 0.05:
                add(f"  → Plus forte dégradation {nom_t} : j{pire_j} (+{pire_val:.2f} en un jour)")

    # ── Flux arrivées ──
    arrivees = stats_history.get("arrivees_par_heure", {})
    if arrivees:
        total_arr = sum(arrivees.values())
        heure_pic = max(arrivees, key=arrivees.get)
        pct_pic   = arrivees[heure_pic] / total_arr * 100 if total_arr else 0
        top3      = sorted(arrivees.items(), key=lambda x: x[1], reverse=True)[:3]
        add(f"Total tubes arrivés : {total_arr}")
        add(f"Heure de pic d'arrivée : {heure_pic}h ({pct_pic:.0f}% des arrivées en 1h)")
        add(f"Top 3 heures chargées : {', '.join(f'{h}h ({n} tubes)' for h, n in top3)}")
        nocturne = sum(v for h, v in arrivees.items() if int(h) >= 22 or int(h) < 6)
        if nocturne > 0:
            add(f"Arrivées nocturnes (22h-6h) : {nocturne} tubes ({nocturne / total_arr * 100:.0f}%)")

        # ── Croisement flux nocturne × couverture ──
        # Identifier les créneaux sans couverture où des tubes arrivent quand même
        if techs and arrivees:
            # Construire les plages couvertes heure par heure (0-23)
            heures_couvertes = set()
            for _, m_t in techs:
                nom_t = m_t.get("nom") or "?"
                h_tech = horaires.get(nom_t, {})
                hd = int(h_tech.get("heure_debut", 7))
                hf = int(h_tech.get("heure_fin", 15))
                for h in range(hd, hf):
                    heures_couvertes.add(h % 24)

            heures_sans_couverture = {
                h: n for h, n in arrivees.items()
                if n > 0 and (int(h) % 24) not in heures_couvertes
            }
            if heures_sans_couverture:
                total_sans = sum(heures_sans_couverture.values())
                heures_tri = sorted(heures_sans_couverture.items(), key=lambda x: x[1], reverse=True)
                top_h = ", ".join(f"{h}h ({n} tubes)" for h, n in heures_tri[:3])
                add(f"Tubes arrivant SANS COUVERTURE technicien : {total_sans} tubes "
                    f"({total_sans / total_arr * 100:.0f}% du total) — heures les plus chargées : {top_h}")
                add(f"  → ⚠ Ces tubes s'accumulent jusqu'à l'arrivée du premier tech — "
                    f"cela explique directement les pics d'âge max observés en début de journée")

    # ── Arrêts maladie ──
    arrets = [e for e in stats_history.get("events_arret_maladie", []) if e.get("type") == "debut"]
    if arrets:
        noms_arrets = list(dict.fromkeys(e["nom"] for e in arrets))
        add(f"Arrêts maladie : {len(arrets)} épisode(s) — techniciens concernés : {', '.join(noms_arrets)}")

    # ── Patterns hebdomadaires récurrents ──
    cycles = _detecter_cycles_hebdomadaires(stats_history, times)
    if cycles:
        metriques.append("  --- Cycles hebdomadaires détectés ---")
        for c in cycles:
            metriques.append(f"  [M{idx}] {c}")
            idx += 1

    return metriques


# ─────────────────────────────────────────────────────────────────────────────
#  Contexte hiérarchique (agrégateur multi-niveaux)
# ─────────────────────────────────────────────────────────────────────────────

def construire_metriques_aggregateur(aggregator) -> str:
    """Construit le bloc MÉTRIQUES depuis un StatsAggregator (N2+N3).

    Remplace `construire_metriques_block` pour les longues simulations.
    Taille constante quelle que soit la durée simulée.
    """
    try:
        from core.stats_aggregator import StatsAggregator
    except ImportError:
        return ""
    if aggregator is None or aggregator.nb_jours < 0.01:
        return ""

    bloc = aggregator.bloc_vue_globale()
    if not bloc:
        return ""

    lignes = [
        "== MÉTRIQUES VÉRIFIABLES (vue agrégée) ==",
        "Ces données sont calculées sur TOUTE la durée simulée.",
        "Pour chaque chiffre cité, indique entre parenthèses sa provenance, ex: (→ sem.2, j8).",
        bloc,
    ]
    return "\n".join(lignes)


def detecter_zoom(texte: str) -> tuple[str | None, int | None]:
    """Détecte si le message utilisateur demande un zoom sur un jour ou une semaine.

    Retourne (type, index) où type = "jour"|"semaine"|None, index = numéro 0-based.

    Exemples :
      "détail du jour 3"     → ("jour", 2)
      "zoom semaine 2"       → ("semaine", 1)
      "que s'est-il passé j5" → ("jour", 4)
    """
    import re
    t = texte.lower()

    # Jour — "jour 3", "j3", "journée 3", "le 3e jour"
    m = re.search(
        r"(?:jour|journ[eé]e|j)[\s\-]?(\d+)|(\d+)[eè]?(?:re?|ème|eme)?\s+jour",
        t
    )
    if m:
        n = int(m.group(1) or m.group(2))
        if 1 <= n <= 3650:
            return ("jour", n - 1)   # 0-based

    # Semaine — "semaine 2", "sem 2", "la 2e semaine"
    m = re.search(
        r"(?:semaine|sem\.?)[\s\-]?(\d+)|(\d+)[eè]?(?:re?|ème|eme)?\s+semaine",
        t
    )
    if m:
        n = int(m.group(1) or m.group(2))
        if 1 <= n <= 520:
            return ("semaine", n - 1)

    return (None, None)


def construire_bloc_zoom(aggregator, type_zoom: str, index: int) -> str:
    """Génère le bloc texte de zoom à injecter dans le prochain message."""
    if aggregator is None:
        return ""
    if type_zoom == "jour":
        return aggregator.bloc_zoom_jour(index)
    if type_zoom == "semaine":
        return aggregator.bloc_zoom_semaine(index)
    return ""


def construire_contexte(config, stats_history=None):
    """Résumé textuel du labo pour injection dans le prompt."""
    machines  = config.get("machines", {})
    horaires  = config.get("horaires", {})
    JOURS     = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    JOURS_NOM = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

    lignes = []

    # ── Personnel avec couverture ──
    techs = [(n, m) for n, m in machines.items() if m.get("type") == "TECH_OFFICE"]
    lignes.append(f"PERSONNEL ({len(techs)} technicien(s)) :")
    couverture = {j: [] for j in range(7)}
    for nom_m, m in techs:
        nom    = m.get("nom") or nom_m
        exp    = m.get("experience", 3)
        age    = m.get("age", 35)
        h_tech = horaires.get(nom, {})
        jours_t = h_tech.get("jours", list(range(5)))
        hd     = h_tech.get("heure_debut", 7)
        hf     = h_tech.get("heure_fin", 15)
        jours_txt = [JOURS[j] for j in jours_t]
        lignes.append(
            f"  • {nom} (expérience {exp}/5, {age} ans) — "
            f"{', '.join(jours_txt) if jours_txt else 'jours non définis'} "
            f"de {hd:.0f}h à {hf:.0f}h"
        )
        for j in jours_t:
            couverture[j].append(nom)

    # Jours sans couverture
    jours_vides = [JOURS_NOM[j] for j in range(7) if not couverture[j]]
    if jours_vides:
        lignes.append(f"  ⚠ ATTENTION : aucun technicien ces jours : {', '.join(jours_vides)}")
    else:
        lignes.append("  ✓ Couverture assurée tous les jours de la semaine")

    # ── Équipements ──
    types_eq = ("Centrifugeuse", "Automate", "Paillasse")
    machines_actives = [(n, m) for n, m in machines.items() if m.get("type") in types_eq]
    lignes.append(f"\nÉQUIPEMENTS ({len(machines_actives)}) :")
    for nom_m, m in machines_actives:
        cap   = m.get("capacite", 4)
        tmep  = m.get("tmep", 0)
        tmr   = m.get("tmr", 0)
        dispo = f"{tmep/(tmep+tmr)*100:.0f}%" if (tmep and tmr) else "non configuré"
        proto = ", ".join(m.get("protocoles", {}).keys()) or "aucun"
        lignes.append(f"  • {nom_m} ({m.get('type')}) — capacité {cap} — protocoles : {proto} — disponibilité : {dispo}")

    # ── Résumé simulation ──
    if stats_history and stats_history.get("time"):
        times = stats_history["time"]
        JOUR  = 1440.0
        nb_j  = times[-1] / JOUR if times else 0

        lignes.append(f"\nDERNIÈRE SIMULATION ({nb_j:.0f} jours simulés) :")

        # Transit rolling
        tr = [v for v in stats_history.get("transit_time_rolling", []) if v is not None]
        if tr:
            mn = int(tr[-1])
            lignes.append(f"  • Temps de transit final : {mn//60}h{mn%60:02d}min")
            # Tendance : compare 1er quart vs dernier quart
            q = max(1, len(tr) // 4)
            debut_moy = sum(tr[:q]) / q
            fin_moy   = sum(tr[-q:]) / q
            delta     = fin_moy - debut_moy
            if abs(delta) > 5:
                sens = "se dégrade" if delta > 0 else "s'améliore"
                lignes.append(f"  • Tendance : transit {sens} de {abs(delta):.0f} min sur la période")

        # Pending max
        pm = [v for v in stats_history.get("transit_time_pending_max", []) if v is not None]
        if pm:
            mn = int(max(pm))
            lignes.append(f"  • Retard maximum observé : {mn//60}h{mn%60:02d}min")

        # Utilisation par machine depuis stats_history["busy"]
        busy = stats_history.get("busy", {})
        if busy:
            lignes.append("  • Taux d'utilisation des équipements :")
            for nom_m, valeurs in busy.items():
                vals = [v for v in valeurs if v is not None]
                if vals:
                    moy = sum(vals) / len(vals) * 100
                    alerte = " ⚠ SURCHARGÉ" if moy > 85 else (" (sous-utilisé)" if moy < 15 else "")
                    lignes.append(f"    - {nom_m} : {moy:.0f}%{alerte}")

        # Tubes rejetés / dégradés
        rejetes  = stats_history.get("rejetes",  [])
        degrades = stats_history.get("degrades", [])
        nb_rej = rejetes[-1]  if rejetes  else 0
        nb_deg = degrades[-1] if degrades else 0
        if nb_rej or nb_deg:
            lignes.append(f"  • Qualité : {nb_rej} tube(s) rejeté(s), {nb_deg} dégradé(s) sur la période")
            if nb_rej > 10:
                lignes.append("    ⚠ Nombre de rejets élevé — vérifier la qualité des prélèvements ou l'expérience des techniciens")

        # Pannes machines
        pannes = stats_history.get("pannes", {})
        if pannes:
            lignes.append("  • Pannes enregistrées :")
            JOUR = 1440.0
            for nom_m, ts in pannes.items():
                jours_pannes = sorted(set(int(t / JOUR) + 1 for t in ts))
                lignes.append(f"    - {nom_m} : {len(ts)} panne(s) (jours {jours_pannes})")

        # Arrêts maladie
        arrets = [e for e in stats_history.get("events_arret_maladie", []) if e.get("type") == "debut"]
        if arrets:
            noms_arrets = list(dict.fromkeys(e["nom"] for e in arrets))
            lignes.append(f"  • Arrêts maladie : {', '.join(noms_arrets)} ({len(arrets)} épisode(s))")
        else:
            lignes.append("  • Aucun arrêt maladie enregistré")

        # Distances parcourues par technicien
        distances = stats_history.get("distances_tech", {})
        if distances:
            lignes.append("  • Distance parcourue par technicien (par jour) :")
            for nom_t, jours_d in distances.items():
                if jours_d:
                    vals    = list(jours_d.values())
                    moy_m   = sum(vals) / len(vals)
                    total_m = sum(vals)
                    lignes.append(f"    - {nom_t} : {total_m:.0f} m total — {moy_m:.0f} m/jour en moyenne")
            # Identifier le technicien qui marche le plus
            totaux = {n: sum(j.values()) for n, j in distances.items() if j}
            if totaux:
                plus_loin = max(totaux, key=totaux.get)
                moins_loin = min(totaux, key=totaux.get)
                if totaux[plus_loin] > totaux[moins_loin] * 1.5:
                    lignes.append(
                        f"    ⚠ {plus_loin} marche {totaux[plus_loin]/max(totaux[moins_loin],1):.1f}x "
                        f"plus que {moins_loin} — son poste est peut-être mal positionné"
                    )

        # Bien-être / mécontentement techniciens
        bienetre = stats_history.get("bienetre", {})
        if bienetre:
            lignes.append("  • Niveau de fatigue/mécontentement des techniciens (0=serein, 1=épuisé) :")
            for nom_t, jours_b in bienetre.items():
                if jours_b:
                    vals    = list(jours_b.values())
                    moy     = sum(vals) / len(vals)
                    fin     = vals[-1]
                    tendance = " ↗ en hausse" if fin > moy * 1.2 else (" ↘ en baisse" if fin < moy * 0.8 else " → stable")
                    alerte  = " ⚠ CRITIQUE" if fin > 0.7 else (" ⚠ élevé" if fin > 0.5 else "")
                    lignes.append(f"    - {nom_t} : {fin:.2f} en fin de période{tendance}{alerte}")

        # Flux d'arrivées par heure (pic horaire)
        arrivees = stats_history.get("arrivees_par_heure", {})
        if arrivees:
            total_tubes = sum(arrivees.values())
            heure_pic   = max(arrivees, key=arrivees.get)
            pct_pic     = arrivees[heure_pic] / total_tubes * 100 if total_tubes else 0
            lignes.append(
                f"  • Flux d'arrivée : {total_tubes} tubes au total — "
                f"pic à {heure_pic}h ({pct_pic:.0f}% des arrivées)"
            )
            # Top 3 heures chargées
            top3 = sorted(arrivees.items(), key=lambda x: x[1], reverse=True)[:3]
            lignes.append(f"    Heures les plus chargées : {', '.join(f'{h}h ({n} tubes)' for h, n in top3)}")

        # Insights sim_advisor (si disponibles)
        # IMPORTANT : on transmet TOUS les insights avec leur corps COMPLET et leur action.
        # Le sim_advisor calcule des corrélations causales (ex : pic le lundi → tel tech absent)
        # que le LLM ne peut pas déduire seul. Il faut lui servir les conclusions, pas les couper.
        try:
            from core.sim_advisor import analyser
            insights = analyser(stats_history, config)
            if insights:
                lignes.append("\n== ANALYSE AUTOMATIQUE (corrélations et causes identifiées) ==")
                lignes.append("Ces conclusions sont calculées par analyse du code de simulation.")
                lignes.append("Cite-les directement — elles sont fiables et causalement vérifiées.")
                for ins in insights:
                    emoji = {"error": "🔴", "warn": "🟠", "tip": "💡", "info": "ℹ", "ok": "✅"}.get(ins.niveau, "•")
                    lignes.append(f"\n{emoji} [{ins.niveau.upper()}] {ins.titre}")
                    if ins.corps:
                        for line in ins.corps.strip().splitlines():
                            lignes.append(f"   {line}")
                    if ins.action:
                        lignes.append(f"   → Action recommandée : {ins.action.strip()}")
        except Exception:
            pass

    else:
        lignes.append("\n[AUCUNE_SIMULATION_DISPONIBLE]")
        lignes.append("ATTENTION — aucune simulation n'a encore été lancée. Il n'existe donc AUCUNE donnée chiffrée (%, minutes, fatigue, utilisation, rejets, etc.) à analyser.")
        lignes.append("Tu dois informer le gestionnaire qu'il faut d'abord lancer une simulation avant de pouvoir faire une analyse. Ne cite AUCUN chiffre.")

    # ── Configuration brute (RH, protocoles, paramètres machines) ──────────
    lignes.append("\n== CONFIGURATION COMPLÈTE DU LABORATOIRE ==")
    lignes.append("(données brutes — valeurs exactes configurées par le gestionnaire)")

    # Techniciens — paramètres RH complets
    techs_all = [(k, m) for k, m in machines.items() if m.get("type") == "TECH_OFFICE"]
    if techs_all:
        lignes.append("\nPARAMÈTRES RH DES TECHNICIENS :")
        for _, m in techs_all:
            nom   = m.get("nom") or "?"
            exp   = m.get("experience", "?")
            age   = m.get("age", "?")
            pct   = m.get("pct_erreur_tech", "non défini")
            cap   = m.get("capacite_max_tubes", "?")
            seuil_f = m.get("seuil_charge_fatigue", "?")
            montee  = m.get("taux_montee_fatigue", "?")
            recup   = m.get("taux_recuperation_nuit", None)
            h = horaires.get(nom, {})
            jours_t = h.get("jours", [])
            jours_txt = "/".join(JOURS[j] for j in jours_t) if jours_t else "?"
            hd = h.get("heure_debut", "?")
            hf = h.get("heure_fin", "?")
            actif = h.get("actif", True)
            ligne = (
                f"  {nom} : exp={exp}/5, age={age}ans, "
                f"pct_erreur={pct}, capacite_max={cap} tubes, "
                f"seuil_fatigue={seuil_f}, montee_fatigue={montee}"
            )
            if recup is not None:
                ligne += f", recuperation_nuit={recup}"
            ligne += f" | horaire: {jours_txt} {hd}h→{hf}h"
            if not actif:
                ligne += " [INACTIF]"
            lignes.append(ligne)

    # Équipements — paramètres complets avec protocoles et durées
    types_eq = ("Centrifugeuse", "Automate", "Paillasse")
    equips = [(k, m) for k, m in machines.items() if m.get("type") in types_eq]
    if equips:
        lignes.append("\nPARAMÈTRES MACHINES ET PROTOCOLES :")
        for nom_k, m in equips:
            typ      = m.get("type", "?")
            cap      = m.get("capacite", "?")
            seuil    = m.get("seuil", "?")
            fmax     = m.get("file_max", "?")
            tmep     = m.get("tmep", "?")
            tmr      = m.get("tmr", "?")
            degrad   = m.get("delai_max_avant_degrad", "?")
            requis   = m.get("tech_requis_poste", False)
            protos   = m.get("protocoles", {})
            proto_txt = ", ".join(
                f"{pn} ({pv.get('temps','?')} min)" for pn, pv in protos.items()
            ) if protos else "aucun"
            ligne = (
                f"  {nom_k} ({typ}) : capacite={cap}, seuil={seuil}, "
                f"file_max={fmax}, tmep={tmep}h, tmr={tmr}h, "
                f"delai_degrad={degrad}min, tech_requis={requis}"
                f" | protocoles: {proto_txt}"
            )
            lignes.append(ligne)

    # Point d'entrée — profil d'arrivée des tubes
    entree = next((m for m in machines.values() if m.get("type") == "ENTREE"), None)
    if entree:
        lignes.append("\nCONFIGURATION ENTRÉE (flux de tubes) :")
        freq     = entree.get("frequence", "?")
        gamma_k  = entree.get("gamma_k", "?")
        hd_e     = entree.get("heure_debut", "?")
        pct_mv   = entree.get("pct_mauvais_prelevements", "?")
        profil   = entree.get("profil_horaire", [])
        lignes.append(
            f"  fréquence_base={freq} tubes/h, variabilite_gamma_k={gamma_k}, "
            f"heure_debut={hd_e}h, pct_mauvais_prelevements={pct_mv}"
        )
        if profil:
            pts = ", ".join(f"{int(h)}h×{mult}" for h, mult in profil)
            lignes.append(f"  profil_horaire (multiplicateurs): {pts}")

    return "\n".join(lignes)


def construire_metriques_block(config, stats_history):
    """Retourne le bloc MÉTRIQUES VÉRIFIABLES à injecter séparément en fin de prompt."""
    if not stats_history or not stats_history.get("time"):
        return ""
    metriques = _construire_metriques(stats_history, config)
    if not metriques:
        return ""
    lignes = [
        "== MÉTRIQUES VÉRIFIABLES ==",
        "Ces chiffres sont les SEULS que tu peux citer. Pour chaque chiffre dans ta réponse, indique son numéro entre crochets, ex: (→ [M3]).",
        "Si un chiffre n'est pas dans cette liste, n'écris pas ce chiffre — dis plutôt 'je ne dispose pas de cette donnée'.",
    ]
    lignes.extend(metriques)
    return "\n".join(lignes)


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
    "mistral-ai/mistral-small-2503",    # low tier  — 150 req/j, 128k ctx
    "microsoft/phi-4",                  # low tier  — 150 req/j, 16k ctx
]


def github_models_disponible():
    """Vérifie qu'un token GitHub est enregistré (sans test réseau)."""
    return bool(get_cle_github())


def envoyer_messages_github(messages, model="openai/gpt-4.1-mini",
                             on_token=None, timeout=120, stop_event=None):
    """Envoie une conversation à GitHub Models (format OpenAI compatible).

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
    req  = urllib.request.Request(
        GITHUB_MODELS_URL,
        data=body,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {cle}",
        },
        method="POST",
    )

    reponse_complete = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
    except urllib.error.HTTPError as e:
        corps = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(corps).get("error", {}).get("message", corps)
        except Exception:
            detail = corps
        raise ConnectionError(f"Erreur GitHub Models ({e.code}) : {detail}") from e
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"Impossible de joindre GitHub Models.\n"
            f"Vérifiez votre connexion Internet.\nDétail : {e}"
        ) from e

    return "".join(reponse_complete)

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
        descriptions.append(f"• {chemin} : {ancienne!r} → {valeur!r}")

    return config_copy, descriptions


# ─────────────────────────────────────────────────────────────────────────────
#  Gestionnaire de conversation
# ─────────────────────────────────────────────────────────────────────────────

class Conversation:
    """Maintient l'historique de la conversation et le prompt système.

    Parameters
    ----------
    model   : str — nom du modèle (Ollama ou Claude selon backend)
    backend : str — "ollama" (défaut) ou "anthropic"
    """

    def __init__(self, model="llama3", backend="ollama"):
        self.model    = model
        self.backend  = backend   # "ollama" | "github"
        self.messages = []
        self._system  = ""
        self._has_simulation = False
        self._config  = None
        self._stats_history = None
        self._aggregator    = None   # StatsAggregator optionnel (longues simulations)
        self._dernieres_metriques: str = ""  # dernier bloc [M1][M2]... pour le bouton Sources

    def _construire_bloc_metriques(self, stats_history):
        """Choisit la source de métriques : agrégateur (vue compacte) + métriques enrichies toujours."""
        parties = []

        # Bloc agrégateur (vue compacte des tendances journalières) si disponible
        if self._aggregator is not None and self._aggregator.nb_jours >= 1.0:
            bloc_agg = construire_metriques_aggregateur(self._aggregator)
            if bloc_agg:
                parties.append(bloc_agg)

        # Métriques enrichies [M1][M2]... : toujours incluses (couverture, distances,
        # flux nocturne, profils tech, pannes, rejets…) — taille bornée quelle que
        # soit la durée simulée (résumés statistiques, pas de données brutes).
        bloc_rich = construire_metriques_block(self._config, stats_history)
        if bloc_rich:
            parties.append(bloc_rich)

        bloc = "\n\n".join(parties) if parties else ""
        self._dernieres_metriques = bloc
        return bloc

    def _build_system(self, config, stats_history):
        from core.ai_memory import construire_section_memoire, get_prenom_gestionnaire
        contexte    = construire_contexte(config, stats_history)
        metriques   = self._construire_bloc_metriques(stats_history)
        mapping_ids = _construire_mapping_ids(config.get("machines", {}))
        nom_labo    = config.get("nom_projet", "")
        memoire     = construire_section_memoire(nom_labo)
        prenom      = get_prenom_gestionnaire()
        profil_txt  = (
            f"\n== Profil du gestionnaire ==\n"
            f"Son prénom est {prenom}. Utilise son prénom pour personnaliser tes réponses."
        ) if prenom else ""
        return (
            _SYSTEM_PROMPT
            .replace("{contexte}",    contexte)
            .replace("{metriques}",   metriques)
            .replace("{mapping_ids}", mapping_ids)
            .replace("{memoire}",     memoire + profil_txt)
        )

    def initialiser(self, config, stats_history=None, aggregator=None):
        """Construit le prompt système avec le contexte du labo."""
        self._config      = config
        self._stats_history = stats_history
        self._aggregator  = aggregator
        self._has_simulation = bool(
            (aggregator and aggregator.nb_jours >= 0.01)
            or (stats_history and stats_history.get("time"))
        )
        self._system  = self._build_system(config, stats_history)
        self.messages = []

    def actualiser_contexte(self, stats_history, aggregator=None):
        """Reconstruit le prompt système avec de nouvelles stats, sans effacer l'historique."""
        if self._config is None:
            return
        self._stats_history = stats_history
        if aggregator is not None:
            self._aggregator = aggregator
        self._has_simulation = bool(
            (self._aggregator and self._aggregator.nb_jours >= 0.01)
            or (stats_history and stats_history.get("time"))
        )
        self._system = self._build_system(self._config, stats_history)

    def ajouter_message_utilisateur(self, texte):
        self.messages.append({"role": "user", "content": texte})

    def ajouter_message_assistant(self, texte):
        self.messages.append({"role": "assistant", "content": texte})

    def _messages_complets(self):
        """Ajoute le message système en tête."""
        return [{"role": "system", "content": self._system}] + self.messages

    def envoyer(self, texte_utilisateur, on_token=None, stop_event=None):
        """Envoie un message et retourne la réponse brute du LLM."""
        from core.ai_memory import detecter_et_sauver_prenom, get_prenom_gestionnaire
        # Détecter si l'utilisateur donne son prénom, et l'injecter dans le système si nouveau
        prenom_detecte = detecter_et_sauver_prenom(texte_utilisateur)
        if prenom_detecte:
            profil_txt = (
                f"\n== Profil du gestionnaire ==\n"
                f"Son prénom est {prenom_detecte}. Utilise son prénom pour personnaliser tes réponses."
            )
            if "== Profil du gestionnaire ==" not in self._system:
                self._system += profil_txt
            else:
                import re
                self._system = re.sub(
                    r"== Profil du gestionnaire ==.*",
                    profil_txt.strip(),
                    self._system,
                    flags=re.DOTALL,
                )

        # ── Zoom : détecter "jour X" ou "semaine X" et injecter le détail N1/N2
        zoom_prefix = ""
        if self._aggregator is not None:
            type_zoom, idx_zoom = detecter_zoom(texte_utilisateur)
            if type_zoom is not None:
                bloc_zoom = construire_bloc_zoom(self._aggregator, type_zoom, idx_zoom)
                if bloc_zoom:
                    zoom_prefix = (
                        f"[Données détaillées injectées automatiquement — niveau zoom]\n"
                        f"{bloc_zoom}\n\n"
                        f"[Fin des données de zoom — utilise ces chiffres pour répondre]\n\n"
                    )

        # Sur le premier message, injecter un rappel de langue + instruction de diagnostic
        if not self.messages:
            if self._has_simulation:
                rappel_sim = (
                    "[Rappel : réponds UNIQUEMENT en français]\n"
                    "[Rappel : si des données de simulation sont disponibles, commence par citer "
                    "les problèmes concrets identifiés avec leurs chiffres exacts — pas de généralités]\n\n"
                )
            else:
                rappel_sim = (
                    "[Rappel : réponds UNIQUEMENT en français]\n"
                    "[INSTRUCTION STRICTE : le contexte indique [AUCUNE_SIMULATION_DISPONIBLE]. "
                    "Ta réponse doit contenir UNE SEULE phrase courte : invite le gestionnaire à lancer une simulation. "
                    "RIEN D'AUTRE. Pas de liste, pas de conseils généraux, pas de points à surveiller. "
                    "Une phrase.]\n\n"
                )
            contenu_envoye = rappel_sim + zoom_prefix + texte_utilisateur
        else:
            contenu_envoye = zoom_prefix + texte_utilisateur

        self.ajouter_message_utilisateur(contenu_envoye)
        if self.backend == "github":
            reponse = envoyer_messages_github(
                messages=self._messages_complets(),
                model=self.model,
                on_token=on_token,
                stop_event=stop_event,
            )
        else:  # ollama (défaut)
            reponse = envoyer_messages(
                self._messages_complets(),
                model=self.model,
                on_token=on_token,
                stop_event=stop_event,
            )
        self.ajouter_message_assistant(reponse)
        return reponse

    def reinitialiser(self):
        self.messages = []
