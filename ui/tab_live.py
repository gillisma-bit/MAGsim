import tkinter as tk
from tkinter import ttk
import simpy
import math
import random
import heapq
import bisect
from core.technician import TechnicianState
from core.stats_aggregator import StatsAggregator
from core.coordinateur_stress import CoordonnateurStress
import ui.theme as theme
import ui.theme as theme


def _score_priorite(tube, now, mult_urgence=1.0, mult_validite=1.0, mult_age=1.0):
    """Score de priorité d'un tube : plus élevé = traiter EN PREMIER.

    Trois composantes additives avec multiplicateurs de stress (injectés par
    le CoordonnateurStress selon la zone STABLE/VIGILANCE/CRITIQUE) :
    1. Urgence (flag booléen)         → +1 000 000 fixe (flag absolu, mu n'amplifie pas)
    2. % de validité consommée (0–1)  → ×    1 000 × mult_validite  (levier IA principal)
    3. Ancienneté brute (minutes)     → ×        1 × mult_age  (tiebreaker)

    mult_urgence sert uniquement à amplifier le score INTRA-URGENTS : un tube
    urgent reste toujours devant un tube non-urgent, mais parmi les urgents
    l'ordre dépend du reste du score × mult_urgence.
    """
    age      = now - tube.get("arrivee", now)
    validite = tube.get("duree_validite", 0)
    pct      = (age / validite) if validite > 0 else 0.0
    # Urgents : flag absolu 1_000_000 + score intra-urgents amplifié par mult_urgence
    # Non-urgents : score validité + ancienneté seulement
    if tube.get("urgent"):
        return (1_000_000.0
                + (pct * 1_000.0 * mult_validite + age * mult_age) * mult_urgence)
    else:
        return pct * 1_000.0 * mult_validite + age * mult_age


def _inserer_par_priorite(queue, tube, now, mult_urgence=1.0, mult_validite=1.0, mult_age=1.0):
    """Insère `tube` dans `queue` en ordre décroissant de _score_priorite."""
    score     = _score_priorite(tube, now, mult_urgence, mult_validite, mult_age)
    neg_scores = [-_score_priorite(t, now, mult_urgence, mult_validite, mult_age) for t in queue]
    pos = bisect.bisect_right(neg_scores, -score)
    queue.insert(pos, tube)


def _trier_queue_par_priorite(queue, now, mult_urgence=1.0, mult_validite=1.0, mult_age=1.0):
    """Trie une file en place : score décroissant (plus urgent/vieux en tête)."""
    queue.sort(key=lambda t: -_score_priorite(t, now, mult_urgence, mult_validite, mult_age))


def _inserer_par_anciennete(queue, tube, now=None, mult_urgence=1.0, mult_validite=1.0, mult_age=1.0):
    """Insère `tube` dans `queue` par priorité composite (urgence + validité + ancienneté)."""
    if now is not None:
        _inserer_par_priorite(queue, tube, now, mult_urgence, mult_validite, mult_age)
        return
    # Fallback sans `now` : urgents devant, puis FIFO par arrivée
    if tube.get("urgent"):
        queue.insert(0, tube)
        return
    nb_urgents = sum(1 for t in queue if t.get("urgent"))
    arrivees_normaux = [t.get("arrivee", 0) for t in queue[nb_urgents:]]
    pos = bisect.bisect_left(arrivees_normaux, tube.get("arrivee", 0))
    queue.insert(nb_urgents + pos, tube)


