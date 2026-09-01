"""Mixin _TabLiveStats pour TabLive — extrait de ui/tab_live.py.

Ces méthodes utilisent `self.xxx` défini dans TabLive.__init__.
"""
from collections import deque
import simpy
from core.sim.priorite import (
    _score_priorite, _inserer_par_priorite,
    _trier_queue_par_priorite, _inserer_par_anciennete,
)
from core.sim.sim_io import sauver_stats_sim


class _TabLiveStats:
    """Mixin : ne pas instancier directement."""

    def _escalader_tubes_vieillissants(self, t):
        """Élève en priorité urgente les tubes qui approchent de leur péremption.

        Seuils (paramétrables via la config du type de tube) :
          - 65 % de la durée de validité écoulée → urgence niveau 1 (orange)
          - 85 % écoulée → urgence niveau 2 (rouge vif)
        Seuls les tubes encore dans entry_queue sont repositionnés ; pour les files
        machine la gestion FIFO interne est conservée (on se contente du visuel).
        """
        if not self.entry_queue:
            return

        # Seuils adaptatifs : abaissés par le coordinateur en zone CRITIQUE/VIGILANCE
        n1_seuil = self.coordinateur.seuil_escalade_n1
        n2_seuil = self.coordinateur.seuil_escalade_n2
        escalades = 0

        # ── entry_queue : une seule passe, pas de remove()+insert() O(n²) ────
        # On reconstruit la liste : escaladés en tête, puis urgents existants, puis normaux.
        escalades_tubes   = []
        urgents_existants = []
        non_urgents       = []
        for tube in self.entry_queue:
            dv = tube.get("duree_validite", 0)
            if dv > 0 and not tube.get("perime"):
                age   = t - tube.get("arrivee", t)
                ratio = age / dv
                if ratio >= n2_seuil and not tube.get("urgent"):
                    tube["urgent"]  = True
                    tube["escalade"] = 2
                    escalades_tubes.append(tube)
                    escalades += 1
                    if not self.headless and tube.get("id") and self.canvas.winfo_exists():
                        self.canvas.itemconfig(tube["id"],
                                               fill="#e74c3c", outline="#c0392b", width=3)
                    continue
                elif ratio >= n1_seuil and not tube.get("urgent") and not tube.get("escalade"):
                    tube["urgent"]  = True
                    tube["escalade"] = 1
                    escalades_tubes.append(tube)
                    escalades += 1
                    if not self.headless and tube.get("id") and self.canvas.winfo_exists():
                        self.canvas.itemconfig(tube["id"],
                                               fill="#e67e22", outline="#d35400", width=2)
                    continue
            if tube.get("urgent"):
                urgents_existants.append(tube)
            else:
                non_urgents.append(tube)

        if escalades:
            self.entry_queue = escalades_tubes + urgents_existants + non_urgents

        # ── files machine : visuel uniquement, inutile en mode headless ────────
        if not self.headless and self.canvas.winfo_exists():
            for q in self.machine_queues.values():
                for tube in q:
                    dv = tube.get("duree_validite", 0)
                    if dv <= 0 or tube.get("perime"):
                        continue
                    age   = t - tube.get("arrivee", t)
                    ratio = age / dv
                    if not tube.get("id"):
                        continue
                    if ratio >= n2_seuil and not tube.get("escalade"):
                        tube["escalade"] = 2
                        self.canvas.itemconfig(tube["id"],
                                               fill="#e74c3c", outline="#c0392b", width=3)
                    elif ratio >= n1_seuil and not tube.get("escalade"):
                        tube["escalade"] = 1
                        self.canvas.itemconfig(tube["id"],
                                               fill="#e67e22", outline="#d35400", width=2)

        if escalades:
            self.stats_history.setdefault("escalades_count", [])
            self.stats_history["escalades_count"].append((t, escalades))

    def stats_collector(self):
        """Échantillonne l'état des files toutes les 2 unités de simulation pour les graphiques goulots."""
        interval = 2.0
        # deque(maxlen=N) : append en O(1), cap automatique — pas de pop(0) manuel.
        # 43 200 pts = 2 min × 43 200 = 86 400 min sim ≈ 60 jours.
        MAX_SERIES = 43_200

        while self.running:
            t = self.env.now
            sh = self.stats_history

            # ── Séries temporelles (deque à maxlen → auto-cap O(1)) ──────────
            sh["time"].append(t)
            sh["entry"].append(len(self.entry_queue))

            machines = self.config_manager.get_machines()
            for nom, m in machines.items():
                if m["type"] in ("ENTREE", "SORTIE", "TECH_OFFICE", "REPOS"):
                    continue
                if nom not in sh["queues"]:
                    sh["queues"][nom] = deque(maxlen=MAX_SERIES)
                sh["queues"][nom].append(len(self.machine_queues.get(nom, [])))

                if nom not in sh["output"]:
                    sh["output"][nom] = deque(maxlen=MAX_SERIES)
                sh["output"][nom].append(len(self.output_queues.get(nom, [])))

                if nom not in sh["busy"]:
                    sh["busy"][nom] = deque(maxlen=MAX_SERIES)
                sh["busy"][nom].append(1 if nom in self.blinking_machines else 0)

            # Temps de transit : moyenne + glissante (20 derniers tubes)
            # _transit_sum est maintenu de manière incrémentale (avec gestion de l'éviction
            # dans technician_process). Pas de sum() O(n) ici.
            if self.transit_times_raw:
                n = len(self.transit_times_raw)
                avg_transit = self._transit_sum / n
                window = list(self.transit_times_raw)[-20:]
                rolling_transit = sum(window) / len(window)
            else:
                avg_transit = None
                rolling_transit = None
            sh["transit_time_avg"].append(avg_transit)
            sh["transit_time_rolling"].append(rolling_transit)

            # TAT glissant séparé normaux vs urgents (20 derniers de chaque)
            if self.transit_times_normaux:
                w_n = list(self.transit_times_normaux)[-20:]
                sh["tat_normal_rolling"].append(sum(w_n) / len(w_n))
            else:
                sh["tat_normal_rolling"].append(None)
            if self.transit_times_urgents:
                w_u = list(self.transit_times_urgents)[-20:]
                sh["tat_urgent_rolling"].append(sum(w_u) / len(w_u))
            else:
                sh["tat_urgent_rolling"].append(None)

            # Âge du plus vieux tube encore en attente dans le système.
            # Stratégie O(entrée) + O(nb_machines) :
            #   • entry_queue : scan complet en O(n) — drainée activement par les techs,
            #     reste petite même avec goulot. On prend le min(arrivee) car les urgents
            #     sont insérés en tête (insert(0)) et masqueraient le vrai plus ancien.
            #   • machine_queues / output_queues : FIFO purs (append uniquement) → position 0
            #     est toujours le plus ancien, O(1) par file.
            ages_en_attente = []
            if self.entry_queue:
                oldest_entry = min(
                    (tube["arrivee"] for tube in self.entry_queue if "arrivee" in tube),
                    default=None,
                )
                if oldest_entry is not None:
                    ages_en_attente.append(t - oldest_entry)
            for _q in self.machine_queues.values():
                if _q and "arrivee" in _q[0]:
                    ages_en_attente.append(t - _q[0]["arrivee"])
            for _q in self.output_queues.values():
                if _q and "arrivee" in _q[0]:
                    ages_en_attente.append(t - _q[0]["arrivee"])
            pending_max = max(ages_en_attente) if ages_en_attente else None
            sh["transit_time_pending_max"].append(pending_max)

            # Compteurs d'erreurs (valeurs cumulatives, parallèles à "time")
            sh["rejetes"].append(self.tubes_rejetes)
            sh["degrades"].append(self.tubes_degrades)

            # Distance journalière par technicien (1 jour SimPy = 1440 min)
            # 1 case = 50 px ; metres_par_case (config) définit l'échelle réelle.
            # Par défaut 3.0 m/case → 1 px = 0.06 m (lab ~72 m x 42 m)
            personnel_cfg_dist = self.config_manager.data.get("personnel", {})
            _metres_par_px = float(personnel_cfg_dist.get("metres_par_case", 3.0)) / 50.0
            JOUR_DUREE = 1440.0
            jour_actuel = int(t / JOUR_DUREE)
            if not hasattr(self, "_jours_connus_dist"):
                self._jours_connus_dist = set()
            # Transition de jour : mettre à jour le snapshot de TOUS les techs
            # AVANT de calculer d_m, et en dehors de la boucle for.
            if jour_actuel not in self._jours_connus_dist:
                self._jours_connus_dist.add(jour_actuel)
                if jour_actuel > 0:
                    personnel_cfg = self.config_manager.data.get("personnel", {})
                    cap_jour = float(personnel_cfg.get("capacite_journaliere_normale", 150))
                    import random as _rnd
                    horaires_cfg = self.config_manager.data.get("horaires", {})
                    jour_debut_sim = int(self.config_manager.data.get("personnel", {}).get("jour_debut_simulation", 0))
                    # Le jour qui vient de s'écouler est jour_actuel - 1
                    jour_hier_semaine = (jour_debut_sim + jour_actuel - 1) % 7
                    for tech in self.technicians:
                        tech._distance_debut_jour_px = tech.distance_parcourue_px
                        tubes_jour = tech.tubes_livres_session - tech._tubes_livres_debut_jour
                        tech._tubes_livres_debut_jour = tech.tubes_livres_session
                        # Récupération nocturne de la fatigue physique
                        tech.fatigue_courante = max(0.0, tech.fatigue_courante - 0.40)
                        if tech.en_arret_maladie:
                            # Congé maladie : récupération accélérée du mécontentement
                            tech.mecontentement = max(0.0, tech.mecontentement - 0.10)
                            tech.fatigue_courante = max(0.0, tech.fatigue_courante - 0.20)
                            # Retour au travail : probabilité minimale garantie à 5 %
                            # pour éviter qu'un tech très épuisé ne revienne jamais
                            # (mecontentement ≥ 0.75 donnait 0 % → blocage permanent)
                            proba_retour = max(0.05, 0.60 - tech.mecontentement * 0.80)
                            if _rnd.random() < proba_retour:
                                tech.en_arret_maladie = False
                                tech.jours_consecutifs_surcharge = 0
                                self.stats_history["events_arret_maladie"].append({
                                    "t": t, "nom": tech.nom, "type": "retour",
                                    "mecontentement": round(tech.mecontentement, 3),
                                })
                            tech.jours_conges_consecutifs = 0  # congé maladie ≠ repos planifié
                        else:
                            # Déterminer si hier était un jour de repos AVANT le calcul de
                            # mécontentement : les tubes livrés en garde sur un jour de repos
                            # ne doivent pas être comptés en surcharge (cap_jour = journée pleine).
                            tech_horaire = horaires_cfg.get(tech.nom, {})
                            jours_travail = tech_horaire.get("jours", list(range(5)))
                            est_conge = jour_hier_semaine not in jours_travail
                            if est_conge and tubes_jour == 0:
                                # Vrai jour de repos : aucun tube traité, pas de rappel en garde.
                                # Récupération nocturne complète.
                                tech.mecontentement = max(
                                    0.0,
                                    tech.mecontentement * (1.0 - tech.taux_recuperation_nuit)
                                )
                                tech.jours_consecutifs_surcharge = 0
                                tech.jours_conges_consecutifs += 1
                                if tech.jours_conges_consecutifs >= 2:
                                    bonus = 0.08 + (tech.jours_conges_consecutifs - 2) * 0.03
                                    tech.mecontentement = max(0.0, tech.mecontentement - bonus)
                                    tech.fatigue_courante = max(0.0, tech.fatigue_courante - 0.15)
                            else:
                                # Jour travaillé (normal ou rappelé en garde sur jour de congé) :
                                # la charge réelle (tubes_jour) détermine le mécontentement.
                                tech.mettre_a_jour_mecontentement(tubes_jour, cap_jour)
                                tech.jours_conges_consecutifs = 0
                                # Risque arrêt maladie : tirage aléatoire journalier
                                # (désactivé en mode test « sans arrêts maladie »)
                                if not self.mode_sans_arret_maladie:
                                    risque = tech.calculer_risque_arret_maladie()
                                    if risque > 0 and _rnd.random() < risque:
                                        tech.en_arret_maladie = True
                                        self.stats_history["events_arret_maladie"].append({
                                            "t": t, "nom": tech.nom, "type": "debut",
                                            "mecontentement": round(tech.mecontentement, 3),
                                        })
                        self._update_tech_sprite_bienetre(tech)
                        _k_be = tech.nom if tech.nom else f"Tech {self.technicians.index(tech) + 1}"
                        if _k_be not in self.stats_history["bienetre"]:
                            self.stats_history["bienetre"][_k_be] = {}
                        # Écrire la valeur authoritative du jour écoulé (hier = jour_actuel-1).
                        self.stats_history["bienetre"][_k_be][jour_actuel - 1] = round(tech.mecontentement, 3)
            for idx, tech in enumerate(self.technicians):
                k = tech.nom if tech.nom else f"Tech {idx + 1}"
                if k not in self.stats_history["distances_tech"]:
                    self.stats_history["distances_tech"][k] = {}
                d_m = (tech.distance_parcourue_px - tech._distance_debut_jour_px) * _metres_par_px
                self.stats_history["distances_tech"][k][jour_actuel] = round(d_m, 1)
                # Historique bien-être (valeur courante)
                if k not in self.stats_history["bienetre"]:
                    self.stats_history["bienetre"][k] = {}
                self.stats_history["bienetre"][k][jour_actuel] = round(tech.mecontentement, 3)

            # ── Escalade des tubes vieillissants ──────────────────────────────────────
            # Un tube qui a dépassé 65 % de sa durée de validité devient urgent
            # pour être traité avant péremption complète.
            self._escalader_tubes_vieillissants(t)

            # ── Péremption des tubes dans toutes les files ───────────────────
            # entry_queue uniquement : reconstruite en une passe O(n_entry).
            # machine_queues / output_queues : gérées par traiter_batch_machine
            # (rejet prédictif _batch_viables + delai_max_avant_degrad). Les scanner
            # ici serait O(n_total_tubes) par tick → O(n²) avec goulot.
            def _purger_queue(q):
                """Retire les tubes périmés d'une liste. Retourne (nouvelle_liste, nb_retirés)."""
                nouvelle, nb = [], 0
                for tube in q:
                    dv = tube.get("duree_validite", 0)
                    if dv > 0 and not tube.get("perime") and (t - tube.get("arrivee", t)) > dv:
                        tube["perime"] = True
                        self.tubes_perimes += 1
                        self.tubes_degrades += 1
                        if not self.headless and tube.get("id") and self.canvas.winfo_exists():
                            self.canvas.itemconfig(tube["id"],
                                                   fill="#bdc3c7", outline="#e74c3c", width=2)
                            tid = tube["id"]
                            self.canvas.after(
                                800,
                                lambda _t=tid: self.canvas.delete(_t)
                                if self.canvas.winfo_exists() else None)
                        nb += 1
                    else:
                        nouvelle.append(tube)
                return nouvelle, nb

            if self.entry_queue:
                nouvelle_eq, _ = _purger_queue(self.entry_queue)
                if len(nouvelle_eq) != len(self.entry_queue):
                    self.entry_queue = nouvelle_eq

            # ── Watchdog : forcer un batch si un tube est bloqué trop longtemps ──
            # Cas typique : arrivées lentes → capacite jamais atteinte → machine jamais déclenchée.
            # Paramètre JSON par machine : "timeout_batch" (minutes, défaut 60).
            # GARDE : _machines_batch_actif empêche tout doublon de processus.
            for nom_wm, conf_wm in machines.items():
                if conf_wm.get("type") in ("ENTREE", "SORTIE", "TECH_OFFICE", "REPOS"):
                    continue
                # Les machines de stockage (frigo, congélateur) ne font pas de traitement par batch
                if conf_wm.get("sous_categorie") == "STOCKAGE":
                    continue
                q_wm = self.machine_queues.get(nom_wm, [])
                if q_wm and nom_wm not in self._machines_batch_actif:
                    oldest_age = t - q_wm[0].get("arrivee", t)
                    timeout_batch = conf_wm.get("timeout_batch", 60)
                    if oldest_age > timeout_batch:
                        # Les machines à opérateur requis ne démarrent que si un tech est au poste
                        tech_present = not conf_wm.get("tech_requis_poste", False) or nom_wm in self.paillasse_analyste
                        if tech_present:
                            self._machines_batch_actif.add(nom_wm)
                            self.env.process(self.traiter_batch_machine(nom_wm, conf_wm))

            # ── Alimenter l'aggregator multi-niveaux ────────────────────────
            busy_snap = {}
            for nom_m in self.stats_history.get("busy", {}):
                vals = self.stats_history["busy"][nom_m]
                busy_snap[nom_m] = vals[-1] if vals else None
            queues_snap = {}
            for nom_m in self.stats_history.get("queues", {}):
                vals = self.stats_history["queues"][nom_m]
                queues_snap[nom_m] = vals[-1] if vals else None
            tr_raw = self.stats_history.get("transit_times_raw", [])
            pend = self.stats_history["transit_time_pending_max"]
            self.aggregator.tick(t, {
                "entry":              len(self.entry_queue),
                "transit_rolling":    self.stats_history["transit_time_rolling"][-1] if self.stats_history["transit_time_rolling"] else None,
                "transit_pending_max": pend[-1] if pend else None,
                "busy":               busy_snap,
                "queues":             queues_snap,
            })

            yield self.env.timeout(interval)

    def _analyse_prospective(self, horizon_min: float = 20.0) -> dict:
        """Analyse les tubes en attente de ramassage et en transit pour anticiper les arrivées.

        Retourne un dict :
          nb_total          : nombre de tubes qui arriveront dans `horizon_min` minutes
          nb_urgents        : dont urgents
          par_service       : {fid: nb_tubes}
          charge_workflows  : {etape_workflow: nb_tubes attendus} → pré-charge estimée
          rush_detecte      : True si seuil dépassé
          urgence_critique  : True si nb_urgents >= seuil_urgents
        """
        now      = self.env.now
        nb_total = 0
        nb_urgents = 0
        par_service: dict    = {}
        charge_workflows: dict = {}

        navette_conf = self._cache_navette_conf
        if navette_conf is None:
            navette_conf = self.config_manager.get_navette_principale()
            self._cache_navette_conf = navette_conf
        freq_ramassage = float(navette_conf.get("frequence_jour_min", 30))

        # 1. Tubes en transit (ETA exacte — données prospectives fiables)
        for fid, tubes in self.navette_en_transit.items():
            for tube in tubes:
                eta = tube.get("eta_labo", now)
                if eta - now <= horizon_min:
                    nb_total += 1
                    if tube.get("urgent"):
                        nb_urgents += 1
                    par_service[fid] = par_service.get(fid, 0) + 1
                    for etape in tube.get("workflow", []):
                        charge_workflows[etape] = charge_workflows.get(etape, 0) + 1

        # 2. Tubes en queue navette (pas encore ramassés)
        #    ETA optimiste = trajet seul ; si ≤ horizon, ils arriveront probablement à temps
        fournisseurs = self._cache_fournisseurs
        if fournisseurs is None:
            fournisseurs = self.config_manager.get_fournisseurs()
            self._cache_fournisseurs = fournisseurs
        for fid, queue in self.navette_queues.items():
            if not queue:
                continue
            fconf  = fournisseurs.get(fid, {})
            trajet = float(fconf.get("duree_trajet_min", 10.0))
            # Pire cas : on vient juste de rater un passage → attente jusqu'au prochain
            eta_pire_cas = trajet + freq_ramassage
            if eta_pire_cas <= horizon_min:
                # Tous arriveront dans l'horizon même au pire
                tubes_dans_horizon = queue
            elif trajet <= horizon_min:
                # Seulement ceux ramassés au prochain passage (capacite_max)
                cap = int(navette_conf.get("capacite_max", 20))
                tubes_dans_horizon = queue[:cap]
            else:
                tubes_dans_horizon = []

            for tube in tubes_dans_horizon:
                nb_total += 1
                if tube.get("urgent"):
                    nb_urgents += 1
                par_service[fid] = par_service.get(fid, 0) + 1
                for etape in tube.get("workflow", []):
                    charge_workflows[etape] = charge_workflows.get(etape, 0) + 1

        seuil_rush    = 8   # tubes dans l'horizon pour déclarer un rush
        seuil_urgents = 3   # urgents dans l'horizon pour déclarer urgence critique

        return {
            "nb_total":         nb_total,
            "nb_urgents":       nb_urgents,
            "par_service":      par_service,
            "charge_workflows": charge_workflows,
            "rush_detecte":     nb_total >= seuil_rush,
            "urgence_critique": nb_urgents >= seuil_urgents,
        }

    def _reequilibrer_pour_rush(self, prospectif: dict):
        """Réorganise entry_queue pour absorber le rush entrant.

        Stratégie :
          - Urgents en tête (déjà la règle, on renforce)
          - Parmi les non-urgents : tubes avec workflow court d'abord
            → libérer les techniciens rapidement avant l'afflux
        Enregistre l'action dans stats_history["anticipations"].
        """
        if not self.entry_queue:
            return
        avant = len(self.entry_queue)
        urgents     = [t for t in self.entry_queue if t.get("urgent")]
        non_urgents = [t for t in self.entry_queue if not t.get("urgent")]
        # Courts workflows d'abord → maximise le throughput avant la vague
        non_urgents.sort(key=lambda t: len(t.get("workflow", [])))
        self.entry_queue = urgents + non_urgents

        self.stats_history.setdefault("anticipations", deque(maxlen=2_000))
        self.stats_history["anticipations"].append({
            "t":                    self.env.now,
            "nb_entrants_prevus":   prospectif["nb_total"],
            "nb_urgents_prevus":    prospectif["nb_urgents"],
            "queue_reordonnee":     avant,
            "par_service":          dict(prospectif["par_service"]),
        })

    def coordinateur_process(self):
        """Process SimPy : évalue la tension du labo toutes les N minutes simulées.

        En mode VIGILANCE/CRITIQUE :
          - seuils d'escalade abaissés (tubes prioritaires plus tôt)
          - multiplicateurs de poids amplifiés dans le scoring
        En mode CRITIQUE avec IA activée :
          - appel Qwen 2.5 32B pour ajustements dynamiques
          - synchrone en headless (benchmark), thread en mode live
        """
        profil_defaut = [
            [0.0, 0.1], [6.0, 0.3], [7.0, 0.8], [8.0, 1.5], [9.0, 1.8],
            [10.0, 1.4], [11.0, 1.1], [12.0, 0.6], [13.0, 0.7], [14.0, 1.2],
            [15.0, 1.0], [16.0, 0.7], [17.0, 0.4], [18.0, 0.2], [20.0, 0.1], [24.0, 0.1],
        ]
        while self.running:
            yield self.env.timeout(self.coordinateur.intervalle_min)
            if not self.running:
                break

            # Lire config ENTREE
            machines = self.config_manager.get_machines()
            entree   = next((m for m in machines.values() if m.get("type") == "ENTREE"), {})
            profil_horaire = sorted(
                entree.get("profil_horaire", profil_defaut), key=lambda p: p[0])
            frequence_base = float(entree.get("frequence", 5.0))

            snap = self.coordinateur.evaluer(
                t               = self.env.now,
                heure_debut_sim = self.heure_debut_sim,
                entry_queue_len = self.entry_queue,
                machine_queues  = self.machine_queues,
                profil_horaire  = profil_horaire,
                frequence_base  = frequence_base,
            )

            # ── Récupérer une éventuelle réponse IA du tick précédent (mode live) ──
            reponse_async = self.coordinateur.recuperer_reponse_ia()
            if reponse_async:
                self.coordinateur.appliquer_reponse_ia(reponse_async)
                self.stats_history["stress_events"][-1]["ia_reponse"] = reponse_async

            # ── Enregistrer dans l'historique ────────────────────────────────────
            event = {
                "t"       : snap.t,
                "zone"    : snap.zone,
                "tension" : snap.tension,
                "entry"   : snap.entry_queue_len,
                "total"   : snap.total_en_attente,
                "urgents" : snap.nb_urgents,
                "facteur" : snap.facteur_horaire,
                "baseline": snap.baseline,
                "ia"      : self.coordinateur.ia_active,
            }
            self.stats_history["stress_events"].append(event)

            # ── Mise à jour indicateur visuel zone stress ─────────────────────────
            if not self.headless:
                self._maj_label_stress(snap.zone, snap.tension)

            if snap.zone in ("VIGILANCE", "CRITIQUE"):
                self._escalader_tubes_vieillissants(self.env.now)

            # ── Analyse prospective : anticipation des rushes entrants ────────────
            prospectif = self._analyse_prospective(horizon_min=20.0)
            event["prospectif"] = {
                "nb_entrants_prevus":  prospectif["nb_total"],
                "nb_urgents_prevus":   prospectif["nb_urgents"],
                "rush_detecte":        prospectif["rush_detecte"],
                "urgence_critique":    prospectif["urgence_critique"],
                "par_service":         prospectif["par_service"],
            }
            if prospectif["rush_detecte"] or prospectif["urgence_critique"]:
                if self.anticipation_active:
                    self._reequilibrer_pour_rush(prospectif)

            # ── Appel IA si zone VIGILANCE (pic imminent) ou CRITIQUE ────────────
            # Jamais en mode headless : l'appel Ollama est synchrone et bloquerait
            # le thread de simulation pour chaque tick en zone de stress.
            if snap.zone in ("VIGILANCE", "CRITIQUE") and self.coordinateur.ia_active and not self.headless:
                nb_actifs = sum(1 for t in self.technicians
                                if not t.en_arret_maladie and t.en_service)
                nb_pannes = len(self.panne_machines)
                reponse = self.coordinateur.consulter_ia(
                    snap, nb_actifs, nb_pannes, headless=self.headless,
                    prospectif=prospectif)
                if reponse:   # synchrone (headless) : appliquer immédiatement
                    self.coordinateur.appliquer_reponse_ia(reponse)
                    event["ia_reponse"] = reponse

    def _maj_label_stress(self, zone: str, tension: float):
        """Met à jour l'indicateur de stress dans la barre de contrôle."""
        if not hasattr(self, "lbl_stress") or not self.lbl_stress.winfo_exists():
            return
        couleurs = {"STABLE": "#27ae60", "VIGILANCE": "#e67e22", "CRITIQUE": "#e74c3c"}
        icones   = {"STABLE": "🟢", "VIGILANCE": "🟡", "CRITIQUE": "🔴"}
        c = couleurs.get(zone, "#7f8c8d")
        i = icones.get(zone, "⚪")
        self.lbl_stress.config(
            text=f"{i} Stress: {zone} ({tension:.1f}×)",
            foreground=c,
        )
