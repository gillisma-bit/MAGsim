"""Modèle d'état d'un technicien — logique pure, sans dépendance Tkinter."""

import math


class TechnicianState:
    """État individuel d'un technicien (position, sprite canvas, tubes portés)."""
    COLORS = ["#f1c40f", "#e67e22", "#9b59b6", "#1abc9c"]

    # Multiplicateur d'erreur selon l'expérience (1 = novice → 5 = expert)
    _FACTEUR_EXP = {1: 2.0, 2: 1.5, 3: 1.0, 4: 0.70, 5: 0.40}

    # Seuils de mécontentement → état de bien-être (emoji, couleur bordure, label)
    _SEUILS_BIENETRE = [
        (0.20, "😊", "#2ecc71",  "Satisfait"),   # vert
        (0.40, "😐", "#f1c40f",  "Neutre"),       # jaune
        (0.60, "😟", "#e67e22",  "Stressé"),      # orange
        (0.80, "😠", "#e74c3c",  "Épuisé"),       # rouge
        (1.01, "🤢", "#8e44ad",  "Burn-out"),     # violet
    ]

    def __init__(self, x, y, canvas_id=None, index=0):
        self.x = x
        self.y = y
        self.canvas_id = canvas_id
        self.label_bienetre_id = None   # id du texte emoji sur le canvas
        self.carried_tubes = []
        self.mouvement_interrompu = False
        self.color = self.COLORS[index % len(self.COLORS)]
        self.pct_erreur = 0.0           # taux effectif (recalculé à chaque livraison)
        self.pct_erreur_base = 0.0      # taux de base configuré (avant modification)
        # ── Caractéristiques personnelles ─────────────────────────────────────
        self.nom = ""                   # prénom/identifiant du technicien
        self.experience = 3             # 1 (novice) – 5 (expert)
        self.age = 35                   # âge en années
        self.seuil_charge_fatigue = 0.70  # ratio (0‑1) au-delà duquel la fatigue monte
        self.taux_montee_fatigue = 0.01   # incrément de fatigue par tube livré en surcharge
        self.capacite_max_tubes = 10    # nb max de tubes portables simultanément
        # ── État dynamique ────────────────────────────────────────────────────
        self.fatigue_courante = 0.0     # [0.0 – 1.0] : 0 = reposé, 1 = épuisé
        self.tubes_livres_session = 0   # compteur de tubes livrés cette session
        self.distance_parcourue_px = 0.0        # distance cumulative (pixels, session)
        self._distance_debut_jour_px = 0.0      # snapshot au début du jour courant (calcul journalier)
        # ── Bien-être / mécontentement ────────────────────────────────────────
        self.mecontentement = 0.0       # [0.0 – 1.0] état cumulatif
        self.jours_consecutifs_surcharge = 0    # nombre de jours consécutifs en surcharge
        self._tubes_livres_debut_jour = 0       # snapshot tubes livrés au début du jour
        self.en_arret_maladie = False           # le tech est en arrêt maladie
        self.historique_bienetre = []           # [(jour, mecontentement), ...] pour les stats

    # ------------------------------------------------------------------
    def calculer_pct_erreur_effectif(self, heure_simpy=0.0, heure_debut=7.0):
        """Taux d'erreur effectif = base × f_expérience × f_âge × f_fatigue × f_heure.

        - Expérience : novice fait 5× plus d'erreurs qu'un expert
        - Âge : junior (<28 ans) légèrement plus d'erreurs ; senior (>50) moins d'erreurs
        - Fatigue accumulée : erreurs × 2 au maximum (fatigue=1.0)
        - Heure : fin de journée augmente légèrement le taux
        """
        f_exp = self._FACTEUR_EXP.get(max(1, min(5, self.experience)), 1.0)

        # Âge → erreurs
        a = self.age
        if a <= 28:
            f_age = 1.35
        elif a <= 40:
            f_age = 1.35 - (a - 28) / 12.0 * 0.35
        elif a <= 55:
            f_age = 1.0 - (a - 40) / 15.0 * 0.20
        else:
            f_age = max(0.60, 0.80 - (a - 55) / 10.0 * 0.20)

        # Fatigue accumulée → erreurs ×[1.0 ; 2.0]
        f_fatigue = 1.0 + self.fatigue_courante

        # Heure de la journée → erreurs
        h = (heure_debut + heure_simpy / 60.0) % 24.0
        if h < 7 or h >= 20:
            f_heure = 1.20
        elif h < 11:
            f_heure = 1.00
        elif h < 14:
            f_heure = 1.05
        elif h < 17:
            f_heure = 1.15
        else:
            f_heure = 1.0 + min(0.40, (h - 17) / 3.0 * 0.40)

        return min(1.0, self.pct_erreur_base * f_exp * f_age * f_fatigue * f_heure)

    # ------------------------------------------------------------------
    def calculer_vitesse(self, heure_simpy=0.0, heure_debut=7.0):
        """Vitesse de déplacement (px/tick) modulée par l'âge, l'heure et la fatigue.

        - Jeune (<28) : +10 % ; Senior (>60) : −20 % à −30 %
        - Matin : plein potentiel ; fin de journée : −15 % à −25 %
        - Fatigue ×0.70 au maximum
        """
        a = self.age
        if a <= 28:
            f_age = 1.10
        elif a <= 45:
            f_age = 1.10 - (a - 28) / 17.0 * 0.15
        elif a <= 60:
            f_age = 0.95 - (a - 45) / 15.0 * 0.15
        else:
            f_age = max(0.70, 0.80 - (a - 60) / 10.0 * 0.10)

        h = (heure_debut + heure_simpy / 60.0) % 24.0
        if h < 7 or h >= 20:
            f_heure = 0.82
        elif h < 10:
            f_heure = 1.00
        elif h < 13:
            f_heure = 0.97
        elif h < 16:
            f_heure = 0.92
        else:
            f_heure = max(0.75, 0.92 - (h - 16) / 4.0 * 0.17)

        f_fatigue = max(0.70, 1.0 - self.fatigue_courante * 0.30)

        return 8.0 * f_age * f_heure * f_fatigue

    # ------------------------------------------------------------------
    def etat_bien_etre(self):
        """Retourne (emoji, couleur_hex, label) selon le mécontentement courant."""
        for seuil, emoji, couleur, label in self._SEUILS_BIENETRE:
            if self.mecontentement < seuil:
                return emoji, couleur, label
        return "🤢", "#8e44ad", "Burn-out"

    # ------------------------------------------------------------------
    def mettre_a_jour_mecontentement(self, tubes_livres_jour, capacite_journaliere_normale):
        """Met à jour le mécontentement en fin de journée.

        Logique :
        - charge_effective = tubes_livres_jour / capacite_journaliere_normale
        - Si charge > seuil_charge_fatigue → montée du mécontentement proportionnelle
          à l'excès de charge × facteur d'accumulation (jours consécutifs amplificateur)
        - Sinon → récupération partielle
        - La fatigue physique contribue également au mécontentement

        Le risque d'arrêt maladie augmente exponentiellement avec le mécontentement
        et les jours consécutifs de surcharge.
        """
        if capacite_journaliere_normale <= 0:
            return
        charge = tubes_livres_jour / capacite_journaliere_normale

        if charge > self.seuil_charge_fatigue:
            exces = charge - self.seuil_charge_fatigue
            # Amplificateur : plus les jours de surcharge s'accumulent, plus la montée est rapide
            amplificateur = 1.0 + 0.15 * self.jours_consecutifs_surcharge
            delta = exces * 0.12 * amplificateur
            # La fatigue physique ajoute sa propre contribution
            delta += self.fatigue_courante * 0.05
            self.mecontentement = min(1.0, self.mecontentement + delta)
            self.jours_consecutifs_surcharge += 1
        else:
            # Récupération : plus lente selon l'état actuel
            recuperation = 0.04 * (1.0 - self.mecontentement * 0.5)
            self.mecontentement = max(0.0, self.mecontentement - recuperation)
            self.jours_consecutifs_surcharge = 0

        self.historique_bienetre.append((self.jours_consecutifs_surcharge, round(self.mecontentement, 3)))

    # ------------------------------------------------------------------
    def calculer_risque_arret_maladie(self):
        """Probabilité journalière d'arrêt maladie.

        Modèle sigmoïde : risque très faible en dessous de 0.5 de mécontentement,
        puis monte rapidement. Amplifié par les jours consécutifs en surcharge.

        Retourne un float [0–1] : probabilité sur 1 jour simulé.
        """
        if self.mecontentement < 0.40:
            return 0.0
        # Base sigmoïde centrée en 0.70
        x = (self.mecontentement - 0.70) * 8.0
        base = 1.0 / (1.0 + math.exp(-x))
        # Amplification durée de surcharge (multiplie jusqu'à ×3 après 7 jours)
        amp = 1.0 + min(2.0, self.jours_consecutifs_surcharge * 0.15)
        return min(1.0, base * amp * 0.35)