class TabLive:
    def __init__(self, parent, config_manager):
        self.parent = parent
        self.config_manager = config_manager
        self.env = None
        self.running = False
        self.technicians = []  # Liste des TechnicianState actifs (un par TECH_OFFICE)

        # Indicateurs visuels de machines en travail
        self.machine_indicators = {}   # nom_machine -> id canvas du point
        self.blinking_machines = set() # noms des machines en cours de clignotement
        
        # Types de tubes — chargés depuis le JSON au démarrage de la simulation
        self.types_tubes = {}
        self.prochaine_arrivee = 0

        # Nouvelles structures pour les queues
        self.machine_queues = {}
        self.output_queues = {}  # Tubes traités prêts pour l'étape suivante
        self.entry_queue = []
        self.machine_labels = {}        # nom -> label haut (entrée / total entrée)
        self.machine_labels_queue = {}  # nom -> label droite (file d'attente)
        self.machine_labels_output = {} # nom -> label gauche (traités prêts)
        self.mouvement_interrompu = False  # conservé pour compatibilité (unused en multi-tech)

        # Collecte des métriques pour l'onglet goulots
        self.stats_history = {"time": [], "queues": {}, "output": {}, "busy": {}, "entry": [],
                              "transit_time_avg": [], "transit_time_rolling": [],
                              "transit_time_pending_max": [],
                              "rejetes": [], "degrades": [], "pannes": {},
                              "distances_tech": {}, "bienetre": {},
                              "arrivees_par_heure": {},
                              "events_arret_maladie": [],
                              "stress_events": []}
        self.aggregator = StatsAggregator()
        self.coordinateur = CoordonnateurStress(intervalle_min=15)
        self.stats_tubes_total = 0
        self.tubes_sortis = 0  # Tubes ayant atteint la sortie
        self.transit_times_raw = []  # Durées de transit individuelles (arrivee → sortie)
        self.transit_times_urgents = []  # Idem pour les tubes urgents uniquement
        self.headless = False  # True = simulation accélérée sans animation (mode goulots)
        self.turbo = False  # True = 10 pas SimPy par tick (×10 vitesse)
        self._sol_cache = None  # Cache du sol grid, initialisé au lancement de la simulation
        self.heure_debut_sim = 7.0  # Heure de démarrage (lue depuis config ENTREE)
        self.panne_machines = set()     # noms des machines actuellement en panne
        self.paillasse_analyste = set()  # noms des Paillasses avec un tech actuellement à poste
        self.machine_repair_events = {}     # nom_machine -> simpy.Event déclenché quand réparé
        # ── Flag de test : désactiver les arrêts maladie ──────────────────────
        self.mode_sans_arret_maladie = False   # piloté par Menu Tests
        self.machine_rect_ids = {}      # nom_machine -> id canvas du rectangle
        self.tubes_rejetes = 0          # compteur cumulatif rejets (mauvais prélèv. + erreur tech)
        self.tubes_degrades = 0         # compteur cumulatif dégradés (délai ou panne machine)
        self.tubes_perimes = 0          # compteur cumulatif périmés (échantillon à refaire)
        # ── Navettes multi-source ─────────────────────────────────────────────
        self.navette_queues: dict = {}  # {fournisseur_id: [tubes en attente navette]}
        self.navette_stats:  dict = {}  # {fournisseur_id: {en_transit, total_envoye, en_queue}}
        # ── Réservation de slots machine ──────────────────────────────────────
        # Slots réservés par un tech en transit mais pas encore déposés.
        # Empêche un second tech de prendre la même place de file.
        self.machine_slots_reserved: dict = {}  # {nom_machine: nb_slots_réservés}
        # Interface canvas
        self.canvas = tk.Canvas(self.parent, bg="#ffffff", highlightthickness=0)
        
        # Ajouter barres de défilement
        self.scrollbar_x = ttk.Scrollbar(self.parent, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.scrollbar_y = ttk.Scrollbar(self.parent, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.scrollbar_x.set, yscrollcommand=self.scrollbar_y.set, scrollregion=(0, 0, 3000, 2000))
        
        self.scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(expand=True, fill="both")
        
        # Frame de contrôle
        self.info_frame = ttk.Frame(self.parent)
        self.info_frame.pack(fill="x", padx=10, pady=10)
        
        self.btn_start = ttk.Button(self.info_frame, text="▶ LANCER SIMULATION", command=self.toggle_sim)
        self.btn_start.pack(side=tk.LEFT, padx=5)

        self.btn_turbo = ttk.Button(self.info_frame, text="⚡ ×10", command=self.toggle_turbo, width=7)
        self.btn_turbo.pack(side=tk.LEFT, padx=5)

        # ── Toggle IA ──
        self._var_ia = tk.BooleanVar(value=False)
        self.btn_ia = ttk.Checkbutton(
            self.info_frame,
            text="🤖 IA (Qwen)",
            variable=self._var_ia,
            command=self._toggle_ia,
        )
        self.btn_ia.pack(side=tk.LEFT, padx=10)

        # Indicateur de zone stress (mis à jour par coordinateur_process)
        self.lbl_stress = ttk.Label(self.info_frame, text="⚪ Stress: —",
                                    font=theme.FONT_BODY, foreground="#7f8c8d")
        self.lbl_stress.pack(side=tk.LEFT, padx=10)

        self.lbl_queue = ttk.Label(self.info_frame, text="Tubes en attente : 0", 
                                   font=theme.FONT_LABEL, foreground="#e74c3c")
        self.lbl_queue.pack(side=tk.RIGHT, padx=20)

        self.lbl_heure = ttk.Label(self.info_frame, text="🕐 --:--",
                                   font=theme.FONT_LABEL, foreground="#2c3e50")
        self.lbl_heure.pack(side=tk.RIGHT, padx=20)

        self.lbl_erreurs = ttk.Label(self.info_frame, text="⚠ Rejets: 0 | Dégradés: 0",
                                     font=theme.FONT_BODY, foreground="#e67e22")
        self.lbl_erreurs.pack(side=tk.RIGHT, padx=15)

    def mettre_a_jour_compteur(self):
        """Met à jour l'affichage du nombre de tubes et de l'heure simulée"""
        if self.headless:
            return
        nb = len(self.entry_queue or [])
        self.lbl_queue.config(text=f"Tubes en attente : {nb}")
        self.lbl_erreurs.config(text=f"⚠ Rejets: {self.tubes_rejetes} | Dégradés: {self.tubes_degrades} | Périmés: {self.tubes_perimes}")
        if self.env:
            machines = self.config_manager.get_machines()
            entrees = [m for m in machines.values() if m["type"] == "ENTREE"]
            heure_debut = entrees[0].get("heure_debut", 7.0) if entrees else 7.0
            t_total = heure_debut * 60 + self.env.now  # en minutes
            h = int(t_total // 60) % 24
            m = int(t_total % 60)
            self.lbl_heure.config(text=f"🕐 {h:02d}:{m:02d}")

    def dessiner_labo_complet(self):
        """Redessine le labo avec sol et machines, sans superposer les labels."""
        self.canvas.delete("all")
        # Nettoyer les anciens labels et indicateurs
        self.machine_labels.clear()
        self.machine_labels_queue.clear()
        self.machine_labels_output.clear()
        self.machine_indicators.clear()
        self.blinking_machines.clear()
        self.machine_rect_ids.clear()
        self.panne_machines.clear()
        self.machine_repair_events.clear()
        
        # Sol
        sol = self.config_manager.data.get("sol", {})
        for cle, type_s in sol.items():
            try:
                c, r = map(int, cle.split("_"))
                color = "#ecf0f1" if type_s == "COUNTER" else "#2c3e50"
                self.canvas.create_rectangle(c*50, r*50, (c+1)*50, (r+1)*50, fill=color, outline="#d0d0d0")
            except:
                pass
        
        # Machines
        machines = self.config_manager.get_machines()
        for nom, m in machines.items():
            typ = m["type"]
            x, y = m["coords"]["x"], m["coords"]["y"]

            # ── TECH_OFFICE : invisible en simulation (géré via fenêtre RH) ──
            if typ == "TECH_OFFICE":
                continue

            # ── REPOS : simple repère visuel, sans labels machine ────────────
            if typ == "REPOS":
                self.canvas.create_oval(x-18, y-18, x+18, y+18,
                                        fill="#8e44ad", outline="#6c3483", width=2)
                self.canvas.create_text(x, y+26, text="Repos", font=theme.FONT_NOTE,
                                        fill="#8e44ad")
                continue

            if typ == "ENTREE":
                color = "#2ecc71"
            elif typ == "SORTIE":
                color = "#e74c3c"
            else:
                color = "#3498db"

            rect_id = self.canvas.create_rectangle(x-25, y-25, x+25, y+25,
                                                   fill=color, outline="black", width=2)
            if typ not in ("ENTREE", "SORTIE"):
                self.machine_rect_ids[nom] = rect_id
            self.canvas.create_text(x, y+30, text=nom, font=theme.FONT_NOTE)

            # Point indicateur (rouge = en travail) — masqué par défaut
            if typ not in ("ENTREE", "SORTIE"):
                ind_id = self.canvas.create_oval(x+15, y-25, x+25, y-15,
                                                 fill="", outline="", tags=f"ind_{nom}")
                self.machine_indicators[nom] = ind_id

            # --- Labels par machine (sauf SORTIE) ---
            if typ == "ENTREE":
                # ENTREE : un seul label haut (nb tubes en attente à l'entrée)
                self.canvas.create_rectangle(x-40, y-52, x+40, y-37, fill="white", outline="#27ae60", width=1)
                lbl = self.canvas.create_text(x, y-44, text=f"{nom}: 0",
                                              font=theme.FONT_NOTE, fill="#27ae60")
                self.machine_labels[nom] = lbl

            elif typ == "SORTIE":
                # Label SORTIE : compteur de tubes traités
                self.canvas.create_rectangle(x-40, y-52, x+40, y-37, fill="white", outline="#e74c3c", width=1)
                lbl_s = self.canvas.create_text(x, y-44, text="Sortis : 0",
                                                font=theme.FONT_NOTE, fill="#e74c3c")
                self.machine_labels[nom] = lbl_s

            else:
                # --- Label HAUT : tubes total entrés dans la machine ---
                self.canvas.create_rectangle(x-35, y-52, x+35, y-37,
                                             fill="white", outline="gray", width=1)
                lbl_top = self.canvas.create_text(x, y-44, text=f"{nom}",
                                                  font=theme.FONT_NOTE, fill="#2c3e50")
                self.machine_labels[nom] = lbl_top

                # --- Label DROITE : file d'attente (tubes déposés, pas encore traités) ---
                self.canvas.create_rectangle(x+28, y-12, x+70, y+12,
                                             fill="#fef9e7", outline="#e67e22", width=1)
                self.canvas.create_text(x+49, y-16, text="En attente",
                                        font=theme.FONT_NOTE, fill="#e67e22")
                lbl_q = self.canvas.create_text(x+49, y, text="0",
                                                font=theme.FONT_BODY, fill="#e67e22")
                self.machine_labels_queue[nom] = lbl_q

                # --- Label GAUCHE : tubes traités prêts à partir ---
                self.canvas.create_rectangle(x-70, y-12, x-28, y+12,
                                             fill="#eafaf1", outline="#27ae60", width=1)
                self.canvas.create_text(x-49, y-16, text="Prêts",
                                        font=theme.FONT_NOTE, fill="#27ae60")
                lbl_o = self.canvas.create_text(x-49, y, text="0",
                                                font=theme.FONT_BODY, fill="#27ae60")
                self.machine_labels_output[nom] = lbl_o

    def update_machine_labels(self):
        """Met à jour les 3 labels par machine (haut, droite, gauche)."""
        try:
            if self.headless or not self.running or not self.canvas or not self.canvas.winfo_exists():
                return
            machines = self.config_manager.get_machines()

            # --- Label haut : ENTREE ---
            for nom, lbl in self.machine_labels.items():
                m = machines.get(nom)
                if not m:
                    continue
                if m["type"] == "ENTREE":
                    self.canvas.itemconfig(lbl, text=f"{nom}: {len(self.entry_queue)}")
                elif m["type"] == "SORTIE":
                    self.canvas.itemconfig(lbl, text=f"Sortis : {self.tubes_sortis}")
                else:
                    # Affiche nom + état (Traitement... si en cours)
                    if nom in self.blinking_machines:
                        self.canvas.itemconfig(lbl, text=f"{nom} ⏳", fill="#e74c3c")
                    else:
                        self.canvas.itemconfig(lbl, text=nom, fill="#2c3e50")

            # --- Label droite : file d'attente (non encore traités) ---
            for nom, lbl in self.machine_labels_queue.items():
                n = len(self.machine_queues.get(nom, []))
                m = machines.get(nom, {})
                capacite = m.get("capacite", 4)
                file_max = m.get("file_max", capacite)
                color = "#e74c3c" if n >= file_max else ("#e67e22" if n > 0 else "#bdc3c7")
                self.canvas.itemconfig(lbl, text=str(n), fill=color)

            # --- Label gauche : tubes traités prêts à partir ---
            for nom, lbl in self.machine_labels_output.items():
                n = len(self.output_queues.get(nom, []))
                color = "#27ae60" if n > 0 else "#bdc3c7"
                self.canvas.itemconfig(lbl, text=str(n), fill=color)

            # Mise à jour visuelle de la fatigue pour tous les techniciens
            for tech in self.technicians:
                self._update_tech_sprite_fatigue(tech)

        except Exception as e:
            if self.running:
                print(f"[ERREUR UPDATE_LABELS] {e}")

    def est_libre(self, x, y):
        """Vérifie si une position est libre"""
        col, row = int(x // 50), int(y // 50)
        cle = f"{col}_{row}"
        if self._sol_cache is None:
            self._sol_cache = self.config_manager.data.get("sol", {})
        if cle in self._sol_cache and self._sol_cache[cle] in ("COUNTER", "WALL"):
            return False
        return True

    def lancer_simulation_headless(self, duree_sim, on_progress=None, on_complete=None, seed=None):
        """Lance une simulation accélérée (sans animation) dans un thread séparé.
        - duree_sim   : durée en unités SimPy
        - on_progress : callback(t, total) appelé toutes les 5 % de progression
        - on_complete : callback() appelé à la fin (depuis le thread — utiliser .after())
        - seed        : graine random optionnelle (reproductibilité / tests)
        """
        import threading

        def _run():
            try:
                if seed is not None:
                    random.seed(seed)
                self.headless = True
                self.running = True

                # Réinitialiser tout l'état
                self.entry_queue = []
                self.machine_queues = {}
                self.output_queues = {}
                self.technicians = []
                self.blinking_machines = set()
                self.machine_indicators = {}
                self.machine_labels = {}
                self.machine_labels_queue = {}
                self.machine_labels_output = {}
                self.stats_history = {"time": [], "queues": {}, "output": {}, "busy": {}, "entry": [],
                                      "transit_time_avg": [], "transit_time_rolling": [],
                                      "transit_time_pending_max": [],
                                      "rejetes": [], "degrades": [], "pannes": {},
                                      "distances_tech": {}, "bienetre": {},
                                      "arrivees_par_heure": {},
                                      "events_arret_maladie": [],
                                      "stress_events": []}
                self.aggregator = StatsAggregator()
                self.coordinateur.reset()
                if not self.headless and hasattr(self, 'lbl_stress'):
                    self.lbl_stress.config(text="⚪ Stress: —", foreground="#7f8c8d")
                self._jours_connus_dist = set()
                self.stats_tubes_total = 0
                self.tubes_sortis = 0
                self.transit_times_raw = []
                self.transit_times_urgents = []
                self.prochaine_arrivee = 0
                self.panne_machines = set()
                self.paillasse_analyste = set()
                self.machine_repair_events = {}
                self.tubes_rejetes = 0
                self.tubes_degrades = 0
                self.tubes_perimes = 0

                # Charger la config
                config_types = self.config_manager.data.get("types_tubes", {})
                if config_types:
                    self.types_tubes = config_types

                machines = self.config_manager.get_machines()
                # Charger heure_debut depuis la config ENTREE
                entrees_cfg = [m for m in machines.values() if m["type"] == "ENTREE"]
                self.heure_debut_sim = entrees_cfg[0].get("heure_debut", 7.0) if entrees_cfg else 7.0
                tech_offices = [(k, m) for k, m in machines.items() if m["type"] == "TECH_OFFICE"]
                if not tech_offices:
                    tech_offices = [("tech_0", {"coords": {"x": 125, "y": 125}})]
                for idx, (office_key, office) in enumerate(tech_offices):
                    tech = TechnicianState(
                        office["coords"]["x"], office["coords"]["y"],
                        canvas_id=None, index=idx)
                    tech.pct_erreur_base = office.get("pct_erreur_tech", 0.0)
                    tech.pct_erreur     = tech.pct_erreur_base
                    tech.nom            = office.get("nom") or office_key
                    tech.experience     = int(office.get("experience", 3))
                    tech.age            = int(office.get("age", 35))
                    tech.seuil_charge_fatigue  = float(office.get("seuil_charge_fatigue", 0.70))
                    tech.taux_montee_fatigue   = float(office.get("taux_montee_fatigue", 0.01))
                    tech.taux_recuperation_nuit = float(office.get("taux_recuperation_nuit", 0.15))
                    tech.capacite_max_tubes    = int(office.get("capacite_max_tubes", 10))
                    tech.office_x = office["coords"]["x"]
                    tech.office_y = office["coords"]["y"]
                    self.technicians.append(tech)

                # Créer l'environnement SimPy et lancer les processus
                self.env = simpy.Environment()
                self._sol_cache = self.config_manager.data.get("sol", {})  # cache sol
                self.navette_queues = {}
                self.navette_stats  = {}
                self.machine_slots_reserved = {}
                fournisseurs_cfg = self.config_manager.get_fournisseurs()
                fournisseurs_actifs = {
                    fid: f for fid, f in fournisseurs_cfg.items()
                    if f.get("actif", True)
                }
                if fournisseurs_actifs:
                    navette_conf = self.config_manager.get_navette_principale()
                    for fid, fconf in fournisseurs_actifs.items():
                        self.navette_queues[fid] = []
                        self.navette_stats[fid]  = {"en_transit": 0, "total_envoye": 0, "en_queue": 0}
                        self.env.process(self.tube_generation_fournisseur(fid, fconf))
                        self.env.process(self.navette_process(fid, fconf, navette_conf))
                else:
                    self.env.process(self.tube_generation())
                for t in self.technicians:
                    self.env.process(self.technician_process(t))
                self.env.process(self.stats_collector())
                self.env.process(self.coordinateur_process())
                for nom_m, m_conf in machines.items():
                    if m_conf.get("tmep") and m_conf.get("tmr"):
                        self.env.process(self.machine_breakdown_process(nom_m, m_conf))

                # Avancer par tranche de 5 % pour le retour de progression
                tranche = max(duree_sim / 20, 1)
                t = 0
                while t < duree_sim and self.running:
                    t_next = min(t + tranche, duree_sim)
                    self.env.run(until=t_next)
                    t = t_next
                    if on_progress:
                        on_progress(t, duree_sim)

            except Exception as e:
                print(f"[ERREUR HEADLESS] {e}")
                import traceback; traceback.print_exc()
            finally:
                self.running = False
                self.headless = False
                if on_complete:
                    on_complete()

        threading.Thread(target=_run, daemon=True).start()

    def toggle_sim(self):
        """Démarre ou arrête la simulation"""
        if not self.running:
            # DÉMARRAGE
            self.running = True
            self.btn_start.config(text="⏹ ARRÊTER SIMULATION")
            
            # Initialiser les queues AVANT de dessiner
            self.entry_queue = []
            self.machine_queues = {}
            self.output_queues = {}
            self.machine_labels = {}

            # Charger les types de tubes depuis la config JSON
            config_types = self.config_manager.data.get("types_tubes", {})
            if config_types:
                self.types_tubes = config_types

            # MAINTENANT dessiner le labo (qui va remplir machine_labels)
            self.dessiner_labo_complet()
            
            # Charger les machines depuis la config
            machines = self.config_manager.get_machines()

            # Créer un technicien par bureau TECH_OFFICE et dessiner leurs sprites
            self.technicians = []
            tech_offices = [(k, m) for k, m in machines.items() if m["type"] == "TECH_OFFICE"]
            if not tech_offices:
                tech_offices = [("tech_0", {"coords": {"x": 125, "y": 125}})]
            for idx, (office_key, office) in enumerate(tech_offices):
                office_x, office_y = office["coords"]["x"], office["coords"]["y"]
                # Chercher la première case libre autour du bureau
                spawn_x, spawn_y = office_x, office_y
                found_spawn = False
                for r in range(-2, 3):
                    for c in range(-2, 3):
                        tx = office_x + c * 50
                        ty = office_y + r * 50
                        if self.est_libre(tx, ty):
                            spawn_x, spawn_y = tx, ty
                            found_spawn = True
                            break
                    if found_spawn:
                        break
                tech = TechnicianState(spawn_x, spawn_y, index=idx)
                tech.pct_erreur_base = office.get("pct_erreur_tech", 0.0)
                tech.pct_erreur     = tech.pct_erreur_base
                tech.nom            = office.get("nom") or office_key
                tech.experience     = int(office.get("experience", 3))
                tech.age            = int(office.get("age", 35))
                tech.seuil_charge_fatigue  = float(office.get("seuil_charge_fatigue", 0.70))
                tech.taux_montee_fatigue   = float(office.get("taux_montee_fatigue", 0.01))
                tech.taux_recuperation_nuit = float(office.get("taux_recuperation_nuit", 0.15))
                tech.capacite_max_tubes    = int(office.get("capacite_max_tubes", 10))
                tech.office_x = office["coords"]["x"]
                tech.office_y = office["coords"]["y"]
                tech.canvas_id = self.canvas.create_oval(
                    tech.x-10, tech.y-10, tech.x+10, tech.y+10,
                    fill=tech.color, outline="black", width=2, tags="tech")
                # Emoji bien-être affiché au-dessus du sprite
                emoji_init, _, _ = tech.etat_bien_etre()
                tech.label_bienetre_id = self.canvas.create_text(
                    tech.x, tech.y - 18, text=emoji_init,
                    font=theme.FONT_BODY, tags="tech_bienetre")
                self.technicians.append(tech)
            self.canvas.update()
            
            # Démarrer SimPy
            self.env = simpy.Environment()
            self._sol_cache = self.config_manager.data.get("sol", {})  # cache invalide/rafraichi
            # Initialiser heure_debut_sim depuis la config ENTREE
            entrees_cfg = [m for m in machines.values() if m["type"] == "ENTREE"]
            self.heure_debut_sim = entrees_cfg[0].get("heure_debut", 7.0) if entrees_cfg else 7.0
            self.prochaine_arrivee = 0

            # Réinitialiser les statistiques
            self.stats_history = {"time": [], "queues": {}, "output": {}, "busy": {}, "entry": [],
                                  "bienetre": {},
                                  "transit_time_avg": [], "transit_time_rolling": [],
                                  "transit_time_pending_max": [],
                                  "rejetes": [], "degrades": [], "pannes": {},
                                  "distances_tech": {},
                                  "arrivees_par_heure": {},
                                  "events_arret_maladie": [],
                                  "stress_events": []}
            self.aggregator = StatsAggregator()
            self.coordinateur.reset()
            if not self.headless and hasattr(self, 'lbl_stress'):
                self.lbl_stress.config(text="⚪ Stress: —", foreground="#7f8c8d")
            self._jours_connus_dist = set()
            self.stats_tubes_total = 0
            self.tubes_sortis = 0
            self.transit_times_raw = []
            self.transit_times_urgents = []
            self.panne_machines = set()
            self.paillasse_analyste = set()
            self.machine_repair_events = {}
            self.tubes_rejetes = 0
            self.tubes_degrades = 0
            self.tubes_perimes = 0

            # Réinitialiser les navettes multi-source
            self.navette_queues = {}
            self.navette_stats  = {}
            self.machine_slots_reserved = {}

            self.mettre_a_jour_compteur()

            # ── Démarrage des générateurs de tubes ───────────────────────────
            fournisseurs_cfg = self.config_manager.get_fournisseurs()
            fournisseurs_actifs = {
                fid: f for fid, f in fournisseurs_cfg.items()
                if f.get("actif", True)
            }
            if fournisseurs_actifs:
                navette_conf = self.config_manager.get_navette_principale()
                for fid, fconf in fournisseurs_actifs.items():
                    self.navette_queues[fid] = []
                    self.navette_stats[fid]  = {"en_transit": 0, "total_envoye": 0, "en_queue": 0}
                    self.env.process(self.tube_generation_fournisseur(fid, fconf))
                    self.env.process(self.navette_process(fid, fconf, navette_conf))
            else:
                # Fallback : mode ENTREE unique (comportement historique)
                self.env.process(self.tube_generation())

            for t in self.technicians:
                self.env.process(self.technician_process(t))
            self.env.process(self.stats_collector())
            self.env.process(self.coordinateur_process())
            # Lancer un processus de panne indépendant pour chaque machine avec TMEP/TMR
            for nom_m, m_conf in machines.items():
                if m_conf.get("tmep") and m_conf.get("tmr"):
                    self.env.process(self.machine_breakdown_process(nom_m, m_conf))
            self.run_sim_loop()
        else:
            # ARRÊT
            self.running = False
            self.turbo = False
            self.btn_turbo.config(text="⚡ ×10")
            self.btn_start.config(text="▶ LANCER SIMULATION")
            for t in self.technicians:
                if t.canvas_id:
                    try:
                        self.canvas.delete(t.canvas_id)
                    except Exception:
                        pass
            self.technicians = []
            print("[INFO] Simulation arrêtée")

    def toggle_turbo(self):
        """Active/désactive l'accélération ×10"""
        self.turbo = not self.turbo
        if self.turbo:
            self.btn_turbo.config(text="⚡ ×10  ON", style="Accent.TButton" if "Accent.TButton" in ttk.Style().theme_names() else "TButton")
        else:
            self.btn_turbo.config(text="⚡ ×10")

    def _toggle_ia(self):
        """Active ou désactive le coordinateur IA (Qwen 2.5 32B via Ollama)."""
        actif = self._var_ia.get()
        self.coordinateur.ia_active = actif
        if actif:
            try:
                import ollama  # noqa: F401 — juste vérifier disponibilité
            except ImportError:
                import tkinter.messagebox as mb
                mb.showwarning(
                    "IA indisponible",
                    "Le paquet 'ollama' n'est pas installé.\n"
                    "Exécutez : pip install ollama",
                )
                self._var_ia.set(False)
                self.coordinateur.ia_active = False


    def run_sim_loop(self):
        """Boucle qui exécute la simulation par étapes"""
        if self.running and self.env:
            try:
                steps = 10 if self.turbo else 1
                for _ in range(steps):
                    self.env.step()
                self.mettre_a_jour_compteur()
                self.update_machine_labels()
                self.parent.after(50, self.run_sim_loop)
            except StopIteration:
                print("[INFO] Simulation terminée")
                self.running = False
                self.turbo = False
                self.btn_turbo.config(text="⚡ ×10")
                self.btn_start.config(text="▶ LANCER SIMULATION")
            except Exception as e:
                if self.running:
                    print(f"[ERREUR LOOP] {e}")
                    self.running = False

    def trouver_case_libre_proche(self, target_x, target_y, rayon=55, from_x=0, from_y=0):
        """Trouve la case libre adjacente (1 case max) la plus proche du technicien."""
        meilleure_pos = None
        meilleure_distance_totale = float('inf')
        
        # Chercher dans un rayon d'1 case autour de la cible (cases directement adjacentes)
        for x in range(int(target_x - rayon), int(target_x + rayon) + 1, 50):
            for y in range(int(target_y - rayon), int(target_y + rayon) + 1, 50):
                if self.est_libre(x, y):
                    # Distance depuis la position actuelle du tech
                    dist_depart = math.sqrt((x - from_x)**2 + (y - from_y)**2)
                    # Distance de la case à la cible (favoriser les cases les plus proches)
                    dist_arrivee = math.sqrt((x - target_x)**2 + (y - target_y)**2)
                    distance_totale = dist_depart + dist_arrivee * 2  # pénaliser l'éloignement de la cible
                    
                    if distance_totale < meilleure_distance_totale:
                        meilleure_distance_totale = distance_totale
                        meilleure_pos = (x, y)
        
        if meilleure_pos:
            return meilleure_pos
        else:
            # Fallback : retourner la cible même si pas libre
            return (target_x, target_y)
    
    def _blink_machine(self, nom_machine):
        """Fait clignoter le point rouge sur la machine tant qu'elle est dans blinking_machines."""
        if self.headless:
            return  # Pas d'animation en mode headless
        ind_id = self.machine_indicators.get(nom_machine)
        if not ind_id:
            return
        visible = True
        while nom_machine in self.blinking_machines and self.running:
            if self.canvas.winfo_exists():
                if visible:
                    self.canvas.itemconfig(ind_id, fill="#e74c3c", outline="#c0392b")
                else:
                    self.canvas.itemconfig(ind_id, fill="", outline="")
            visible = not visible
            yield self.env.timeout(0.5)
        # Éteindre le point à la fin
        if self.canvas.winfo_exists() and ind_id:
            self.canvas.itemconfig(ind_id, fill="", outline="")

    def trouver_chemin_astar(self, start_x, start_y, goal_x, goal_y):
        """Calcule un chemin A* en pixels en évitant COUNTER et WALL."""
        CELL = 50
        if self._sol_cache is None:
            self._sol_cache = self.config_manager.data.get("sol", {})
        sol = self._sol_cache

        def walkable(col, row):
            cle = f"{col}_{row}"
            return cle not in sol or sol[cle] not in ("COUNTER", "WALL")

        sc, sr = int(start_x // CELL), int(start_y // CELL)
        gc, gr = int(goal_x // CELL), int(goal_y // CELL)

        # Si la cellule de départ est bloquée, chercher la plus proche libre
        if not walkable(sc, sr):
            for dr in range(-3, 4):
                for dc in range(-3, 4):
                    if walkable(sc + dc, sr + dr):
                        sc, sr = sc + dc, sr + dr
                        break
                else:
                    continue
                break

        # Si départ == arrivée, on est déjà là
        if sc == gc and sr == gr:
            return []

        SQRT2 = math.sqrt(2)

        def h(c, r):
            # Heuristique octile — admissible avec déplacement diagonal coût √2
            dx, dy = abs(c - gc), abs(r - gr)
            return max(dx, dy) + (SQRT2 - 1) * min(dx, dy)

        # (f, g, col, row, chemin)
        open_set = [(h(sc, sr), 0, sc, sr, [(sc, sr)])]
        visited = set()

        while open_set:
            f, g, col, row, path = heapq.heappop(open_set)
            if (col, row) in visited:
                continue
            visited.add((col, row))

            if col == gc and row == gr:
                # Convertir en coordonnées pixels (centre de chaque cellule), sans inclure le départ
                return [(c * CELL + CELL // 2, r * CELL + CELL // 2) for c, r in path[1:]]

            for dc, dr in [(0, 1), (0, -1), (1, 0), (-1, 0),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)]:
                nc, nr = col + dc, row + dr
                if (nc, nr) in visited or not walkable(nc, nr):
                    continue
                # Empêcher le coupage de coins : les deux cases adjacentes doivent être libres
                if dc != 0 and dr != 0:
                    if not walkable(col + dc, row) or not walkable(col, row + dr):
                        continue
                ng = g + (SQRT2 if dc != 0 and dr != 0 else 1)
                heapq.heappush(open_set, (ng + h(nc, nr), ng, nc, nr, path + [(nc, nr)]))

        # Aucun chemin trouvé — aller directement
        return [(goal_x, goal_y)]

    def deplacer_vers(self, tech, target_x, target_y, interruptible=False):
        """Déplace le technicien `tech` vers une destination en suivant un chemin A*.
        Si interruptible=True, stoppe le mouvement dès qu'une output_queue n'est plus vide
        et positionne tech.mouvement_interrompu = True.
        """
        tech.mouvement_interrompu = False
        vitesse = tech.calculer_vitesse(self.env.now, self.heure_debut_sim)
        tolerance = 10

        chemin = self.trouver_chemin_astar(tech.x, tech.y, target_x, target_y)
        if not chemin:
            return  # Déjà à destination

        if self.headless:
            # Mode accéléré : calculer le temps de trajet en une seule fois, sans boucle pixel
            path_len = math.sqrt((chemin[0][0]-tech.x)**2 + (chemin[0][1]-tech.y)**2)
            for i in range(1, len(chemin)):
                path_len += math.sqrt((chemin[i][0]-chemin[i-1][0])**2 + (chemin[i][1]-chemin[i-1][1])**2)
            tech.distance_parcourue_px += path_len
            temps_trajet = max(path_len / vitesse * 0.05, 0.001)
            yield self.env.timeout(temps_trajet)
            tech.x, tech.y = target_x, target_y
            return

        for wp_x, wp_y in chemin:
            vitesse = tech.calculer_vitesse(self.env.now, self.heure_debut_sim)  # recalcul par waypoint
            while self.running:
                dx = wp_x - tech.x
                dy = wp_y - tech.y
                dist = math.sqrt(dx**2 + dy**2)

                if dist < tolerance:
                    tech.x = wp_x
                    tech.y = wp_y
                    # Vérifier la priorité à chaque waypoint (pas en plein mouvement)
                    if interruptible and any(self.output_queues.get(n) for n in self.output_queues):
                        tech.mouvement_interrompu = True
                        return
                    break

                step_x = (dx / dist) * vitesse
                step_y = (dy / dist) * vitesse
                pas = min(vitesse, dist)
                tech.distance_parcourue_px += pas
                tech.x += step_x
                tech.y += step_y

                if self.canvas.winfo_exists() and tech.canvas_id:
                    self.canvas.coords(tech.canvas_id,
                                      tech.x-10, tech.y-10,
                                      tech.x+10, tech.y+10)
                    if tech.label_bienetre_id:
                        self.canvas.coords(tech.label_bienetre_id, tech.x, tech.y - 18)
                    for tube in tech.carried_tubes:
                        if tube.get("id"):
                            self.canvas.coords(tube["id"],
                                              tech.x-6, tech.y-6,
                                              tech.x+6, tech.y+6)

                yield self.env.timeout(0.05)

        # Ajuster la position finale exacte (uniquement si non interrompu)
        if not tech.mouvement_interrompu:
            tech.x = target_x
            tech.y = target_y
            if self.canvas.winfo_exists() and tech.canvas_id:
                self.canvas.coords(tech.canvas_id,
                                  tech.x-10, tech.y-10,
                                  tech.x+10, tech.y+10)
                if tech.label_bienetre_id:
                    self.canvas.coords(tech.label_bienetre_id, tech.x, tech.y - 18)
                for tube in tech.carried_tubes:
                    if tube.get("id"):
                        self.canvas.coords(tube["id"],
                                          tech.x-6, tech.y-6,
                                          tech.x+6, tech.y+6)

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

        for tube in list(self.entry_queue):
            dv = tube.get("duree_validite", 0)
            if dv <= 0:
                continue
            if tube.get("perime"):
                continue
            age = t - tube.get("arrivee", t)
            ratio = age / dv

            if ratio >= n2_seuil and not tube.get("urgent"):
                tube["urgent"] = True
                tube["escalade"] = 2
                self.entry_queue.remove(tube)
                self.entry_queue.insert(0, tube)
                escalades += 1
                if not self.headless and tube.get("id") and self.canvas.winfo_exists():
                    self.canvas.itemconfig(tube["id"],
                                          fill="#e74c3c", outline="#c0392b", width=3)
            elif ratio >= n1_seuil and not tube.get("urgent") and not tube.get("escalade"):
                tube["urgent"] = True
                tube["escalade"] = 1
                self.entry_queue.remove(tube)
                self.entry_queue.insert(0, tube)
                escalades += 1
                if not self.headless and tube.get("id") and self.canvas.winfo_exists():
                    self.canvas.itemconfig(tube["id"],
                                          fill="#e67e22", outline="#d35400", width=2)

        # Escalade dans les files machine : visuel uniquement (pas de réordonnancement)
        for q in self.machine_queues.values():
            for tube in q:
                dv = tube.get("duree_validite", 0)
                if dv <= 0 or tube.get("perime"):
                    continue
                age = t - tube.get("arrivee", t)
                ratio = age / dv
                if ratio >= n2_seuil and not tube.get("escalade"):
                    tube["escalade"] = 2
                    if not self.headless and tube.get("id") and self.canvas.winfo_exists():
                        self.canvas.itemconfig(tube["id"],
                                              fill="#e74c3c", outline="#c0392b", width=3)
                elif ratio >= n1_seuil and not tube.get("escalade"):
                    tube["escalade"] = 1
                    if not self.headless and tube.get("id") and self.canvas.winfo_exists():
                        self.canvas.itemconfig(tube["id"],
                                              fill="#e67e22", outline="#d35400", width=2)

        if escalades:
            self.stats_history.setdefault("escalades_count", [])
            self.stats_history["escalades_count"].append((t, escalades))

    def stats_collector(self):
        """Échantillonne l'état des files toutes les 2 unités de simulation pour les graphiques goulots."""
        interval = 2.0
        while self.running:
            t = self.env.now
            self.stats_history["time"].append(t)

            # File d'entrée
            self.stats_history["entry"].append(len(self.entry_queue))

            machines = self.config_manager.get_machines()
            for nom, m in machines.items():
                if m["type"] in ("ENTREE", "SORTIE", "TECH_OFFICE", "REPOS"):
                    continue
                if nom not in self.stats_history["queues"]:
                    self.stats_history["queues"][nom] = []
                self.stats_history["queues"][nom].append(len(self.machine_queues.get(nom, [])))

                # File de sortie
                if nom not in self.stats_history["output"]:
                    self.stats_history["output"][nom] = []
                self.stats_history["output"][nom].append(len(self.output_queues.get(nom, [])))

                # Occupation (1 = en traitement, 0 = libre)
                if nom not in self.stats_history["busy"]:
                    self.stats_history["busy"][nom] = []
                self.stats_history["busy"][nom].append(1 if nom in self.blinking_machines else 0)

            # Temps de transit : moyenne cumulative + moyenne glissante (20 derniers tubes)
            if self.transit_times_raw:
                avg_transit = sum(self.transit_times_raw) / len(self.transit_times_raw)
                window = self.transit_times_raw[-20:]
                rolling_transit = sum(window) / len(window)
            else:
                avg_transit = None    # None = pas encore de données (pas de 0 trompeur)
                rolling_transit = None
            self.stats_history["transit_time_avg"].append(avg_transit)
            self.stats_history["transit_time_rolling"].append(rolling_transit)
            # Snapshot des durées brutes pour min/max/p95 (liste complète, mise à jour)
            self.stats_history["transit_times_raw"] = list(self.transit_times_raw)

            # Âge du plus vieux tube encore en attente dans le système
            # (entrée + files machine + sorties de machine non encore récupérées)
            # → monte pendant un blocage même si aucun tube ne sort
            all_pending = list(self.entry_queue)
            for _q in self.machine_queues.values():
                all_pending.extend(_q)
            for _q in self.output_queues.values():
                all_pending.extend(_q)
            ages_en_attente = [t - tube["arrivee"] for tube in all_pending if "arrivee" in tube]
            pending_max = max(ages_en_attente) if ages_en_attente else None
            self.stats_history["transit_time_pending_max"].append(pending_max)

            # Compteurs d'erreurs (valeurs cumulatives, parallèles à "time")
            self.stats_history["rejetes"].append(self.tubes_rejetes)
            self.stats_history["degrades"].append(self.tubes_degrades)

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
                        # Mécontentement : comparaison tubes livrés hier vs capacité normale
                        tubes_jour = tech.tubes_livres_session - tech._tubes_livres_debut_jour
                        tech.mettre_a_jour_mecontentement(tubes_jour, cap_jour)
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
                            # Vérifier si hier était un jour de repos planifié
                            tech_horaire = horaires_cfg.get(tech.nom, {})
                            jours_travail = tech_horaire.get("jours", list(range(7)))
                            est_conge = jour_hier_semaine not in jours_travail
                            if est_conge:
                                tech.jours_conges_consecutifs += 1
                                # Bonus à partir du 2e jour de repos consécutif (ex: week-end)
                                if tech.jours_conges_consecutifs >= 2:
                                    bonus = 0.08 + (tech.jours_conges_consecutifs - 2) * 0.03
                                    tech.mecontentement = max(0.0, tech.mecontentement - bonus)
                                    tech.fatigue_courante = max(0.0, tech.fatigue_courante - 0.15)
                            else:
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

            # ── Péremption des tubes ─────────────────────────────────────────────────────
            # Un tube est périmé si sa durée de validité est dépassée depuis son arrivée.
            # Il est retiré de toutes les files et compté comme "dégradé" (prélèvement à refaire).
            perimes = [
                tube for tube in all_pending
                if tube.get("duree_validite", 0) > 0
                and (t - tube.get("arrivee", t)) > tube.get("duree_validite", 0)
                and not tube.get("perime")
            ]
            for tube in perimes:
                tube["perime"] = True
                if tube in self.entry_queue:
                    self.entry_queue.remove(tube)
                for _q in self.machine_queues.values():
                    try:
                        _q.remove(tube)
                    except ValueError:
                        pass
                for _q in self.output_queues.values():
                    try:
                        _q.remove(tube)
                    except ValueError:
                        pass
                self.tubes_perimes += 1
                self.tubes_degrades += 1
                if not self.headless and tube.get("id") and self.canvas.winfo_exists():
                    self.canvas.itemconfig(tube["id"], fill="#bdc3c7", outline="#e74c3c", width=2)
                    tid = tube["id"]
                    self.canvas.after(800,
                        lambda _t=tid: self.canvas.delete(_t) if self.canvas.winfo_exists() else None)

            # ── Watchdog : forcer un batch si un tube est bloqué trop longtemps ──
            # Cas typique : arrivées lentes → capacite jamais atteinte → machine jamais déclenchée.
            # Paramètre JSON par machine : "timeout_batch" (minutes, défaut 60).
            for nom_wm, conf_wm in machines.items():
                if conf_wm.get("type") in ("ENTREE", "SORTIE", "TECH_OFFICE", "REPOS"):
                    continue
                q_wm = self.machine_queues.get(nom_wm, [])
                if q_wm and nom_wm not in self.blinking_machines:
                    oldest_age = t - q_wm[0].get("arrivee", t)
                    timeout_batch = conf_wm.get("timeout_batch", 60)
                    if oldest_age > timeout_batch:
                        # Les machines à opérateur requis ne démarrent que si un tech est au poste
                        tech_present = not conf_wm.get("tech_requis_poste", False) or nom_wm in self.paillasse_analyste
                        if tech_present:
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

            # ── Appel IA si zone VIGILANCE (pic imminent) ou CRITIQUE ────────────
            if snap.zone in ("VIGILANCE", "CRITIQUE") and self.coordinateur.ia_active:
                nb_actifs = sum(1 for t in self.technicians
                                if not t.en_arret_maladie and t.en_service)
                nb_pannes = len(self.panne_machines)
                reponse = self.coordinateur.consulter_ia(
                    snap, nb_actifs, nb_pannes, headless=self.headless)
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


    def tube_generation_fournisseur(self, fid: str, fconf: dict):
        """Génère des tubes pour un fournisseur et les place dans sa file navette.

        Paramètres lus depuis fconf à chaque tirage (modifications en live).
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

        while self.running:
            # Tirer l'inter-arrivée
            freq_base = float(fconf.get("frequence_base", 30))
            gamma_k   = float(fconf.get("gamma_k", 2.0))
            facteur   = _facteur(self.env.now)
            freq_mod  = max(0.5, freq_base / facteur)
            theta     = freq_mod / gamma_k
            inter     = random.gammavariate(gamma_k, theta)
            yield self.env.timeout(inter)

            if not self.types_tubes or not fconf.get("actif", True):
                continue

            # Choisir le type de tube parmi ceux que ce fournisseur émet
            types_emis  = fconf.get("types_tubes_emis", list(self.types_tubes.keys()))
            types_valides = [t for t in types_emis if t in self.types_tubes]
            if not types_valides:
                types_valides = list(self.types_tubes.keys())
            if not types_valides:
                continue

            nom_type = random.choice(types_valides)
            conf     = self.types_tubes[nom_type]

            _dv_min = int(conf.get("duree_validite_min", 0))
            _dv_max = int(conf.get("duree_validite_max", _dv_min))
            _dv     = random.randint(_dv_min, max(_dv_min, _dv_max)) if _dv_min > 0 else 0

            tube = {
                "type":           nom_type,
                "workflow":       list(conf.get("workflow", [])),
                "couleur":        conf.get("couleur", "#3498db"),
                "arrivee":        self.env.now,   # mis à jour à la livraison navette
                "t_generation":   self.env.now,
                "urgent":         random.random() < float(fconf.get("pct_urgent", 0.05)),
                "duree_validite": _dv,
                "fournisseur":    fid,
                "id":             None,
            }

            # Déposer dans la file navette
            if fid not in self.navette_queues:
                self.navette_queues[fid] = []
            self.navette_queues[fid].append(tube)
            self.navette_stats[fid]["en_queue"] = len(self.navette_queues[fid])
            self.stats_tubes_total += 1

    def navette_process(self, fid: str, fconf: dict, navette_conf: dict):
        """Gère les départs et le transit de la navette pour un fournisseur.

        Modes de départ :
          horaire  → part toutes les ``frequence_depart_min`` minutes sim
          pleine   → part quand la queue atteint ``capacite_max``
          hybride  → horaire OU dès qu'un urgent arrive (si priorite_urgents)
        """
        while self.running:
            mode     = navette_conf.get("mode_depart", "hybride")
            freq_dep = float(navette_conf.get("frequence_depart_min", 30))
            cap      = int(navette_conf.get("capacite_max", 20))
            priorite = navette_conf.get("priorite_urgents", True)
            trajet   = float(fconf.get("duree_trajet_min", 10.0))

            queue = self.navette_queues.get(fid, [])

            if mode == "horaire":
                yield self.env.timeout(freq_dep)

            elif mode == "pleine":
                t_max = self.env.now + freq_dep * 3
                while len(queue) < cap and self.env.now < t_max and self.running:
                    yield self.env.timeout(1)

            else:  # hybride (défaut)
                t_depart = self.env.now + freq_dep
                while self.env.now < t_depart and self.running:
                    if priorite and any(t.get("urgent") for t in queue):
                        break
                    yield self.env.timeout(1)

            # Prendre jusqu'à cap tubes de la file
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
            self.navette_stats[fid] = stats

            # Transit (délai de transport)
            yield self.env.timeout(trajet)

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
                heure_abs = int((now / 60 + self.heure_debut_sim)) % 24
                aph       = self.stats_history["arrivees_par_heure"]
                aph[heure_abs] = aph.get(heure_abs, 0) + 1

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
                    self.stats_tubes_total += 1

                self.prochaine_arrivee = self.env.now + prochaine_interarrivee()

            yield self.env.timeout(0.5)

    # ──────────────────────────────────────────────────────────────────────
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
                temps_sur_place = self.env.now - getattr(tech, '_garde_arrivee', self.env.now)
                has_urgent = any(t.get("urgent") for t in self.entry_queue)
                if temps_sur_place >= forfait_min and not has_urgent:
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
            # Les tubes restent dans output_queues (boîtes vertes visibles) jusqu'à
            # l'arrivée physique du tech. On évite le double-claim en ignorant les tubes
            # déjà portés par un autre technicien.
            deja_portes = {id(t) for other in self.technicians if other is not tech
                           for t in other.carried_tubes}

            tubes_finis = []
            noms_a_vider = []
            for nom_m in list(self.output_queues.keys()):
                disponibles = [t for t in self.output_queues[nom_m]
                               if id(t) not in deja_portes]
                if disponibles:
                    tubes_finis.extend(disponibles)
                    noms_a_vider.append(nom_m)

            if tubes_finis:
                # Trier par ancienneté : les tubes les plus vieux livrés en premier
                tubes_finis.sort(key=lambda t: t.get("arrivee", 0))
                # Claim : assigner les tubes AU TECH dès maintenant, mais les laisser dans
                # output_queues pour que les boîtes vertes restent visibles pendant le trajet
                tech.carried_tubes = tubes_finis

                # Se rendre près du premier tube fini (il est à sa machine source)
                if not self.headless:
                    premier = tubes_finis[0]
                    if premier.get("id") and self.canvas.winfo_exists():
                        coords = self.canvas.coords(premier["id"])
                        if coords:
                            tx = (coords[0] + coords[2]) / 2
                            ty = (coords[1] + coords[3]) / 2
                            libre_x, libre_y = self.trouver_case_libre_proche(tx, ty, from_x=tech.x, from_y=tech.y)
                            yield self.env.process(self.deplacer_vers(tech, libre_x, libre_y))
                else:
                    # Headless : se déplacer vers la machine source via ses coordonnées
                    if noms_a_vider:
                        m_src = machines.get(noms_a_vider[0])
                        if m_src:
                            libre_x, libre_y = self.trouver_case_libre_proche(
                                m_src["coords"]["x"], m_src["coords"]["y"], from_x=tech.x, from_y=tech.y)
                            yield self.env.process(self.deplacer_vers(tech, libre_x, libre_y))

                # Le tech est maintenant à la machine : retirer les tubes qu'il emporte
                tubes_finis_set = set(id(t) for t in tubes_finis)
                for nom_m in noms_a_vider:
                    self.output_queues[nom_m] = [t for t in self.output_queues[nom_m]
                                                 if id(t) not in tubes_finis_set]

                if not self.headless:
                    for tube in tech.carried_tubes:
                        if self.canvas.winfo_exists() and tube.get("id"):
                            self.canvas.coords(tube["id"],
                                              tech.x-6, tech.y-6,
                                              tech.x+6, tech.y+6)

                yield self.env.process(self._livrer_tubes(tech, tech.carried_tubes, machines, sorties))
                tech.carried_tubes = []
                continue

            # --- Priorité 2 : nouveau(x) tube(s) en attente à l'entrée ---
            if not self.entry_queue or not entrees:
                yield self.env.timeout(0.5)
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
                    self.canvas.coords(tube["id"],
                                      tech.x-6, tech.y-6,
                                      tech.x+6, tech.y+6)

            yield self.env.process(self._livrer_tubes(tech, tech.carried_tubes, machines, sorties))
            tech.carried_tubes = []

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
                    if should_trigger and nom_machine not in self.blinking_machines:
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

                            # Rester en poste tant que la file ou la machine sont actives.
                            # Si le quart se termine, on abandonne le poste (les tubes
                            # restants seront traités par le prochain tech qui déposera).
                            while (self.machine_queues.get(nom_machine)
                                   or nom_machine in self.blinking_machines):
                                yield self.env.timeout(temps_analyse / 10)
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
                        tat = now - tube["arrivee"]
                        self.transit_times_raw.append(tat)
                        if tube.get("urgent"):
                            self.transit_times_urgents.append(tat)
                # Retirer + supprimer APRÈS l'arrivée
                self.tubes_sortis += len(vers_sortie)
                _vs_ids = {id(t) for t in vers_sortie}
                # Libérer les réservations des tubes sortis (workflow vide, aucune machine réservée
                # en principe, mais on nettoie par sécurité)
                self._liberer_reservations(vers_sortie)
                tech.carried_tubes = [t for t in tech.carried_tubes if id(t) not in _vs_ids]
                if not self.headless:
                    for tube in vers_sortie:
                        if self.canvas.winfo_exists() and tube.get("id"):
                            self.canvas.delete(tube["id"])

            # Si certains tubes n'ont pas pu être déposés (file pleine), attendre et réessayer
            if tubes_reportes:
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

    def machine_breakdown_process(self, nom_machine, machine):
        """Processus indépendant modélisant les pannes par loi exponentielle (TMEP/TMR).

        TMEP (Temps Moyen Entre Pannes) et TMR (Temps Moyen de Réparation) sont en HEURES.
        Taux de disponibilité théorique : A = TMEP / (TMEP + TMR).
        Les valeurs sont converties en minutes (×60) pour SimPy (1 unité = 1 min).
        """
        tmep = machine.get("tmep", 0)
        tmr  = machine.get("tmr",  0)
        if not tmep or not tmr or tmep <= 0 or tmr <= 0:
            return

        # Conversion heures → minutes SimPy
        tmep_min = tmep * 60
        tmr_min  = tmr  * 60

        while self.running:
            # Attendre le prochain incident (distribution exponentielle)
            delai_avant_panne = random.expovariate(1.0 / tmep_min)
            yield self.env.timeout(delai_avant_panne)
            if not self.running:
                break

            # --- Déclenchement de la panne ---
            self.panne_machines.add(nom_machine)
            self.stats_history["pannes"].setdefault(nom_machine, []).append(self.env.now)

            repair_event = self.env.event()
            self.machine_repair_events[nom_machine] = repair_event

            if not self.headless and self.canvas.winfo_exists():
                if nom_machine in self.machine_rect_ids:
                    self.canvas.itemconfig(self.machine_rect_ids[nom_machine], fill="#e67e22")
                if nom_machine in self.machine_labels:
                    self.canvas.itemconfig(self.machine_labels[nom_machine], text="⚠ EN PANNE")

            # Attendre la durée de réparation (distribution exponentielle)
            duree_reparation = random.expovariate(1.0 / tmr_min)
            yield self.env.timeout(duree_reparation)
            if not self.running:
                break

            # --- Réparation terminée ---
            self.panne_machines.discard(nom_machine)
            if not repair_event.triggered:
                repair_event.succeed()
            self.machine_repair_events.pop(nom_machine, None)

            if not self.headless and self.canvas.winfo_exists():
                if nom_machine in self.machine_rect_ids:
                    self.canvas.itemconfig(self.machine_rect_ids[nom_machine], fill="#3498db")
                if nom_machine in self.machine_labels:
                    self.canvas.itemconfig(self.machine_labels[nom_machine], text=nom_machine)

    def _trouver_prochaine_machine(self, tube, machines, virtual_queues=None):
        """Délègue à core.sim_utils.trouver_prochaine_machine (logique pure testable)."""
        from core.sim_utils import trouver_prochaine_machine
        return trouver_prochaine_machine(
            tube, machines, self.machine_queues, virtual_queues,
            paillasse_occupee=self.paillasse_analyste,
        )

    def traiter_batch_machine(self, nom_machine, machine, force_batch_size=None):
        """Traite un batch de tubes sur une machine et les place en file de sortie.

        force_batch_size : si fourni, limite le batch à ce nombre (ex. 1 pour urgents
        isolés en mode ACCELERER IA).
        """
        capacite = machine.get("capacite", 4)
        if force_batch_size is not None:
            capacite = min(capacite, force_batch_size)
        # Trier la file par priorité composite avant d'extraire le batch :
        # urgent > % validité consommée > ancienneté → les tubes les plus critiques
        # sont toujours dans les premiers slots, même si déposés tardivement.
        # Les multiplicateurs de stress du coordinateur amplifient la séparation.
        mu, mv, ma = self.coordinateur.poids_courants
        _trier_queue_par_priorite(self.machine_queues[nom_machine], self.env.now, mu, mv, ma)
        batch = self.machine_queues[nom_machine][:capacite]
        del self.machine_queues[nom_machine][:capacite]

        # Démarrer le clignotement
        self.blinking_machines.add(nom_machine)
        self.env.process(self._blink_machine(nom_machine))

        # Feedback visuel : tubes en cours de traitement (bleu foncé)
        if not self.headless and self.canvas.winfo_exists():
            for tube in batch:
                if tube.get("id"):
                    self.canvas.itemconfig(tube["id"], fill="#2980b9", outline="#1a5276", width=2)

        if not self.headless and nom_machine in self.machine_labels:
            self.canvas.itemconfig(self.machine_labels[nom_machine], text=f"{nom_machine}: Traitement...")

        # Temps de traitement depuis le premier protocole de la machine
        protocoles = machine.get("protocoles", {})
        etape = next(iter(protocoles), None)
        temps = protocoles[etape].get("temps", 60) if etape else 60
        yield self.env.timeout(temps / 10)

        # === Vérification dégradation : tubes trop longtemps en attente ===
        delai_max = machine.get("delai_max_avant_degrad", None)
        if delai_max is not None:
            batch_valides = []
            for tube in batch:
                attente_totale = self.env.now - tube.get("arrivee", self.env.now)
                if attente_totale > delai_max:
                    self.tubes_degrades += 1
                    if not self.headless and self.canvas.winfo_exists() and tube.get("id"):
                        self.canvas.itemconfig(tube["id"], fill="#95a5a6", outline="#7f8c8d", width=1)
                        tid = tube["id"]
                        self.canvas.after(800, lambda t=tid: self.canvas.delete(t) if self.canvas.winfo_exists() else None)
                else:
                    batch_valides.append(tube)
            batch = batch_valides

        # === Machine en panne pendant le traitement (processus TMEP/TMR indépendant) ===
        # Si la machine a subi une panne pendant ce batch, attendre la fin de réparation
        # avant de libérer les tubes. Le batch est préservé (pas de perte).
        if nom_machine in self.panne_machines:
            repair_ev = self.machine_repair_events.get(nom_machine)
            if repair_ev is not None and not repair_ev.triggered:
                yield repair_ev

        # Traitement terminé : feedback visuel (vert = prêt à être récupéré)
        if not self.headless and self.canvas.winfo_exists():
            for tube in batch:
                if tube.get("id"):
                    self.canvas.itemconfig(tube["id"],
                                          fill=tube.get("couleur", "#27ae60"),
                                          outline="#27ae60", width=2)

        # Placer les tubes en file de sortie (workflow déjà à jour depuis le dépôt)
        if nom_machine not in self.output_queues:
            self.output_queues[nom_machine] = []
        self.output_queues[nom_machine].extend(batch)

        # Arrêter le clignotement
        self.blinking_machines.discard(nom_machine)

        # Relancer automatiquement si des tubes restent — toujours, sans condition de seuil.
        # La condition seuil/file_max est réservée au déclenchement INITIAL depuis un dépôt tech.
        # Pour les machines à opérateur requis : l'auto-restart est une continuation du batch
        # déjà autorisé par le tech — pas besoin de re-vérifier paillasse_analyste.
        queue_restante = self.machine_queues.get(nom_machine, [])
        if queue_restante:
            self.env.process(self.traiter_batch_machine(nom_machine, machine))