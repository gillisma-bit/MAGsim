"""Mixin _TabLiveLivraison pour TabLive — extrait de ui/tab_live.py.

Ces méthodes utilisent `self.xxx` défini dans TabLive.__init__.
"""
from collections import deque
import simpy
import random
import ui.theme as theme
from core.sim.priorite import (
    _score_priorite, _inserer_par_priorite,
    _trier_queue_par_priorite, _inserer_par_anciennete,
)


class _TabLiveLivraison:
    """Mixin : ne pas instancier directement."""

    def _livrer_tubes(self, tech, tubes, machines, sorties):
        """Distribue une liste de tubes vers leurs prochaines destinations en respectant les file_max."""
        # Grouper les tubes par prochaine destination
        while tubes:
            # Vérification horaire : si le tech vient de passer hors service,
            # remettre les tubes non encore déposés en file d'entrée et retourner au bureau.
            if (tech.en_arret_maladie
                    or (not self._tech_est_en_service(tech) and not getattr(tech, '_garde_actif', False))
                    or (self._tech_est_en_pause_dejeuner(tech) and not getattr(tech, '_garde_actif', False))):
                tech.en_service = False
                # Libérer les slots réservés AVANT de remettre en file
                self._liberer_reservations(tubes)
                # Remettre les tubes non déposés dans la file d'entrée
                # en respectant l'ordre chronologique (tube vieux → avant les récents)
                for tube in tubes:
                    if not tube.get("dropped_at_machine"):
                        mu, mv, ma = self.coordinateur.poids_courants
                        _inserer_par_anciennete(self.entry_queue, tube, self.env.now, mu, mv, ma)
                tech.carried_tubes = []
                self._refresh_label_tubes(tech)
                # Retourner au bureau
                if not self.headless:
                    office_x = getattr(tech, 'office_x', tech.x)
                    office_y = getattr(tech, 'office_y', tech.y)
                    if abs(tech.x - office_x) > 5 or abs(tech.y - office_y) > 5:
                        libre_x, libre_y = self.trouver_case_libre_proche(
                            office_x, office_y, from_x=tech.x, from_y=tech.y)
                        yield self.env.process(self.deplacer_vers(tech, libre_x, libre_y))
                    self._update_tech_sprite_bienetre(tech)
                return

            # Compteur virtuel : tubes déjà assignés à chaque machine dans CE batch
            # (permet à la stratégie fill-first de tenir compte des tubes déjà attribués
            #  aux machines précédentes avant tout déplacement physique)
            virtual_queues = {}

            groupes = {}    # nom_machine -> [(tube, machine, etape)]
            vers_sortie = []
            tubes_reportes = []  # tubes qu'on ne peut pas déposer maintenant (file pleine)

            for tube in tubes:
                machine, nom_machine, etape = self._trouver_prochaine_machine(
                    tube, machines, virtual_queues)
                if machine:
                    groupes.setdefault(nom_machine, []).append((tube, machine, etape))
                    virtual_queues[nom_machine] = virtual_queues.get(nom_machine, 0) + 1
                else:
                    # Workflow vide → sortie ; machines pleines → reporter
                    if tube.get("workflow"):
                        tubes_reportes.append(tube)
                    else:
                        vers_sortie.append(tube)

            # Traiter les dépôts machine par machine
            for nom_machine, paires in groupes.items():
                machine = paires[0][1]
                tubes_groupe = [(p[0], p[2]) for p in paires]  # (tube, etape)

                file_max = machine.get("file_max", machine.get("capacite", 4))
                deja_en_queue = len(self.machine_queues.get(nom_machine, []))
                # Compter les réservations des AUTRES techs (pas celles de ce tech,
                # dont les tubes sont déjà dans tubes_groupe et comptés par virtual_queues)
                nb_reserves_autres = max(0,
                    self.machine_slots_reserved.get(nom_machine, 0)
                    - sum(1 for p in tubes_groupe
                          if p[0].get("_reserved_machine") == nom_machine)
                )
                places_dispo = max(0, file_max - deja_en_queue - nb_reserves_autres)

                # On ne peut déposer que ce qu'il y a de place
                paires_a_deposer = tubes_groupe[:places_dispo]
                paires_reportees = tubes_groupe[places_dispo:]
                tubes_reportes.extend([p[0] for p in paires_reportees])  # tubes reportés : workflow intact

                if paires_a_deposer:
                    tubes_seuls = [p[0] for p in paires_a_deposer]
                    mx, my = machine["coords"]["x"], machine["coords"]["y"]
                    libre_x, libre_y = self.trouver_case_libre_proche(mx, my, from_x=tech.x, from_y=tech.y)
                    # Les tubes à déposer restent dans carried_tubes pendant le trajet
                    # pour suivre le tech visuellement — retrait APRÈS l'arrivée
                    yield self.env.process(self.deplacer_vers(tech, libre_x, libre_y))
                    tech.carried_tubes = [t for t in tech.carried_tubes if t not in tubes_seuls]
                    self._refresh_label_tubes(tech)

                    if nom_machine not in self.machine_queues:
                        self.machine_queues[nom_machine] = []

                    for tube, etape_tube in paires_a_deposer:
                        # Libérer la réservation : le tube est physiquement déposé (ou perdu)
                        self._liberer_reservations([tube])
                        # Erreur technicien : tube accidentellement contaminé/perdu
                        # Le taux effectif tient compte de l'expérience, de l'âge, de la fatigue et de l'heure
                        pct_eff = tech.calculer_pct_erreur_effectif(self.env.now, self.heure_debut_sim)
                        if pct_eff > 0.0 and random.random() < pct_eff:
                            self.tubes_rejetes += 1
                            if not self.headless and self.canvas.winfo_exists() and tube.get("id"):
                                self.canvas.itemconfig(tube["id"], fill="#e74c3c", outline="#c0392b", width=2)
                                tid = tube["id"]
                                self.canvas.after(500, lambda t=tid: self.canvas.delete(t) if self.canvas.winfo_exists() else None)
                            continue  # tube perdu, non déposé en machine
                        # ── Rejet prédictif : le tube va-t-il expirer avant la fin de son workflow ? ──
                        # On calcule ici (avant de consommer l'étape) car etape_tube est encore
                        # workflow[0], ce qui permet d'inclure la machine courante dans le calcul.
                        _dv = tube.get("duree_validite", 0)
                        if _dv > 0:
                            # Utilise la deadline absolue si disponible (plus précis que arrivee)
                            _dl = tube.get("deadline", 0)
                            _validite_restante = (_dl - self.env.now) if _dl > 0 else (
                                _dv - (self.env.now - tube.get("arrivee", self.env.now)))
                            # étapes restantes APRÈS la machine courante
                            _workflow_apres = tube.get("workflow", [])[1:]
                            _duree_sim = self._estimer_duree_workflow(
                                [etape_tube] + list(_workflow_apres), machines)
                            if _duree_sim > _validite_restante:
                                tube["perime"] = True
                                self.tubes_perimes += 1
                                self.tubes_degrades += 1
                                if not self.headless and self.canvas.winfo_exists() and tube.get("id"):
                                    self.canvas.itemconfig(tube["id"],
                                                          fill="#bdc3c7", outline="#e74c3c", width=2)
                                    _tid = tube["id"]
                                    self.canvas.after(
                                        800,
                                        lambda _t=_tid: self.canvas.delete(_t)
                                        if self.canvas.winfo_exists() else None)
                                continue  # tube condamné, non déposé en machine
                        # Consommer l'étape MAINTENANT que le dépôt est confirmé
                        if tube["workflow"] and tube["workflow"][0] == etape_tube:
                            tube["workflow"].pop(0)
                        if not self.headless and self.canvas.winfo_exists() and tube.get("id"):
                            self.canvas.coords(tube["id"], mx-6, my-6, mx+6, my+6)
                            self.canvas.itemconfig(tube["id"], outline="#e67e22", width=2)
                        self.machine_queues[nom_machine].append(tube)
                        tech.tubes_livres_session += 1

                    # Mise à jour fatigue selon la charge portée dans ce batch
                    charge = len(tubes_seuls) / max(1.0, tech.capacite_max_tubes)
                    if charge > tech.seuil_charge_fatigue:
                        tech.fatigue_courante = min(1.0, tech.fatigue_courante +
                                                    tech.taux_montee_fatigue * len(tubes_seuls))
                    else:
                        tech.fatigue_courante = max(0.0, tech.fatigue_courante -
                                                    tech.taux_montee_fatigue * 0.3)
                    self._update_tech_sprite_fatigue(tech)

                    capacite = machine.get("capacite", 4)
                    seuil = machine.get("seuil", 1)  # seuil minimum pour déclenchement urgent
                    file_max = machine.get("file_max", machine.get("capacite", 4))
                    queue = self.machine_queues[nom_machine]
                    has_urgent = any(t.get("urgent") for t in queue)
                    # Lancer si : batch complet OU urgence OU file pleine
                    should_trigger = (
                        len(queue) >= capacite
                        or (has_urgent and len(queue) >= seuil)
                        or len(queue) >= file_max
                    )
                    # GARDE : _machines_batch_actif est la source de vérité.
                    # blinking_machines est discardé AVANT le finally-block de
                    # traiter_batch_machine, créant une fenêtre où le tech peut
                    # spawner un deuxième batch concurrent → accumulation de
                    # processus SimPy et blocage stochastique.
                    if should_trigger and nom_machine not in self._machines_batch_actif:
                        self._machines_batch_actif.add(nom_machine)
                        self.env.process(self.traiter_batch_machine(nom_machine, machine))

                    # ── Travail manuel : UN SEUL tech à poste ─────────────────────────
                    # Activé par le flag JSON "tech_requis_poste": true sur la machine.
                    # Le tech qui déclenche l'analyse reste à poste pour toute sa durée ;
                    # un second tech qui dépose peut repartir librement.
                    if machine.get("tech_requis_poste", False):
                        if nom_machine not in self.paillasse_analyste:
                            # Ce tech prend le poste : il reste pour l'analyse
                            self.paillasse_analyste.add(nom_machine)
                            protocoles = machine.get("protocoles", {})
                            etape_eff = (paires_a_deposer[0][1]
                                         if paires_a_deposer
                                         else next(iter(protocoles), None))
                            temps_analyse = (protocoles.get(etape_eff, {}).get("temps", 60)
                                             if protocoles else 60)

                            # Limite : rester au poste au plus N batches complets.
                            # Évite qu'un tech reste bloqué indéfiniment quand les tubes
                            # arrivent en continu (seuil=1 → chaque tube déclenche un batch).
                            # Un autre tech (ou le même au prochain tour) prendra le relais.
                            _max_batches_poste = max(3, machine.get("capacite", 4))
                            _batches_vus = 0
                            _etait_blinking = nom_machine in self.blinking_machines

                            while (self.machine_queues.get(nom_machine)
                                   or nom_machine in self.blinking_machines):
                                yield self.env.timeout(temps_analyse / 10)
                                # Détecter la fin d'un batch (blinking s'éteint puis se rallume)
                                _blinking_now = nom_machine in self.blinking_machines
                                if _etait_blinking and not _blinking_now:
                                    _batches_vus += 1
                                _etait_blinking = _blinking_now
                                # Légère récupération de fatigue pendant l'attente passive
                                tech.fatigue_courante = max(0.0, tech.fatigue_courante - 0.0002)
                                if _batches_vus >= _max_batches_poste:
                                    break  # Relâcher le poste — un autre tech prendra le relais
                                if (tech.en_arret_maladie
                                        or (not self._tech_est_en_service(tech)
                                            and not getattr(tech, '_garde_actif', False))):
                                    break
                            self.paillasse_analyste.discard(nom_machine)

                            # Fatigue du travail actif (plus intense qu'un simple transport)
                            surcharge = max(0.0,
                                            len(paires_a_deposer) / max(1, tech.capacite_max_tubes)
                                            - tech.seuil_charge_fatigue)
                            tech.fatigue_courante = min(
                                1.0,
                                tech.fatigue_courante
                                + tech.taux_montee_fatigue * len(paires_a_deposer) * (1.0 + surcharge)
                            )
                            self._update_tech_sprite_fatigue(tech)

                            # Erreur analytique résiduelle en fin d'analyse
                            tubes_produits = self.output_queues.get(nom_machine, [])
                            if tubes_produits:
                                pct_eff_fin = tech.calculer_pct_erreur_effectif(
                                    self.env.now, self.heure_debut_sim)
                                for tube in list(tubes_produits):
                                    if pct_eff_fin > 0.0 and random.random() < pct_eff_fin * 0.4:
                                        tubes_produits.remove(tube)
                                        self.tubes_rejetes += 1
                                        if not self.headless and self.canvas.winfo_exists() and tube.get("id"):
                                            self.canvas.itemconfig(tube["id"],
                                                                   fill="#c0392b", outline="#922b21", width=2)
                                            tid = tube["id"]
                                            self.canvas.after(
                                                600,
                                                lambda t=tid: self.canvas.delete(t)
                                                if self.canvas.winfo_exists() else None
                                            )
                        # else : la Paillasse est déjà occupée — ce tech dépose et repart libre

            # Tubes vers la sortie
            if vers_sortie:
                if sorties:
                    sx, sy = sorties[0]["coords"]["x"], sorties[0]["coords"]["y"]
                    libre_x, libre_y = self.trouver_case_libre_proche(sx, sy, from_x=tech.x, from_y=tech.y)
                    # Ne traîner vers la sortie QUE les tubes qui y sont réellement déposés.
                    # Les tubes_reportes (files pleines) resteraient visuellement collés au
                    # tech pendant le trajet, puis repartiraient depuis la sortie lors du retry
                    # → on les retire temporairement de carried_tubes le temps du trajet.
                    _reportes_ids  = {id(t) for t in tubes_reportes}
                    _reportes_save = [t for t in tech.carried_tubes if id(t) in _reportes_ids]
                    tech.carried_tubes = [t for t in tech.carried_tubes if id(t) not in _reportes_ids]
                    yield self.env.process(self.deplacer_vers(tech, libre_x, libre_y))
                    # Réintégrer les reportés APRÈS l'arrivée pour le retry
                    tech.carried_tubes.extend(_reportes_save)
                # Enregistrer le temps de transit
                now = self.env.now
                for tube in vers_sortie:
                    if "arrivee" in tube:
                        # TAT réel bout-en-bout = transit navette + labo (marche + files + machine)
                        # On part de t_generation (moment de création du tube, avant la navette)
                        # pour inclure le temps préanalytique dans le TAT total.
                        # La navette et les déplacements sont en SimPy 1:1.
                        # Les protocoles machine s'exécutent via timeout(temps/10), donc
                        # machine_simpy × 10 = minutes réelles en machine → correction +9×.
                        machine_simpy = tube.get("_machine_temps_simpy", 0)
                        t_start = tube.get("t_generation", tube["arrivee"])
                        tat = (now - t_start) + machine_simpy * 9
                        # Si la deque est pleine, soustraire l'élément qui va être évincé
                        # pour garder _transit_sum cohérent sans sum() O(n).
                        if getattr(self.transit_times_raw, 'maxlen', None) and len(self.transit_times_raw) == self.transit_times_raw.maxlen:
                            self._transit_sum -= self.transit_times_raw[0]
                        self.transit_times_raw.append(tat)
                        self._transit_sum += tat
                        if tube.get("urgent"):
                            self.transit_times_urgents.append(tat)
                        else:
                            self.transit_times_normaux.append(tat)
                        # Enregistrement TAT par type de tube
                        ttype = tube.get("type", "?")
                        if ttype not in self.tat_par_type:
                            self.tat_par_type[ttype] = {
                                "normal": deque(maxlen=2_000),
                                "urgent": deque(maxlen=2_000),
                            }
                        if tube.get("urgent"):
                            self.tat_par_type[ttype]["urgent"].append(tat)
                        else:
                            self.tat_par_type[ttype]["normal"].append(tat)
                # Retirer + supprimer APRÈS l'arrivée
                self.tubes_sortis += len(vers_sortie)
                _vs_ids = {id(t) for t in vers_sortie}
                # Libérer les réservations des tubes sortis (workflow vide, aucune machine réservée
                # en principe, mais on nettoie par sécurité)
                self._liberer_reservations(vers_sortie)
                tech.carried_tubes = [t for t in tech.carried_tubes if id(t) not in _vs_ids]
                self._refresh_label_tubes(tech)
                if not self.headless:
                    for tube in vers_sortie:
                        if self.canvas.winfo_exists() and tube.get("id"):
                            self.canvas.delete(tube["id"])

            # Si certains tubes n'ont pas pu être déposés (file pleine), attendre et réessayer
            if tubes_reportes:
                if not self.headless:
                    etapes_bloquees = list({t["workflow"][0] for t in tubes_reportes if t.get("workflow")})
                    print(f"[INFO] {len(tubes_reportes)} tube(s) en attente (machines pleines pour {etapes_bloquees}), retry dans 2 min")
                # Libérer les anciennes réservations (machine était pleine) et en faire
                # de nouvelles sur le prochain slot disponible (peut être une autre machine)
                self._liberer_reservations(tubes_reportes)
                yield self.env.timeout(2)
                _vq_retry = {}
                for tube in tubes_reportes:
                    etape = tube["workflow"][0] if tube.get("workflow") else None
                    if not etape:
                        continue
                    m_obj, m_nom, _ = self._trouver_prochaine_machine(tube, machines, _vq_retry)
                    if m_nom:
                        self.machine_slots_reserved[m_nom] = (
                            self.machine_slots_reserved.get(m_nom, 0) + 1)
                        _vq_retry[m_nom] = _vq_retry.get(m_nom, 0) + 1
                        tube["_reserved_machine"] = m_nom
                tubes = tubes_reportes
            else:
                break

    def _estimer_duree_workflow(self, etapes, machines):
        """Estime la durée totale de traitement en unités SimPy pour une liste d'étapes.

        Chaque étape est un NOM DE PROTOCOLE (ex: 'centi1', 'culot 1').
        Recherche dans l'ordre :
          1. catalog_protocoles (lookup direct par nom de protocole)
          2. recherche dans les protocoles de chaque machine
          3. fallback 60 min si introuvable
        La durée SimPy = config_temps / 10 (compression ×10 du simulateur).
        Retourne 0.0 si la liste est vide.
        """
        # Construction d'un index {nom_protocole: temps_minutes} depuis le catalog
        catalog = self.config_manager.data.get("catalog_protocoles", {})
        # Compléter avec les protocoles déclarés directement dans les machines
        # (source de vérité si catalog absent ou incomplet)
        _proto_index = {}
        for m_cfg in machines.values():
            for p_nom, p_cfg in m_cfg.get("protocoles", {}).items():
                if p_nom not in _proto_index:
                    _proto_index[p_nom] = p_cfg.get("temps", 60)
        for p_nom, p_cfg in catalog.items():
            _proto_index.setdefault(p_nom, p_cfg.get("temps", 60))

        total = 0.0
        for step in etapes:
            total += _proto_index.get(step, 60) / 10
        return total

    def _liberer_reservations(self, tubes):
        """Libère les slots réservés pour une liste de tubes.

        À appeler dès qu'un tube est :
          - effectivement déposé en file machine (slot converti en occupation réelle)
          - abandonné (rappel bureau, erreur, retry annulé)
          - perdu (erreur technicien)
        """
        for tube in tubes:
            m_nom = tube.pop("_reserved_machine", None)
            if m_nom:
                self.machine_slots_reserved[m_nom] = max(
                    0, self.machine_slots_reserved.get(m_nom, 0) - 1)

    def _update_tech_sprite_fatigue(self, tech):
        """Met à jour la bordure du sprite selon la fatigue courante du technicien.

        Vert → Jaune → Orange → Rouge au fur et à mesure que la fatigue monte.
        Délègue aussi la mise à jour de l'emoji bien-être.
        """
        if self.headless or not self.canvas.winfo_exists() or not tech.canvas_id:
            return
        f = tech.fatigue_courante
        if f < 0.25:
            clr, w = "black", 2
        elif f < 0.50:
            clr, w = "#e67e22", 2
        elif f < 0.75:
            clr, w = "#e74c3c", 3
        else:
            clr, w = "#c0392b", 4
        self.canvas.itemconfig(tech.canvas_id, outline=clr, width=w)
        self._update_tech_sprite_bienetre(tech)

    def _refresh_label_tubes(self, tech):
        """Met à jour le label de débogage 'ct1:3; au2:1' à droite du sprite technicien.

        Regroupe carried_tubes par _porteur_machine (machine source pour les tubes
        récupérés depuis output_queues) ou 'entr' pour les tubes venant de l'entrée.
        Vide le label quand le tech ne porte rien.
        """
        lbl_id = getattr(tech, 'label_tubes_id', None)
        if self.headless or not self.canvas.winfo_exists() or not lbl_id:
            return
        comptes = {}
        for t in tech.carried_tubes:
            src = t.get("_porteur_machine") or "entr"
            comptes[src] = comptes.get(src, 0) + 1
        # Une ligne par machine source, empilées verticalement
        lignes = [f"{m}:{n}" for m, n in sorted(comptes.items())]
        txt = "\n".join(lignes) if lignes else ""
        self.canvas.itemconfig(lbl_id, text=txt)
        # Ancrer en haut-gauche du sprite pour que les lignes descendent
        self.canvas.coords(lbl_id, tech.x + 14, tech.y - (len(lignes) - 1) * 6)

    def _update_tech_sprite_bienetre(self, tech):
        """Met à jour l'emoji et la couleur de remplissage selon le bien-être du technicien."""
        if self.headless or not self.canvas.winfo_exists():
            return
        emoji, couleur_be, _ = tech.etat_bien_etre()
        # Couleur de remplissage du cercle : mélange entre couleur identité et couleur bien-être
        # Si en arrêt maladie → remplissage gris + emoji spécial
        if tech.en_arret_maladie:
            if tech.canvas_id:
                self.canvas.itemconfig(tech.canvas_id, fill="#bdc3c7", outline="#7f8c8d", width=3)
            if tech.label_bienetre_id:
                self.canvas.itemconfig(tech.label_bienetre_id, text="🏥")
            return
        # Hors service (plage horaire non active) → icône repos
        if not getattr(tech, 'en_service', True):
            if tech.canvas_id:
                self.canvas.itemconfig(tech.canvas_id, fill="#d5d8dc", outline="#95a5a6", width=2)
            if tech.label_bienetre_id:
                self.canvas.itemconfig(tech.label_bienetre_id, text="💤")
            return
        if tech.canvas_id:
            self.canvas.itemconfig(tech.canvas_id, fill=tech.color)
        if tech.label_bienetre_id:
            self.canvas.itemconfig(tech.label_bienetre_id, text=emoji)
            self.canvas.coords(tech.label_bienetre_id, tech.x, tech.y - 18)
