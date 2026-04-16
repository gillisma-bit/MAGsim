"""Modèle d'état d'un technicien — logique pure, sans dépendance Tkinter."""


class TechnicianState:
    """État individuel d'un technicien (position, sprite canvas, tubes portés)."""
    COLORS = ["#f1c40f", "#e67e22", "#9b59b6", "#1abc9c"]

    # Multiplicateur d'erreur selon l'expérience (1 = novice → 5 = expert)
    _FACTEUR_EXP = {1: 2.0, 2: 1.5, 3: 1.0, 4: 0.70, 5: 0.40}

    def __init__(self, x, y, canvas_id=None, index=0):
        self.x = x
        self.y = y
        self.canvas_id = canvas_id
        self.carried_tubes = []
        self.mouvement_interrompu = False
        self.color = self.COLORS[index % len(self.COLORS)]
        self.pct_erreur = 0.0           # taux effectif (recalculé à chaque livraison)
        self.pct_erreur_base = 0.0      # taux de base configuré (avant modification)
        # ── Caractéristiques personnelles ─────────────────────────────────────
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
