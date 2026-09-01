"""Mixin _TabLiveGeneration pour TabLive — extrait de ui/tab_live.py.

Ces méthodes utilisent `self.xxx` défini dans TabLive.__init__.
"""
from collections import deque
import simpy
import random
from core.sim.priorite import (
    _score_priorite, _inserer_par_priorite,
    _trier_queue_par_priorite, _inserer_par_anciennete,
)


class _TabLiveGeneration:
    """Mixin : ne pas instancier directement."""

    def tube_generation_fournisseur(self, fid: str, fconf: dict):
        """Génère des tubes pour un fournisseur et les place dans sa file navette.

        Paramètres lus depuis fconf à chaque tirage (modifications en live).

        Paramètres optionnels de variabilité par service :
          surge_proba       : prob. par tube de déclencher un rush (0.0–1.0)
          surge_facteur     : multiplicateur de fréquence durant le rush (ex: 4.0)
          surge_duree_min   : durée min du rush en minutes sim
          surge_duree_max   : durée max du rush en minutes sim
          pause_proba       : prob. par tube d'une interruption imprévisible
          pause_duree_min   : durée min de la pause en minutes sim
          pause_duree_max   : durée max de la pause en minutes sim
          batch_proba       : prob. d'une arrivée en lot (ex: fin d'opération)
          batch_min         : nombre min de tubes dans le lot
          batch_max         : nombre max de tubes dans le lot
        """
        profil_defaut = [
            [0.0, 0.1], [7.0, 0.8], [9.0, 1.8], [17.0, 0.4], [24.0, 0.1],
        ]

        def _facteur(heure_sim: float) -> float:
            heure_debut = fconf.get("heure_debut", 7.0)
            heure_act   = (heure_debut + heure_sim / 60.0) % 24.0
            profil      = sorted(fconf.get("profil_horaire", profil_defaut),
                                 key=lambda p: p[0])
            for i in range(len(profil) - 1):
                h0, f0 = profil[i]
                h1, f1 = profil[i + 1]
                if h0 <= heure_act < h1:
                    alpha = (heure_act - h0) / (h1 - h0)
                    return max(0.05, f0 + alpha * (f1 - f0))
            return max(0.05, profil[-1][1])

        _surge_fin = 0.0  # heure sim de fin du rush en cours
        _pause_fin = 0.0  # heure sim de fin de la pause en cours

        while self.running:
            # --- 1. Calcul de l'inter-arrivée (surge boost si actif) ---
            freq_base = float(fconf.get("frequence_base", 30))
            gamma_k   = float(fconf.get("gamma_k", 2.0))
            facteur   = _facteur(self.env.now)
            if self.env.now < _surge_fin:
                # Rush en cours : facteur augmenté → tubes plus fréquents
                facteur *= float(fconf.get("surge_facteur", 3.0))
            freq_mod = max(0.5, freq_base / facteur)
            theta    = freq_mod / gamma_k
            inter    = random.gammavariate(gamma_k, theta)
            yield self.env.timeout(inter)

            if not self.types_tubes or not fconf.get("actif", True):
                continue

            # --- 2. Pause imprévisible (coursier en retard, problème interne) ---
            pause_proba = float(fconf.get("pause_proba", 0.0))
            if pause_proba > 0 and self.env.now >= _pause_fin and random.random() < pause_proba:
                p_min = float(fconf.get("pause_duree_min", 5))
                p_max = float(fconf.get("pause_duree_max", 20))
                duree_pause = random.uniform(p_min, max(p_min, p_max))
                _pause_fin  = self.env.now + duree_pause
                _stats = self.navette_stats.setdefault(fid, {})
                _stats["nb_pauses"] = _stats.get("nb_pauses", 0) + 1
                yield self.env.timeout(duree_pause)
                continue  # recalcul de l'inter-arrivée après la pause

            # --- 3. Déclenchement d'un nouveau rush (si pas déjà en surge) ---
            surge_proba = float(fconf.get("surge_proba", 0.0))
            if surge_proba > 0 and self.env.now >= _surge_fin and random.random() < surge_proba:
                s_min      = float(fconf.get("surge_duree_min", 15))
                s_max      = float(fconf.get("surge_duree_max", 45))
                _surge_fin = self.env.now + random.uniform(s_min, max(s_min, s_max))
                _stats = self.navette_stats.setdefault(fid, {})
                _stats["nb_surges"] = _stats.get("nb_surges", 0) + 1

            # --- 4. Arrivée en lot (fin d'opération, livraison groupée) ---
            batch_proba = float(fconf.get("batch_proba", 0.0))
            if batch_proba > 0 and random.random() < batch_proba:
                b_min    = int(fconf.get("batch_min", 2))
                b_max    = int(fconf.get("batch_max", 5))
                nb_tubes = random.randint(b_min, max(b_min, b_max))
            else:
                nb_tubes = 1

            # --- 5. Choisir le type de tube parmi ceux que ce fournisseur émet ---
            types_emis    = fconf.get("types_tubes_emis", list(self.types_tubes.keys()))
            types_valides = [t for t in types_emis if t in self.types_tubes]
            if not types_valides:
                types_valides = list(self.types_tubes.keys())
            if not types_valides:
                continue

            # --- 6. Créer et déposer les tubes (nb_tubes fois) ---
            for _ in range(nb_tubes):
                nom_type = random.choice(types_valides)
                conf     = self.types_tubes[nom_type]

                _dv_min = int(conf.get("duree_validite_min", 0))
                _dv_max = int(conf.get("duree_validite_max", _dv_min))
                _dv     = random.randint(_dv_min, max(_dv_min, _dv_max)) if _dv_min > 0 else 0

                tube = {
                    "type":           nom_type,
                    "workflow":       list(conf.get("workflow", [])),
                    "couleur":        conf.get("couleur", "#3498db"),
                    "arrivee":        self.env.now,
                    "t_generation":   self.env.now,
                    "deadline":       self.env.now + _dv if _dv > 0 else 0,
                    "urgent":         random.random() < float(fconf.get("pct_urgent", 0.05)),
                    "duree_validite": _dv,
                    "fournisseur":    fid,
                    "id":             None,
                }

                if fid not in self.navette_queues:
                    self.navette_queues[fid] = []
                self.navette_queues[fid].append(tube)
                self.stats_tubes_total += 1

            self.navette_stats[fid]["en_queue"] = len(self.navette_queues[fid])

    def navette_process(self, fid: str, fconf: dict, navette_conf: dict):
        """Gère les ramassages de la navette avec planning jour/nuit et imprévus.

        Paramètres navette_conf :
          heure_debut_jour   : début de la plage diurne (défaut 6.0)
          heure_fin_jour     : fin de la plage diurne (défaut 22.0)
          frequence_jour_min : intervalle de ramassage en journée, en minutes (défaut 30)
          facteur_nuit       : fraction du service offerte la nuit vs le jour (défaut 0.5)
                               → freq_nuit = frequence_jour / facteur_nuit (ex: 30/0.5 = 60 min)
          capacite_max       : nombre max de tubes par ramassage (défaut 20)
          priorite_urgents   : départ anticipé si tube urgent en queue (défaut True)
          imprevu_proba      : probabilité d'un retard imprévu par ramassage (défaut 0.05)
          imprevu_delay_min  : retard min en minutes (défaut 10)
          imprevu_delay_max  : retard max en minutes (défaut 45)
        """
        def _heure_actuelle() -> float:
            """Heure de la journée (0–24) correspondant au temps SimPy courant."""
            return (self.heure_debut_sim + self.env.now / 60.0) % 24.0

        while self.running:
            # --- Paramètres (relus à chaque cycle pour prise en compte live) ---
            cap           = int(navette_conf.get("capacite_max", 20))
            priorite      = navette_conf.get("priorite_urgents", True)
            trajet        = float(fconf.get("duree_trajet_min", 10.0))
            freq_jour     = float(navette_conf.get("frequence_jour_min", 30))
            h_deb_jour    = float(navette_conf.get("heure_debut_jour", 6.0))
            h_fin_jour    = float(navette_conf.get("heure_fin_jour", 22.0))
            facteur_nuit  = max(0.05, float(navette_conf.get("facteur_nuit", 0.5)))
            imprevu_proba = float(navette_conf.get("imprevu_proba", 0.05))
            imprevu_min   = float(navette_conf.get("imprevu_delay_min", 10))
            imprevu_max   = float(navette_conf.get("imprevu_delay_max", 45))

            # --- Cadence selon l'heure courante ---
            heure_act = _heure_actuelle()
            if h_deb_jour <= heure_act < h_fin_jour:
                freq = freq_jour                          # plage diurne
            else:
                freq = freq_jour / facteur_nuit           # nuit : service réduit

            # --- Attente jusqu'au prochain ramassage planifié ---
            t_depart = self.env.now + freq
            if self.headless:
                # Headless : saut direct — pas de polling à 1-min (réduit ~10× le nombre
                # d'events SimPy par navette, évite les faux freeze sur simulations longues)
                yield self.env.timeout(freq)
            else:
                while self.env.now < t_depart and self.running:
                    queue = self.navette_queues.get(fid, [])
                    if priorite and any(t.get("urgent") for t in queue):
                        break   # départ anticipé si urgent détecté
                    yield self.env.timeout(min(1.0, t_depart - self.env.now))

            # --- Imprévu : retard aléatoire du coursier ---
            if imprevu_proba > 0 and random.random() < imprevu_proba:
                retard = random.uniform(imprevu_min, max(imprevu_min, imprevu_max))
                _s = self.navette_stats.setdefault(fid, {})
                _s["nb_imprévus"]       = _s.get("nb_imprévus", 0) + 1
                _s["retard_cumule_min"] = _s.get("retard_cumule_min", 0.0) + retard
                yield self.env.timeout(retard)

            # --- Ramassage : prendre jusqu'à cap tubes ---
            queue = self.navette_queues.get(fid, [])
            lot   = queue[:cap]
            self.navette_queues[fid] = queue[cap:]

            if not lot:
                yield self.env.timeout(1)
                continue

            # Mise à jour stats
            stats = self.navette_stats.get(fid, {})
            stats["en_transit"]    = stats.get("en_transit", 0) + len(lot)
            stats["total_envoye"]  = stats.get("total_envoye", 0) + len(lot)
            stats["en_queue"]      = len(self.navette_queues.get(fid, []))
            stats["nb_ramassages"] = stats.get("nb_ramassages", 0) + 1
            self.navette_stats[fid] = stats

            # --- Transit vers le labo (suivi prospectif) ---
            eta_labo = self.env.now + trajet
            for tube in lot:
                tube["eta_labo"] = eta_labo   # ETA exacte connue dès le ramassage
            if fid not in self.navette_en_transit:
                self.navette_en_transit[fid] = []
            self.navette_en_transit[fid].extend(lot)

            yield self.env.timeout(trajet)

            # Retirer du suivi prospectif
            en_tr = self.navette_en_transit.get(fid, [])
            for tube in lot:
                try:
                    en_tr.remove(tube)
                except ValueError:
                    pass

            # Livraison au labo
            now = self.env.now
            stats["en_transit"] = max(0, stats.get("en_transit", 0) - len(lot))
            stats["en_queue"]   = len(self.navette_queues.get(fid, []))

            entrees_cfg = [m for m in self.config_manager.get_machines().values()
                           if m["type"] == "ENTREE"]
            tx = entrees_cfg[0].get("coords", {}).get("x", 100) if entrees_cfg else 100
            ty = entrees_cfg[0].get("coords", {}).get("y", 100) if entrees_cfg else 100

            for tube in lot:
                tube["arrivee"] = now   # temps d'arrivée effective au labo
                # Temps préanalytique (transit navette) en minutes réelles
                t_gen = tube.get("t_generation", now)
                if now > t_gen:
                    # Temps préanalytique = pure attente + transit navette, pas de compression
                    # (la navette n'utilise pas timeout(temps/10), 1 SimPy = 1 min réelle)
                    preana = now - t_gen
                    ttype = tube.get("type", "?")
                    if ttype not in self.preanalyse_par_type:
                        self.preanalyse_par_type[ttype] = deque(maxlen=2_000)
                    self.preanalyse_par_type[ttype].append(preana)
                heure_abs = int((now / 60 + self.heure_debut_sim)) % 24
                aph       = self.stats_history["arrivees_par_heure"]
                aph[heure_abs] = aph.get(heure_abs, 0) + 1
                aphs = self.stats_history["arrivees_par_heure_par_service"]
                if heure_abs not in aphs:
                    aphs[heure_abs] = {}
                aphs[heure_abs][fid] = aphs[heure_abs].get(fid, 0) + 1

                if not self.headless:
                    ox = random.randint(-8, 8)
                    oy = random.randint(-8, 8)
                    try:
                        outline_color = "#e74c3c" if tube["urgent"] else "white"
                        outline_w     = 2 if tube["urgent"] else 1
                        tube["id"] = self.canvas.create_oval(
                            tx+ox-6, ty+oy-6, tx+ox+6, ty+oy+6,
                            fill=tube["couleur"],
                            outline=outline_color, width=outline_w,
                        )
                    except Exception:
                        tube["id"] = None

                if tube.get("urgent"):
                    self.entry_queue.insert(0, tube)
                else:
                    self.entry_queue.append(tube)

    def tube_generation(self):
        """Génère les tubes avec inter-arrivées gamma et profil horaire jour (fréquence varie selon l'heure).

        Config sur la machine ENTREE :
          - frequence    : inter-arrivée moyenne de base (unités SimPy = minutes)
          - gamma_k      : paramètre de forme Gamma (défaut 2.0). Élevé = moins variable.
          - heure_debut  : heure de démarrage de la simulation (défaut 7.0 = 7h00)
          - profil_horaire : liste [[heure, facteur], ...] définissant la densité relative
                             par tranche horaire (interpolation linéaire).
        Tous les paramètres sont relus à chaque tirage — les modifications dans la config
        sont donc prises en compte immédiatement, sans redémarrer la simulation.
        """
        machines = self.config_manager.get_machines()
        entrees_noms = [nom for nom, m in machines.items() if m["type"] == "ENTREE"]

        if not entrees_noms:
            print("[ERREUR] Aucun point d'entrée défini!")
            self.running = False
            return

        entree_nom = entrees_noms[0]

        profil_defaut = [
            [0.0,  0.1], [6.0,  0.3], [7.0,  0.8], [8.0,  1.5], [9.0,  1.8],
            [10.0, 1.4], [11.0, 1.1], [12.0, 0.6], [13.0, 0.7], [14.0, 1.2],
            [15.0, 1.0], [16.0, 0.7], [17.0, 0.4], [18.0, 0.2], [20.0, 0.1], [24.0, 0.1],
        ]

        def lire_entree():
            """Relit la config ENTREE depuis le dict en mémoire à chaque appel."""
            return self.config_manager.get_machines().get(entree_nom, {})

        def facteur_horaire(t_simpy, profil, heure_debut):
            """Retourne le facteur de fréquence pour le temps SimPy t (en minutes)."""
            heure_actuelle = (heure_debut + t_simpy / 60.0) % 24.0
            for i in range(len(profil) - 1):
                h0, f0 = profil[i]
                h1, f1 = profil[i + 1]
                if h0 <= heure_actuelle < h1:
                    alpha = (heure_actuelle - h0) / (h1 - h0)
                    return max(0.05, f0 + alpha * (f1 - f0))
            return profil[-1][1]

        def prochaine_interarrivee():
            """Tire un inter-arrivée Gamma modulé par le profil horaire.
            Relit la config à chaque appel — reflète immédiatement tout changement.
            """
            entree_live = lire_entree()
            freq_base   = entree_live.get("frequence", 5)
            gamma_k     = entree_live.get("gamma_k", 2.0)
            heure_debut = entree_live.get("heure_debut", 7.0)
            profil      = sorted(entree_live.get("profil_horaire", profil_defaut),
                                 key=lambda p: p[0])
            facteur      = facteur_horaire(self.env.now, profil, heure_debut)
            freq_modulee = max(0.5, freq_base / facteur)
            theta        = freq_modulee / gamma_k
            return random.gammavariate(gamma_k, theta)

        # Planifier la première arrivée
        self.prochaine_arrivee = self.env.now + prochaine_interarrivee()

        while self.running:
            if self.env.now >= self.prochaine_arrivee:
                if not self.types_tubes:
                    yield self.env.timeout(1)
                    continue

                entree = lire_entree()
                nom_type = random.choice(list(self.types_tubes.keys()))
                conf = self.types_tubes[nom_type]

                # Taille du lot : uniforme entre lot_min et lot_max
                lot_min  = int(conf.get("taille_lot_min", 1))
                lot_max  = int(conf.get("taille_lot_max", 1))
                nb_tubes = random.randint(lot_min, max(lot_min, lot_max))

                tx, ty = entree.get("coords", {}).get("x", 0), entree.get("coords", {}).get("y", 0)
                pct_mauvais = entree.get("pct_mauvais_prelevements", 0.0)

                for _ in range(nb_tubes):
                    _dv_min = int(conf.get("duree_validite_min", 0))
                    _dv_max = int(conf.get("duree_validite_max", _dv_min))
                    _dv = random.randint(_dv_min, max(_dv_min, _dv_max)) if _dv_min > 0 else 0
                    tube = {
                        "type":           nom_type,
                        "workflow":       list(conf.get("workflow", [])),
                        "couleur":        conf.get("couleur", "#3498db"),
                        "arrivee":        self.env.now,
                        "t_generation":   self.env.now,
                        "deadline":       self.env.now + _dv if _dv > 0 else 0,
                        "urgent":         random.random() < conf.get("pct_urgent", 0.0),
                        "duree_validite": _dv,
                    }

                    if not self.headless:
                        outline_color = "#e74c3c" if tube["urgent"] else "white"
                        outline_w = 2 if tube["urgent"] else 1
                        # Léger décalage aléatoire pour que les tubes d'un lot
                        # ne se superposent pas exactement sur le canvas
                        ox = random.randint(-8, 8)
                        oy = random.randint(-8, 8)
                        tube["id"] = self.canvas.create_oval(
                            tx+ox-6, ty+oy-6, tx+ox+6, ty+oy+6,
                            fill=conf["couleur"],
                            outline=outline_color, width=outline_w)
                    else:
                        tube["id"] = None

                    # Vérifier mauvais prélèvement à l'arrivée
                    if pct_mauvais > 0.0 and random.random() < pct_mauvais:
                        self.tubes_rejetes += 1
                        if not self.headless and tube.get("id") and self.canvas.winfo_exists():
                            self.canvas.itemconfig(tube["id"], fill="#7f8c8d",
                                                   outline="#e74c3c", width=2)
                            tid = tube["id"]
                            self.canvas.after(500,
                                lambda t=tid: self.canvas.delete(t)
                                if self.canvas.winfo_exists() else None)
                    else:
                        if tube["urgent"]:
                            self.entry_queue.insert(0, tube)
                        else:
                            self.entry_queue.append(tube)
                        # Compter l'arrivée dans le créneau horaire (heure de la journée, 0-23)
                        heure_abs = int((self.env.now / 60 + self.heure_debut_sim)) % 24
                        aph = self.stats_history["arrivees_par_heure"]
                        aph[heure_abs] = aph.get(heure_abs, 0) + 1
                        aphs = self.stats_history["arrivees_par_heure_par_service"]
                        if heure_abs not in aphs:
                            aphs[heure_abs] = {}
                        aphs[heure_abs][nom_type] = aphs[heure_abs].get(nom_type, 0) + 1
                    self.stats_tubes_total += 1

                self.prochaine_arrivee = self.env.now + prochaine_interarrivee()

            yield self.env.timeout(0.5)
