"""Mixin _TabLiveTechnician pour TabLive — extrait de ui/tab_live.py.

Ces méthodes utilisent `self.xxx` défini dans TabLive.__init__.
"""
import simpy
from core.technician import TechnicianState
from core.sim.priorite import (
    _score_priorite, _inserer_par_priorite,
    _trier_queue_par_priorite, _inserer_par_anciennete,
)


class _TabLiveTechnician:
    """Mixin : ne pas instancier directement."""

    def _tech_est_en_service(self, tech):
        """Retourne True si le technicien est dans sa plage horaire configurée.

        Règles :
          - Aucun horaire défini → toujours en service.
          - actif = false → jamais en service.
          - Quart de nuit (h_debut > h_fin, ex: 16→8) :
              * Portion soirée (heure >= h_debut) → vérifier que le jour CALENDAIRE actuel est actif.
              * Portion matin  (heure <  h_fin)   → vérifier que le jour CALENDAIRE précédent est actif.
                (Le quart a démarré la veille ; on ne doit pas être en service si ce n'était pas
                 un jour de travail, même si aujourd'hui l'est.)
          - Le jour calendaire utilise la frontière MINUIT (≠ frontière SimPy qui est à heure_debut_sim).
        """
        horaires = self.config_manager.data.get("horaires", {})
        h_tech = horaires.get(tech.nom, {})

        if not h_tech:
            return True  # pas de contrainte → toujours disponible

        if not h_tech.get("actif", True):
            return False

        personnel = self.config_manager.data.get("personnel", {})
        jour_debut_sim = int(personnel.get("jour_debut_simulation", 0))  # 0=Lundi

        t = self.env.now
        h_debut_sim = self.heure_debut_sim  # heure réelle à t=0 (ex: 7.0)

        # ── Jour calendaire (frontière minuit) ────────────────────────────
        # (t + h_debut_sim*60) convertit le temps SimPy en minutes depuis
        # le minuit précédant t=0, puis on divise par 1440 pour avoir les jours.
        calendar_day  = int((t + h_debut_sim * 60) / 1440)
        jour_semaine  = (jour_debut_sim + calendar_day) % 7   # 0=L … 6=D

        jours_actifs = h_tech.get("jours", list(range(5)))
        h_debut = float(h_tech.get("heure_debut", 7))
        h_fin   = float(h_tech.get("heure_fin",   15))

        # Heure réelle actuelle (décimale, 0–24)
        heure_actuelle = (h_debut_sim + (t % 1440) / 60.0) % 24.0

        if h_debut > h_fin:
            # ── Quart traversant minuit (ex: 16h→8h) ──────────────────────
            if heure_actuelle >= h_debut:
                # Portion soirée : le quart démarre CE jour calendaire
                return jour_semaine in jours_actifs
            elif heure_actuelle < h_fin:
                # Portion matin : le quart a démarré le jour calendaire PRÉCÉDENT
                jour_precedent = (jour_semaine - 1) % 7
                return jour_precedent in jours_actifs
            else:
                # Entre h_fin et h_debut → hors service
                return False
        else:
            # ── Quart normal (même jour) ───────────────────────────────────
            if jour_semaine not in jours_actifs:
                return False
            return h_debut <= heure_actuelle < h_fin

    def _tech_est_en_pause_dejeuner(self, tech):
        """Retourne True si le tech est dans sa fenêtre de pause déjeuner.

        En mode rotation automatique, les pauses sont décalées selon l'indice du tech
        (ex : Tech1 12h00–12h30, Tech2 12h30–13h00, Tech3 13h00–13h30).
        En mode manuel, chaque tech utilise ses propres pause_debut / pause_fin.
        """
        if self.env is None:
            return False
        personnel = self.config_manager.data.get("personnel", {})
        if personnel.get("pause_rotation_auto", False):
            p_debut = float(personnel.get("pause_creneau_debut", 12.0))
            duree_h = float(personnel.get("pause_duree_minutes", 30)) / 60.0
            idx     = self._get_tech_rotation_index(tech)
            p_debut = p_debut + idx * duree_h
            p_fin   = p_debut + duree_h
        else:
            horaires = self.config_manager.data.get("horaires", {})
            h_tech   = horaires.get(tech.nom, {})
            if "pause_debut" not in h_tech or "pause_fin" not in h_tech:
                return False
            p_debut = float(h_tech.get("pause_debut", 12.0))
            p_fin   = float(h_tech.get("pause_fin",   13.0))

        heure_actuelle = (self.heure_debut_sim + (self.env.now % 1440) / 60.0) % 24.0
        return p_debut <= heure_actuelle < p_fin

    def _tech_est_en_garde(self, tech):
        """Retourne True si ce tech est le tech de garde pour le jour courant.

        Les gardes ne s'appliquent qu'en Samedi (5), Dimanche (6) et jours
        fériés simulés. En semaine, les 3 quarts couvrent la journée entière.

        Valeurs possibles dans personnel :
          - "Personne"       → aucune garde ce jour
          - "Rotation auto"  → tourne parmi tous les techs actifs, semaine/semaine
          - "<nom_tech>"     → toujours ce tech
        """
        if tech.en_arret_maladie:
            return False
        # La garde ne vaut que hors de la plage horaire normale
        if self._tech_est_en_service(tech):
            return False

        personnel = self.config_manager.data.get("personnel", {})
        jour = self._get_jour_semaine()

        if jour == 5:        # Samedi
            assigne = personnel.get("garde_samedi",   "Personne")
        elif jour == 6:      # Dimanche
            assigne = personnel.get("garde_dimanche", "Personne")
        else:
            return False     # Lundi–Vendredi : pas de garde

        if not assigne or assigne == "Personne":
            return False
        if assigne == "Rotation auto":
            return self._get_tech_garde_auto() == tech.nom
        return assigne == tech.nom

    def _get_jour_semaine(self):
        """Retourne le jour de la semaine courant (0=Lundi … 6=Dimanche)."""
        if self.env is None:
            return 0
        personnel     = self.config_manager.data.get("personnel", {})
        jour_debut    = int(personnel.get("jour_debut_simulation", 0))
        calendar_day  = int((self.env.now + self.heure_debut_sim * 60) / 1440)
        return (jour_debut + calendar_day) % 7

    def _get_tech_garde_auto(self):
        """Tech de garde en rotation automatique pour la semaine SimPy courante.

        Seuls les techs dont pool_garde=True sont inclus dans la rotation.
        Si le pool est vide, retourne None (pas de garde).
        """
        if self.env is None:
            return None
        week_num = int(self.env.now / (7 * 1440))
        horaires = self.config_manager.data.get("horaires", {})
        pool = sorted([
            t.nom for t in self.technicians
            if horaires.get(t.nom, {}).get("actif", True)
            and horaires.get(t.nom, {}).get("pool_garde", False)
            and not t.en_arret_maladie
        ])
        if not pool:
            return None
        return pool[week_num % len(pool)]

    def _get_tech_rotation_index(self, tech):
        """Retourne la position du tech dans la rotation de pauses (ordre alpha des actifs)."""
        horaires = self.config_manager.data.get("horaires", {})
        actifs   = sorted([
            t.nom for t in self.technicians
            if horaires.get(t.nom, {}).get("actif", True)
        ])
        return actifs.index(tech.nom) if tech.nom in actifs else 0

    def technician_process(self, tech):
        """Processus d'un technicien : collecte tous les tubes disponibles, vérifie la capacité des files, dépose et récupère."""
        machines = self.config_manager.get_machines()
        entrees = [m for m in machines.values() if m["type"] == "ENTREE"]
        sorties = [m for m in machines.values() if m["type"] == "SORTIE"]

        while self.running:

            # --- Vérification disponibilité : horaire + pause déjeuner + arrêt maladie ---
            en_service_horaire = (not tech.en_arret_maladie) and self._tech_est_en_service(tech)
            en_pause_dej       = en_service_horaire and self._tech_est_en_pause_dejeuner(tech)
            # Garde active : le tech a été rappelé et est sur place
            en_service = (en_service_horaire and not en_pause_dej) or getattr(tech, '_garde_actif', False)
            tech.en_service = en_service
            tech.en_pause_dejeuner = en_pause_dej

            # ── Prise de service : vérification des tubes vieillissants ──────────
            # Si le tech vient de passer de hors-service à en-service (début de quart),
            # il fait un tour rapide de l'état des files et escalade les tubes proches
            # de péremption avant de commencer sa tournée normale.
            if en_service and not getattr(tech, '_etait_en_service', False):
                self._escalader_tubes_vieillissants(self.env.now)
            tech._etait_en_service = en_service

            # Fin d'intervention de garde : vérifier si le forfait minimum est écoulé
            if getattr(tech, '_garde_actif', False) and not en_service_horaire:
                personnel_g = self.config_manager.data.get("personnel", {})
                forfait_min = float(personnel_g.get("garde_forfait_heures", 3)) * 60
                # Plafond absolu = 2× le forfait pour éviter qu'une garde dure tout le week-end
                # quand des tubes restent urgents (ex: escalade automatique la nuit).
                garde_max = forfait_min * 2
                temps_sur_place = self.env.now - getattr(tech, '_garde_arrivee', self.env.now)
                has_urgent = any(t.get("urgent") for t in self.entry_queue)
                if temps_sur_place >= forfait_min and (not has_urgent or temps_sur_place >= garde_max):
                    tech._garde_actif = False
                    en_service = False
                    tech.en_service = False

            if not en_service:
                # ── Vérifier si une garde peut être déclenchée ──────────────
                if (not tech.en_arret_maladie
                        and self._tech_est_en_garde(tech)
                        and not getattr(tech, '_garde_actif', False)):
                    urgent_present = any(t.get("urgent") for t in self.entry_queue)
                    if urgent_present:
                        personnel_g = self.config_manager.data.get("personnel", {})
                        trajet = float(personnel_g.get("garde_trajet_minutes", 20))
                        yield self.env.timeout(trajet)   # déplacement vers le labo
                        tech._garde_actif   = True
                        tech._garde_arrivee = self.env.now
                        en_service = True
                        tech.en_service = True
                        # Ne pas faire continue : le tech traite le tube urgent
                    else:
                        yield self.env.timeout(5)        # re-vérifier souvent
                        continue
                elif en_pause_dej:
                    # ── Pause déjeuner : aller vers zone de repos si définie, sinon bureau ──
                    _zone_repos = next(
                        (m for m in self.config_manager.get_machines().values()
                         if m.get("type") == "REPOS"),
                        None,
                    )
                    if _zone_repos:
                        dest_x = _zone_repos["coords"]["x"]
                        dest_y = _zone_repos["coords"]["y"]
                    else:
                        dest_x = getattr(tech, 'office_x', tech.x)
                        dest_y = getattr(tech, 'office_y', tech.y)
                    if not self.headless and (abs(tech.x - dest_x) > 5 or abs(tech.y - dest_y) > 5):
                        libre_x, libre_y = self.trouver_case_libre_proche(
                            dest_x, dest_y, from_x=tech.x, from_y=tech.y)
                        yield self.env.process(self.deplacer_vers(tech, libre_x, libre_y))
                    if not self.headless:
                        self._update_tech_sprite_bienetre(tech)
                    yield self.env.timeout(5)            # re-vérifie toutes les 5 min sim
                    continue
                else:
                    # ── Hors service normal : retour au bureau ────────────────
                    office_x = getattr(tech, 'office_x', tech.x)
                    office_y = getattr(tech, 'office_y', tech.y)
                    if not self.headless and (abs(tech.x - office_x) > 5 or abs(tech.y - office_y) > 5):
                        libre_x, libre_y = self.trouver_case_libre_proche(
                            office_x, office_y, from_x=tech.x, from_y=tech.y)
                        yield self.env.process(self.deplacer_vers(tech, libre_x, libre_y))
                    if not self.headless:
                        self._update_tech_sprite_bienetre(tech)
                    yield self.env.timeout(15)           # re-vérifie toutes les 15 min sim
                    continue

            # --- Priorité 1 : tubes ayant fini un traitement, à récupérer ---
            # Correction bug multi-machine : le tech se déplace vers UNE SEULE machine
            # par itération — la plus prioritaire.  Les tubes des autres machines
            # restent visibles dans output_queues et seront ramassés au prochain tour.
            # Avant : tous les tubes de toutes les machines étaient retirés d'un coup
            # même si le tech n'était physiquement allé qu'à la première machine.
            deja_portes = {id(t) for other in self.technicians if other is not tech
                           for t in other.carried_tubes}

            # Trouver la machine la plus prioritaire (tube avec le score EDD le plus élevé)
            mu, mv, ma = self.coordinateur.poids_courants
            meilleure_machine = None
            meilleur_score = -1.0
            for nom_m in list(self.output_queues.keys()):
                disponibles = [t for t in self.output_queues[nom_m]
                               if id(t) not in deja_portes]
                if not disponibles:
                    continue
                score_m = max(
                    _score_priorite(t, self.env.now, mu, mv, ma) for t in disponibles)
                if score_m > meilleur_score:
                    meilleur_score = score_m
                    meilleure_machine = nom_m

            if meilleure_machine is not None:
                tubes_finis = [t for t in self.output_queues[meilleure_machine]
                               if id(t) not in deja_portes]
                # Trier par priorité décroissante avant le trajet
                tubes_finis.sort(
                    key=lambda t: -_score_priorite(t, self.env.now, mu, mv, ma))

                # Claim : assigner les tubes AU TECH maintenant, les laisser dans
                # output_queues pour que les boîtes vertes restent visibles pendant le trajet
                for t in tubes_finis:
                    t["_porteur_machine"] = meilleure_machine  # débogage : machine source visible
                tech.carried_tubes = tubes_finis
                self._refresh_label_tubes(tech)

                # Se rendre à la machine source
                m_src = machines.get(meilleure_machine)
                if not self.headless:
                    # Essayer d'abord via les coordonnées canvas du premier tube
                    premier = tubes_finis[0]
                    dest_trouvee = False
                    if premier.get("id") and self.canvas.winfo_exists():
                        coords = self.canvas.coords(premier["id"])
                        if coords:
                            tx = (coords[0] + coords[2]) / 2
                            ty = (coords[1] + coords[3]) / 2
                            libre_x, libre_y = self.trouver_case_libre_proche(
                                tx, ty, from_x=tech.x, from_y=tech.y)
                            yield self.env.process(
                                self.deplacer_vers(tech, libre_x, libre_y))
                            dest_trouvee = True
                    if not dest_trouvee and m_src:
                        libre_x, libre_y = self.trouver_case_libre_proche(
                            m_src["coords"]["x"], m_src["coords"]["y"],
                            from_x=tech.x, from_y=tech.y)
                        yield self.env.process(
                            self.deplacer_vers(tech, libre_x, libre_y))
                else:
                    # Headless : déplacement via coordonnées config
                    if m_src:
                        libre_x, libre_y = self.trouver_case_libre_proche(
                            m_src["coords"]["x"], m_src["coords"]["y"],
                            from_x=tech.x, from_y=tech.y)
                        yield self.env.process(
                            self.deplacer_vers(tech, libre_x, libre_y))

                # Tech arrivé à la machine : retirer UNIQUEMENT les tubes de cette machine
                tubes_finis_ids = {id(t) for t in tubes_finis}
                self.output_queues[meilleure_machine] = [
                    t for t in self.output_queues[meilleure_machine]
                    if id(t) not in tubes_finis_ids]

                if not self.headless:
                    for tube in tech.carried_tubes:
                        if self.canvas.winfo_exists() and tube.get("id"):
                            self.canvas.coords(tube["id"],
                                              tech.x-6, tech.y-6,
                                              tech.x+6, tech.y+6)

                yield self.env.process(
                    self._livrer_tubes(tech, tech.carried_tubes, machines, sorties))
                tech.carried_tubes = []
                continue

            # --- Priorité 2 : nouveau(x) tube(s) en attente à l'entrée ---
            if not self.entry_queue or not entrees:
                # Headless : tick plus large → 4× moins d'events SimPy sans affecter le résultat
                idle_tick = 2.0 if self.headless else 0.5
                yield self.env.timeout(idle_tick)
                # Récupération légère pendant les périodes d'inactivité
                tech.fatigue_courante = max(0.0, tech.fatigue_courante - 0.001)
                self._update_tech_sprite_fatigue(tech)
                continue

            # Aller à l'entrée
            ex, ey = entrees[0]["coords"]["x"], entrees[0]["coords"]["y"]
            yield self.env.process(self.deplacer_vers(tech, ex, ey))

            if not self.entry_queue:
                continue

            # Calculer combien de places sont disponibles dans les machines destination
            # Sommer TOUTES les machines éligibles pour chaque étape (pas juste la première retenue)
            machines = self.config_manager.get_machines()  # rafraîchir au cas où
            places_par_machine = {}
            for tube in self.entry_queue:
                etape = tube["workflow"][0] if tube["workflow"] else None
                if not etape:
                    continue
                for nom, m in machines.items():
                    if etape in m.get("protocoles", {}) and nom not in places_par_machine:
                        fm = m.get("file_max", m.get("capacite", 4))
                        deja = len(self.machine_queues.get(nom, []))
                        # Soustraire les slots déjà réservés par d'autres techs en transit
                        reserves = self.machine_slots_reserved.get(nom, 0)
                        places_par_machine[nom] = max(0, fm - deja - reserves)

            # Les tubes sans workflow vont directement en sortie — toujours prenables
            nb_vers_sortie = sum(1 for t in self.entry_queue if not t.get("workflow"))
            places_totales = sum(places_par_machine.values()) + nb_vers_sortie
            nb_a_prendre = min(len(self.entry_queue), places_totales)
            if nb_a_prendre == 0:
                # Toutes les files sont pleines, attendre
                yield self.env.timeout(2)
                # Récupération plus marquée lors des longues attentes
                tech.fatigue_courante = max(0.0, tech.fatigue_courante - 0.005)
                self._update_tech_sprite_fatigue(tech)
                continue

            # Trier entry_queue par priorité avant de prendre les tubes
            # → les poids du coordinateur (boostés par l'IA en zone CRITIQUE) prennent effet ici
            mu, mv, ma = self.coordinateur.poids_courants
            _trier_queue_par_priorite(self.entry_queue, self.env.now, mu, mv, ma)

            tech.carried_tubes = self.entry_queue[:nb_a_prendre]
            del self.entry_queue[:nb_a_prendre]

            # ── Réserver les slots machine pour les tubes pris ────────────────
            # Pour chaque tube, déterminer la destination probable et réserver
            # une place, de sorte qu'un autre tech plus rapide ne puisse pas la prendre.
            _vq_reservation = {}   # compteur virtuel local pour cette passe de réservation
            for tube in tech.carried_tubes:
                etape = tube["workflow"][0] if tube.get("workflow") else None
                if not etape:
                    continue
                m_obj, m_nom, _ = self._trouver_prochaine_machine(
                    tube, machines, _vq_reservation)
                if m_nom:
                    self.machine_slots_reserved[m_nom] = (
                        self.machine_slots_reserved.get(m_nom, 0) + 1)
                    _vq_reservation[m_nom] = _vq_reservation.get(m_nom, 0) + 1
                    tube["_reserved_machine"] = m_nom   # mémoriser pour libérer au dépôt

            if not self.headless and self.canvas.winfo_exists():
                for tube in tech.carried_tubes:
                    if tube.get("id"):
                        self.canvas.coords(tube["id"],
                                          tech.x-6, tech.y-6,
                                          tech.x+6, tech.y+6)

            self._refresh_label_tubes(tech)
            yield self.env.process(self._livrer_tubes(tech, tech.carried_tubes, machines, sorties))
            tech.carried_tubes = []
            self._refresh_label_tubes(tech)
