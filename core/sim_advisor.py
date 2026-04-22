"""Conseiller de simulation — analyses de patterns dans stats_history.

Principe
--------
Chaque fonction analyse une dimension précise (périodicité, couverture,
corrélation maladie, etc.) et retourne une liste d'Insight.

La fonction ``analyser()`` agrège tout et renvoie une liste ordonnée par
sévérité, prête à être affichée dans l'onglet Diagnostic.

Les fonctions sont sans dépendance Tkinter : elles sont testables
en isolation (cf. tests/).
"""

from collections import Counter
import math


JOURS_NOM = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
JOUR = 1440.0   # minutes SimPy par jour calendaire


# ─────────────────────────────────────────────────────────────────────────────
#  Structure de données
# ─────────────────────────────────────────────────────────────────────────────

class Insight:
    """Un conseil factuel issu de l'analyse de simulation."""

    NIVEAUX = ("ok", "info", "tip", "warn", "error")
    _ORDRE  = {n: i for i, n in enumerate(NIVEAUX)}

    def __init__(self, niveau, titre, corps, action=""):
        if niveau not in self.NIVEAUX:
            niveau = "info"
        self.niveau = niveau
        self.titre  = titre
        self.corps  = corps    # faits observés (texte multiligne)
        self.action = action   # recommandation concrète

    def __repr__(self):
        return f"<Insight [{self.niveau}] {self.titre!r}>"

    @property
    def poids(self):
        return self._ORDRE[self.niveau]


# ─────────────────────────────────────────────────────────────────────────────
#  Point d'entrée
# ─────────────────────────────────────────────────────────────────────────────

def analyser(hist, config):
    """Analyse complète. Retourne list[Insight] trié par sévérité décroissante."""
    insights = []

    # Analyses purement config (pas besoin de données sim)
    insights.extend(_analyser_couverture_horaire(config))

    # Analyses depuis simulation
    if hist and hist.get("time"):
        insights.extend(_analyser_pics_periodiques(hist, config))
        insights.extend(_analyser_correlation_maladie(hist))
        insights.extend(_analyser_tendance_transit(hist))
        insights.extend(_analyser_saturation_chronique(hist))
        insights.extend(_analyser_accumulation_entree(hist, config))
        insights.extend(_analyser_erreurs_par_periode(hist, config))
        insights.extend(_analyser_accumulation_nocturne(hist, config))

    # Trier : erreurs d'abord, ok à la fin
    insights.sort(key=lambda i: -i.poids)
    return insights


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_duree(minutes):
    """'1h 05min' ou '42 min'."""
    m = int(round(minutes))
    if m >= 60:
        return f"{m // 60}h {m % 60:02d}min"
    return f"{m} min"


