"""Fonctions de construction du contexte et des metriques pour l'assistant IA.
Extrait de ai_assistant.py pour garder les fichiers a taille raisonnable.
"""

def _construire_mapping_ids(machines):
    """Construit le tableau de correspondance clé_machine → nom technicien."""
    lignes = ["Correspondance entre identifiants techniques et noms :"]
    for cle, m in machines.items():
        if m.get("type") == "TECH_OFFICE":
            nom = m.get("nom") or cle
            lignes.append(f"  • Technicien '{nom}' → clé : machines.{cle}")
        elif m.get("type") not in ("ENTREE", "SORTIE", "TECH_OFFICE", "REPOS", None):
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
    _TYPES_SPECIAUX = {"ENTREE", "SORTIE", "TECH_OFFICE", "REPOS"}
    machines_actives = [(n, m) for n, m in machines.items()
                        if m.get("type") not in _TYPES_SPECIAUX and m.get("type")]
    lignes.append(f"\nÉQUIPEMENTS ({len(machines_actives)}) :")
    for nom_m, m in machines_actives:
        cap   = m.get("capacite", 4)
        tmep  = m.get("tmep", 0)
        tmr   = m.get("tmr", 0)
        dispo = f"{tmep/(tmep+tmr)*100:.0f}%" if (tmep and tmr) else "non configuré"
        proto_raw = m.get("protocoles", {})
        if isinstance(proto_raw, dict):
            proto = ", ".join(proto_raw.keys()) or "aucun"
        elif isinstance(proto_raw, list):
            proto = ", ".join(str(p) for p in proto_raw) or "aucun"
        else:
            proto = "aucun"
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
    _TYPES_SPECIAUX_CFG = {"ENTREE", "SORTIE", "TECH_OFFICE", "REPOS"}
    equips = [(k, m) for k, m in machines.items()
              if m.get("type") not in _TYPES_SPECIAUX_CFG and m.get("type")]
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
            if not isinstance(protos, dict):
                protos = {}
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