def _mediane(valeurs):
    sv = sorted(valeurs)
    n = len(sv)
    return (sv[n // 2] + sv[(n - 1) // 2]) / 2.0 if n else 0.0


def _stats_fenetre(times, valeurs, t_debut, t_fin):
    """Retourne (moyenne, max) des valeurs non-None dans [t_debut, t_fin[."""
    v = [v for t, v in zip(times, valeurs) if v is not None and t_debut <= t < t_fin]
    if not v:
        return None, None
    return sum(v) / len(v), max(v)


# ─────────────────────────────────────────────────────────────────────────────
#  1. Couverture horaire (analyse config uniquement)
# ─────────────────────────────────────────────────────────────────────────────

def _analyser_couverture_horaire(config):
    """Détecte les jours ou créneaux sans technicien planifié."""
    insights = []
    horaires = config.get("horaires", {})
    if not horaires:
        return insights

    # Compter le nombre de techs actifs par jour de semaine
    coverage = {}  # jour_idx -> list of (nom, h_debut, h_fin)
    for nom, h in horaires.items():
        if not h.get("actif", True):
            continue
        for j in h.get("jours", []):
            coverage.setdefault(j, []).append(
                (nom, float(h.get("heure_debut", 7)), float(h.get("heure_fin", 15)))
            )

    jours_vides = [j for j in range(7) if j not in coverage or not coverage[j]]

    if coverage:
        nb_moyen = sum(len(v) for v in coverage.values()) / max(1, len(coverage))
        jours_reduits = [
            (j, len(coverage[j]))
            for j in range(7)
            if j in coverage and 0 < len(coverage[j]) < nb_moyen * 0.6
        ]
    else:
        nb_moyen = 0
        jours_reduits = []

    if jours_vides:
        noms_j = ", ".join(JOURS_NOM[j] for j in jours_vides)
        insights.append(Insight(
            "error",
            f"Aucun technicien disponible : {noms_j}",
            f"Les tubes qui arrivent ces jours-là s'accumulent indéfiniment.\n"
            f"Jours sans couverture : {noms_j}.",
            "Assignez au moins un technicien de garde ces jours-là\n"
            "dans l'onglet Horaires.",
        ))

    if jours_reduits:
        detail = ", ".join(
            f"{JOURS_NOM[j]} ({n} tech vs {nb_moyen:.1f} en moyenne)"
            for j, n in jours_reduits
        )
        insights.append(Insight(
            "warn",
            "Couverture réduite certains jours de la semaine",
            f"Jours avec moins de techniciens que la normale :\n{detail}.\n"
            "Si le flux est identique, un seul tech peut créer un goulot.",
            "Vérifiez la charge réelle de ces jours (lancer 30 jours de sim\n"
            "et observer les pics dans l'onglet Stats).",
        ))

    # ── Détection des trous horaires dans la journée ──────────────────────────
    # Pour chaque jour, construire un tableau heure par heure (0-23) indiquant
    # si au moins un tech est présent, en tenant compte des quarts traversant minuit.
    machines = config.get("machines", {})
    entree_cfg = next(
        (m for m in machines.values() if m.get("type") == "ENTREE"),
        {}
    )
    profil_arrivees = entree_cfg.get("profil_horaire", [])
    arrivees_par_h = {int(h): float(f) for h, f in profil_arrivees} if profil_arrivees else {}

    jours_avec_trou = {}  # jour -> [(h_debut_trou, h_fin_trou), ...]
    for j in range(7):
        if j in jours_vides:
            continue  # déjà signalé
        techs_ce_jour = coverage.get(j, [])
        techs_veille = coverage.get((j - 1) % 7, [])

        couvert = [False] * 24
        for _, hd, hf in techs_ce_jour:
            if hd < hf:
                # Quart normal (ex: 8h-16h)
                for h in range(int(hd), int(hf)):
                    couvert[h % 24] = True
            else:
                # Quart traversant minuit (ex: 16h-8h) — portion soirée
                for h in range(int(hd), 24):
                    couvert[h] = True
        for _, hd, hf in techs_veille:
            if hd >= hf:
                # Quart traversant minuit — portion matin (h=0 à hf)
                for h in range(0, int(hf)):
                    couvert[h] = True

        # Trouver les trous : séquences d'heures non couvertes
        trous = []
        i = 0
        while i < 24:
            if not couvert[i]:
                debut = i
                while i < 24 and not couvert[i]:
                    i += 1
                fin = i
                trous.append((debut, fin))
            else:
                i += 1
        if trous:
            jours_avec_trou[j] = trous

    if jours_avec_trou:
        lignes = []
        for j, trous in sorted(jours_avec_trou.items()):
            for hd, hf in trous:
                duree = hf - hd
                # Calculer le charge normalisée dans ce trou
                charge = sum(arrivees_par_h.get(h % 24, 0) for h in range(hd, hf))
                charge_max = max(arrivees_par_h.values()) if arrivees_par_h else 1
                pct = round(charge / charge_max * 100) if charge_max else 0
                lignes.append(f"• {JOURS_NOM[j]} {hd:02d}h–{hf:02d}h ({duree}h, {pct}% flux)")
        detail_trous = "\n".join(lignes)
        insights.append(Insight(
            "error",
            "Trous de couverture horaire détectés",
            f"Des tubes arrivent pendant des créneaux sans technicien.\n"
            f"Ces tubes s'accumulent et atteignent des âges élevés :\n{detail_trous}\n\n"
            f"L'âge max constaté en simulation reflète directement la durée du trou le plus long.",
            "Vérifiez que les quarts s'enchaînent sans interruption (heure_fin du quart A\n"
            "= heure_debut du quart B). Ajoutez une garde ou étendez un quart pour couvrir\n"
            "les créneaux manquants, même à faible flux.",
        ))

    return insights


# ─────────────────────────────────────────────────────────────────────────────
#  2. Pics périodiques dans pending_max
# ─────────────────────────────────────────────────────────────────────────────

def _analyser_pics_periodiques(hist, config):
    """Détecte des pics récurrents (= même intervalle) et identifie leur cause."""
    insights = []

    times   = hist.get("time", [])
    pending = hist.get("transit_time_pending_max", [])

    if not times or not pending or times[-1] < 7 * JOUR:
        return insights

    # ── Calcul du seuil : 2.5× la médiane, minimum 2 h ──
    vals_non_null = [v for v in pending if v is not None]
    if not vals_non_null:
        return insights
    med = _mediane(vals_non_null)
    seuil = max(med * 2.5, 120.0)

    # ── Détection des pics (segments au-dessus du seuil) ──
    pics = []   # [(t_sommet, v_sommet)]
    en_pic = False
    t_sommet = v_sommet = None

    for t, v in zip(times, pending):
        if v is None:
            continue
        if v > seuil:
            if not en_pic:
                en_pic, t_sommet, v_sommet = True, t, v
            elif v > v_sommet:
                t_sommet, v_sommet = t, v
        else:
            if en_pic:
                pics.append((t_sommet, v_sommet))
                en_pic = False
    if en_pic and t_sommet is not None:
        pics.append((t_sommet, v_sommet))

    if len(pics) < 2:
        return insights

    # ── Vérifier la périodicité (tolérance ±25 %) ──
    intervalles = [pics[i + 1][0] - pics[i][0] for i in range(len(pics) - 1)]
    iv_med = _mediane(intervalles)
    if iv_med <= 0:
        return insights
    periodique = all(abs(iv - iv_med) / iv_med < 0.30 for iv in intervalles)
    if not periodique:
        return insights

    nb_jours_periode = iv_med / JOUR
    jour_debut_sim   = int(config.get("personnel", {}).get("jour_debut_simulation", 0))

    # ── Jour de la semaine des pics ──
    jours_pics = [(jour_debut_sim + int(t / JOUR)) % 7 for t, _ in pics]
    cnt = Counter(jours_pics)
    jour_typique = cnt.most_common(1)[0][0]

    # ── Chercher les techs absents ce jour-là ──
    horaires = config.get("horaires", {})
    absents = [
        nom for nom, h in horaires.items()
        if h.get("actif", True)
        and jour_typique not in h.get("jours", list(range(7)))
    ]

    v_max = max(v for _, v in pics)

    if abs(nb_jours_periode - 7.0) < 1.5:
        periode_txt = "chaque semaine"
    else:
        periode_txt = f"tous les ~{nb_jours_periode:.1f} jours"

    corps = (
        f"• {len(pics)} pics détectés sur {times[-1]/JOUR:.0f} jours simulés\n"
        f"• Intervalle régulier : {periode_txt} (≈ {nb_jours_periode:.1f} j)\n"
        f"• Retard maximum lors d'un pic : {_fmt_duree(v_max)}\n"
        f"• Pics survenant typiquement le : {JOURS_NOM[jour_typique]}"
    )

    if absents:
        noms_abs = ", ".join(absents)
        corps += f"\n• Technicien(s) absent(s) le {JOURS_NOM[jour_typique]} : {noms_abs}"
        action = (
            f"Cause identifiée : {noms_abs} ne travaillent pas le {JOURS_NOM[jour_typique]}.\n"
            f"Les tubes s'accumulent faute de transporteur disponible.\n"
            f"→ Activez leur présence dans l'onglet Horaires,\n"
            f"  ou planifiez un remplaçant ce jour-là."
        )
        niveau = "error" if v_max > 240 else "warn"
    else:
        action = (
            f"Les pics surviennent le {JOURS_NOM[jour_typique]} sans absence identifiée.\n"
            f"→ Vérifiez si le flux d'arrivée est plus élevé ce jour,\n"
            f"  ou si une machine est fréquemment en panne."
        )
        niveau = "warn"

    insights.append(Insight(
        niveau,
        f"Pics récurrents {periode_txt} — {_fmt_duree(v_max)} de retard",
        corps,
        action,
    ))
    return insights


# ─────────────────────────────────────────────────────────────────────────────
#  3. Corrélation arrêts maladie ↔ transit
# ─────────────────────────────────────────────────────────────────────────────

def _analyser_correlation_maladie(hist):
    """Mesure si le pending_max augmente après chaque arrêt maladie."""
    insights = []

    events  = [e for e in hist.get("events_arret_maladie", []) if e.get("type") == "debut"]
    times   = hist.get("time", [])
    pending = hist.get("transit_time_pending_max", [])

    if not events or not times or not pending:
        return insights

    FENETRE = 4 * JOUR   # 4 jours

    correlations = []
    for ev in events:
        t_ev = ev["t"]
        moy_av, _ = _stats_fenetre(times, pending, t_ev - FENETRE, t_ev)
        moy_ap, _ = _stats_fenetre(times, pending, t_ev, t_ev + FENETRE)
        if moy_av is not None and moy_ap is not None and moy_av > 0:
            ratio = moy_ap / moy_av
            if ratio > 1.5:
                correlations.append({
                    "nom":   ev["nom"],
                    "avant": moy_av,
                    "apres": moy_ap,
                    "ratio": ratio,
                })

    if not correlations:
        return insights

    detail = "\n".join(
        f"• {c['nom']} : transit moyen ×{c['ratio']:.1f} "
        f"({_fmt_duree(c['avant'])} → {_fmt_duree(c['apres'])})"
        for c in correlations
    )
    insights.append(Insight(
        "warn",
        f"Arrêts maladie corrélés au retard ({len(correlations)} arrêt(s))",
        f"Chaque arrêt maladie est systématiquement suivi d'un allongement\n"
        f"du temps de transit :\n{detail}",
        "Ces techniciens sont des maillons critiques sans remplacement.\n"
        "→ Évaluez l'impact avec Tests → Désactiver arrêts maladie\n"
        "  pour mesurer la part due au planning vs aléatoire.",
    ))
    return insights


# ─────────────────────────────────────────────────────────────────────────────
#  4. Tendance du transit dans le temps
# ─────────────────────────────────────────────────────────────────────────────

def _analyser_tendance_transit(hist):
    """Détecte si le temps de transit se dégrade au fil de la simulation."""
    insights = []

    transit_roll = [v for v in hist.get("transit_time_rolling", []) if v is not None]
    if len(transit_roll) < 20:
        return insights

    quart = max(1, len(transit_roll) // 4)
    moy_debut = sum(transit_roll[:quart]) / quart
    moy_fin   = sum(transit_roll[-quart:]) / quart

    if moy_debut <= 0:
        return insights

    ratio = moy_fin / moy_debut

    if ratio > 1.40:
        insights.append(Insight(
            "error",
            "Transit en forte dégradation",
            f"Le temps de transit a augmenté de ×{ratio:.1f} entre\n"
            f"le début ({_fmt_duree(moy_debut)}) et la fin ({_fmt_duree(moy_fin)}) de la simulation.\n"
            f"Le système accumule du retard de façon cumulative.",
            "Le labo est en sous-capacité structurelle.\n"
            "→ Réduisez la fréquence d'arrivée, ajoutez une machine\n"
            "  ou un technicien supplémentaire.",
        ))
    elif ratio > 1.20:
        insights.append(Insight(
            "warn",
            "Tendance à la dégradation du transit",
            f"Transit : {_fmt_duree(moy_debut)} en début → {_fmt_duree(moy_fin)} en fin "
            f"(+{(ratio-1)*100:.0f}%).\n"
            f"Le retard s'accumule lentement mais continûment.",
            "Surveillez sur des simulations plus longues.\n"
            "→ Vérifiez les machines en goulot dans l'onglet Stats.",
        ))
    elif ratio < 0.80:
        insights.append(Insight(
            "ok",
            "Transit en amélioration",
            f"Le système absorbe mieux la charge au fil du temps :\n"
            f"{_fmt_duree(moy_debut)} → {_fmt_duree(moy_fin)} (−{(1-ratio)*100:.0f}%).",
            "",
        ))

    return insights


# ─────────────────────────────────────────────────────────────────────────────
#  5. Saturation chronique des machines
# ─────────────────────────────────────────────────────────────────────────────

def _analyser_saturation_chronique(hist):
    """Identifie les machines structurellement saturées (> 85 % du temps)."""
    insights = []
    busy = hist.get("busy", {})

    saturees   = []
    sous_util  = []

    for nom, raw in busy.items():
        if not raw:
            continue
        pct = sum(raw) / len(raw) * 100
        if pct > 85:
            saturees.append((nom, pct))
        elif pct < 15:
            sous_util.append((nom, pct))

    if saturees:
        detail = "\n".join(f"• {n} : {p:.0f}% d'occupation" for n, p in saturees)
        insights.append(Insight(
            "warn",
            f"{len(saturees)} machine(s) saturée(s) en permanence",
            f"{detail}\n"
            f"Ces machines sont le goulot principal du flux.",
            "→ Doublez la capacité ou ajoutez une machine parallèle\n"
            "  pour ces étapes.\n"
            "→ Activez Tests → Désactiver arrêts maladie pour vérifier\n"
            "  si la saturation est aggravée par les absences.",
        ))

    if sous_util:
        insights.append(Insight(
            "info",
            f"{len(sous_util)} machine(s) peu utilisée(s)",
            "\n".join(f"• {n} : {p:.0f}% d'occupation" for n, p in sous_util),
            "Ces machines pourraient absorber d'autres protocoles\n"
            "ou être désactivées pour réduire les coûts.",
        ))

    return insights


# ─────────────────────────────────────────────────────────────────────────────
#  6. Accumulation à l'entrée
# ─────────────────────────────────────────────────────────────────────────────

def _analyser_accumulation_entree(hist, config):
    """Alerte si la file d'entrée atteint des niveaux problématiques."""
    insights = []
    entry = hist.get("entry", [])
    if not entry:
        return insights

    max_entree = max(entry)
    moy_entree = sum(entry) / len(entry)
    personnel  = config.get("personnel", {})
    seuil      = float(personnel.get("seuil_accumulation_alerte", 20))

    if max_entree > seuil * 3:
        insights.append(Insight(
            "error",
            f"File d'entrée critique : {max_entree} tubes en attente",
            f"• Maximum atteint : {max_entree} tubes\n"
            f"• Moyenne          : {moy_entree:.1f} tubes\n"
            f"• Seuil configuré  : {seuil:.0f} tubes",
            "Le labo ne peut pas absorber le flux actuel.\n"
            "→ Réduisez la fréquence d'arrivée (param. ENTREE)\n"
            "  ou ajoutez un/des technicien(s) supplémentaire(s).",
        ))
    elif max_entree > seuil:
        insights.append(Insight(
            "warn",
            f"File d'entrée élevée : pic à {max_entree} tubes",
            f"• Maximum atteint : {max_entree} tubes\n"
            f"• Moyenne          : {moy_entree:.1f} tubes\n"
            f"• Seuil d'alerte   : {seuil:.0f} tubes",
            "Des pics d'accumulation sont observés.\n"
            "→ Vérifiez si les pics coïncident avec des absences\n"
            "  ou des pannes machines dans l'onglet Stats.",
        ))

    return insights


# ─────────────────────────────────────────────────────────────────────────────
#  7. Corrélation erreurs / techs sans pct_erreur
# ─────────────────────────────────────────────────────────────────────────────

def _analyser_erreurs_par_periode(hist, config):
    """Détecte si la courbe cumulée des erreurs est plate sur certains créneaux.

    Cause typique : techs avec pct_erreur_base = 0 — leurs heures de travail
    ne génèrent aucune erreur, créant des paliers bien visibles dans le graphe.
    """
    insights = []
    rejetes = hist.get("rejetes", [])
    times   = hist.get("time",    [])
    if len(rejetes) < 10 or not times:
        return insights

    machines = config.get("machines", {})
    horaires = config.get("horaires", {})

    techs_sans_erreur = []
    for _, m in machines.items():
        if m.get("type") != "TECH_OFFICE":
            continue
        nom = m.get("nom") or ""
        pct = m.get("pct_erreur_tech", None)
        if pct is not None and float(pct) == 0.0:
            h = horaires.get(nom, {})
            hd = h.get("heure_debut", "?")
            hf = h.get("heure_fin",   "?")
            jours = h.get("jours", [])
            jours_txt = ", ".join(JOURS_NOM[j] for j in jours) if jours else "?"
            techs_sans_erreur.append(f"{nom} ({jours_txt} {hd}h→{hf}h)")

    # Détecter des paliers : segments où rejetes[i] == rejetes[i-1] sur ≥10 points
    nb_plats = sum(1 for i in range(1, len(rejetes)) if rejetes[i] == rejetes[i - 1])
    pct_plat = nb_plats / max(len(rejetes) - 1, 1)

    if pct_plat > 0.3 and techs_sans_erreur:
        insights.append(Insight(
            "info",
            "Courbe d'erreurs plate sur une partie des créneaux",
            f"• {pct_plat*100:.0f}% des intervalles de temps n'enregistrent aucune erreur\n"
            f"• Technicien(s) configuré(s) avec taux d'erreur = 0 % :\n"
            + "\n".join(f"    - {t}" for t in techs_sans_erreur)
            + "\n• Leurs heures de travail ne contribuent donc jamais au compteur de rejets.",
            "Ce comportement est normal si ces techs sont experts ou si vous avez\n"
            "voulu exclure certains créneaux de l'analyse d'erreurs.\n"
            "→ Si vous souhaitez un modèle plus réaliste, assignez un taux > 0\n"
            "  (ex: 0.005) dans la configuration du technicien.",
        ))
    return insights


# ─────────────────────────────────────────────────────────────────────────────
#  8. Accumulation nocturne (tubes sans couverture la nuit)
# ─────────────────────────────────────────────────────────────────────────────

def _analyser_accumulation_nocturne(hist, config):
    """Détecte si des tubes arrivent la nuit alors qu'aucun tech n'est disponible,
    et corrèle avec le pic d'âge maximum observé en début de matinée."""
    insights = []
    arrivees = hist.get("arrivees_par_heure", {})
    pending  = hist.get("transit_time_pending_max", [])
    times    = hist.get("time", [])
    if not arrivees or not pending or not times:
        return insights

    horaires = config.get("horaires", {})
    machines = config.get("machines", {})

    # Construire la couverture heure par heure (0-23)
    heures_couvertes = set()
    for _, m in machines.items():
        if m.get("type") != "TECH_OFFICE":
            continue
        nom = m.get("nom") or ""
        h = horaires.get(nom, {})
        if not h.get("actif", True):
            continue
        hd = int(float(h.get("heure_debut", 7)))
        hf = int(float(h.get("heure_fin",   15)))
        if hd < hf:
            for hr in range(hd, hf):
                heures_couvertes.add(hr)
        else:  # quart de nuit traversant minuit
            for hr in list(range(hd, 24)) + list(range(0, hf)):
                heures_couvertes.add(hr)

    heures_sans = {
        int(h): n for h, n in arrivees.items()
        if n > 0 and (int(h) % 24) not in heures_couvertes
    }
    if not heures_sans:
        return insights

    total_sans   = sum(heures_sans.values())
    total_arrive = sum(arrivees.values())
    pct          = total_sans / max(total_arrive, 1) * 100
    heures_tri   = sorted(heures_sans.items(), key=lambda x: x[1], reverse=True)
    top3         = ", ".join(f"{h}h ({n} tubes)" for h, n in heures_tri[:3])

    # Chercher un pic de pending_max en début de journée (6h-10h)
    heure_debut_sim = 7.0
    pics_matin = []
    for t, v in zip(times, pending):
        if v is None:
            continue
        h_abs = (heure_debut_sim + t / 60.0) % 24.0
        if 6.0 <= h_abs <= 10.0:
            pics_matin.append(v)

    corps = (
        f"• {total_sans} tubes arrivent pendant des créneaux sans technicien "
        f"({pct:.0f}% du total)\n"
        f"• Créneaux les plus chargés sans couverture : {top3}\n"
        f"• Ces tubes s'accumulent en file d'entrée jusqu'à l'arrivée du premier tech"
    )
    action = (
        "→ Ces tubes expliquent directement les pics d'âge max observés\n"
        "  en début de matinée (le premier tech récupère un stock accumulé).\n"
        "→ Pour réduire cet effet : ajouter un tech de nuit, ou décaler\n"
        "  l'heure de début de la plage d'arrivée des tubes."
    )

    if pics_matin:
        pic_max = max(pics_matin)
        corps += f"\n• Pic d'âge max observé entre 6h et 10h : {_fmt_duree(pic_max)}"

    niveau = "warn" if pct > 15 else "info"
    insights.append(Insight(
        niveau,
        f"{total_sans} tubes arrivent sans technicien disponible ({pct:.0f}% du flux)",
        corps,
        action,
    ))
    return insights
