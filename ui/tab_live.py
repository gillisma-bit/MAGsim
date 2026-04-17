import tkinter as tk
from tkinter import ttk
import simpy
import math
import random
import heapq
from core.technician import TechnicianState


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
                              "rejetes": [], "degrades": [], "pannes": {},
                              "distances_tech": {}, "bienetre": {}}
        self.stats_tubes_total = 0
        self.tubes_sortis = 0  # Tubes ayant atteint la sortie
        self.transit_times_raw = []  # Durées de transit individuelles (arrivee → sortie)
        self.headless = False  # True = simulation accélérée sans animation (mode goulots)
        self.turbo = False  # True = 10 pas SimPy par tick (×10 vitesse)
        self._sol_cache = None  # Cache du sol grid, initialisé au lancement de la simulation
        self.heure_debut_sim = 7.0  # Heure de démarrage (lue depuis config ENTREE)
        self.panne_machines = set()     # noms des machines actuellement en panne
        self.paillasse_analyste = set()  # noms des Paillasses avec un tech actuellement à poste
        self.machine_repair_events = {}     # nom_machine -> simpy.Event déclenché quand réparé
        self.machine_rect_ids = {}      # nom_machine -> id canvas du rectangle
        self.tubes_rejetes = 0          # compteur cumulatif rejets (mauvais prélèv. + erreur tech)
        self.tubes_degrades = 0         # compteur cumulatif dégradés (délai ou panne machine)
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
        
        self.lbl_queue = ttk.Label(self.info_frame, text="Tubes en attente : 0", 
                                   font=("Arial", 11, "bold"), foreground="#e74c3c")
        self.lbl_queue.pack(side=tk.RIGHT, padx=20)

        self.lbl_heure = ttk.Label(self.info_frame, text="🕐 --:--",
                                   font=("Arial", 11, "bold"), foreground="#2c3e50")
        self.lbl_heure.pack(side=tk.RIGHT, padx=20)

        self.lbl_erreurs = ttk.Label(self.info_frame, text="⚠ Rejets: 0 | Dégradés: 0",
                                     font=("Arial", 10), foreground="#e67e22")
        self.lbl_erreurs.pack(side=tk.RIGHT, padx=15)

    def mettre_a_jour_compteur(self):
        """Met à jour l'affichage du nombre de tubes et de l'heure simulée"""
        if self.headless:
            return
        nb = len(self.entry_queue or [])
        self.lbl_queue.config(text=f"Tubes en attente : {nb}")
        self.lbl_erreurs.config(text=f"⚠ Rejets: {self.tubes_rejetes} | Dégradés: {self.tubes_degrades}")
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
            x, y = m["coords"]["x"], m["coords"]["y"]
            if m["type"] == "ENTREE":
                color = "#2ecc71"
            elif m["type"] == "SORTIE":
                color = "#e74c3c"
            elif m["type"] == "TECH_OFFICE":
                color = "#95a5a6"  # gris
            else:
                color = "#3498db"
            
            rect_id = self.canvas.create_rectangle(x-25, y-25, x+25, y+25, fill=color, outline="black", width=2)
            if m["type"] not in ("ENTREE", "SORTIE", "TECH_OFFICE"):
                self.machine_rect_ids[nom] = rect_id
            if m["type"] == "TECH_OFFICE":
                self.canvas.create_text(x, y+35, text="Bureau Tech", font=("Arial", 7, "bold"))
            else:
                self.canvas.create_text(x, y+30, text=nom, font=("Arial", 7, "bold"))

            # Point indicateur (rouge = en travail) — masqué par défaut
            if m["type"] not in ("ENTREE", "SORTIE", "TECH_OFFICE"):
                ind_id = self.canvas.create_oval(x+15, y-25, x+25, y-15,
                                                 fill="", outline="", tags=f"ind_{nom}")
                self.machine_indicators[nom] = ind_id

            # --- Labels par machine (sauf SORTIE) ---
            if m["type"] == "ENTREE":
                # ENTREE : un seul label haut (nb tubes en attente à l'entrée)
                self.canvas.create_rectangle(x-40, y-52, x+40, y-37, fill="white", outline="#27ae60", width=1)
                lbl = self.canvas.create_text(x, y-44, text=f"{nom}: 0",
                                              font=("Arial", 8, "bold"), fill="#27ae60")
                self.machine_labels[nom] = lbl

            elif m["type"] == "SORTIE":
                # Label SORTIE : compteur de tubes traités
                self.canvas.create_rectangle(x-40, y-52, x+40, y-37, fill="white", outline="#e74c3c", width=1)
                lbl_s = self.canvas.create_text(x, y-44, text="Sortis : 0",
                                                font=("Arial", 8, "bold"), fill="#e74c3c")
                self.machine_labels[nom] = lbl_s

            elif m["type"] not in ("TECH_OFFICE"):
                # --- Label HAUT : tubes total entrés dans la machine ---
                self.canvas.create_rectangle(x-35, y-52, x+35, y-37,
                                             fill="white", outline="gray", width=1)
                lbl_top = self.canvas.create_text(x, y-44, text=f"{nom}",
                                                  font=("Arial", 8, "bold"), fill="#2c3e50")
                self.machine_labels[nom] = lbl_top

                # --- Label DROITE : file d'attente (tubes déposés, pas encore traités) ---
                self.canvas.create_rectangle(x+28, y-12, x+70, y+12,
                                             fill="#fef9e7", outline="#e67e22", width=1)
                self.canvas.create_text(x+49, y-16, text="En attente",
                                        font=("Arial", 6), fill="#e67e22")
                lbl_q = self.canvas.create_text(x+49, y, text="0",
                                                font=("Arial", 9, "bold"), fill="#e67e22")
                self.machine_labels_queue[nom] = lbl_q

                # --- Label GAUCHE : tubes traités prêts à partir ---
                self.canvas.create_rectangle(x-70, y-12, x-28, y+12,
                                             fill="#eafaf1", outline="#27ae60", width=1)
                self.canvas.create_text(x-49, y-16, text="Prêts",
                                        font=("Arial", 6), fill="#27ae60")
                lbl_o = self.canvas.create_text(x-49, y, text="0",
                                                font=("Arial", 9, "bold"), fill="#27ae60")
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

    def lancer_simulation_headless(self, duree_sim, on_progress=None, on_complete=None):
        """Lance une simulation accélérée (sans animation) dans un thread séparé.
        - duree_sim   : durée en unités SimPy
        - on_progress : callback(t, total) appelé toutes les 5 % de progression
        - on_complete : callback() appelé à la fin (depuis le thread — utiliser .after())
        """
        import threading

        def _run():
            try:
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
                                      "rejetes": [], "degrades": [], "pannes": {},
                                      "distances_tech": {}, "bienetre": {}}
                self._jours_connus_dist = set()
                self.stats_tubes_total = 0
                self.tubes_sortis = 0
                self.transit_times_raw = []
                self.prochaine_arrivee = 0
                self.panne_machines = set()
                self.paillasse_analyste = set()
                self.machine_repair_events = {}
                self.tubes_rejetes = 0
                self.tubes_degrades = 0

                # Charger la config
                config_types = self.config_manager.data.get("types_tubes", {})
                if config_types:
                    self.types_tubes = config_types

                machines = self.config_manager.get_machines()
                # Charger heure_debut depuis la config ENTREE
                entrees_cfg = [m for m in machines.values() if m["type"] == "ENTREE"]
                self.heure_debut_sim = entrees_cfg[0].get("heure_debut", 7.0) if entrees_cfg else 7.0
                tech_offices = [m for m in machines.values() if m["type"] == "TECH_OFFICE"]
                if not tech_offices:
                    tech_offices = [{"coords": {"x": 125, "y": 125}}]
                for idx, office in enumerate(tech_offices):
                    tech = TechnicianState(
                        office["coords"]["x"], office["coords"]["y"],
                        canvas_id=None, index=idx)
                    tech.pct_erreur_base = office.get("pct_erreur_tech", 0.0)
                    tech.pct_erreur     = tech.pct_erreur_base
                    tech.nom            = office.get("nom", f"Tech {idx + 1}")
                    tech.experience     = int(office.get("experience", 3))
                    tech.age            = int(office.get("age", 35))
                    tech.seuil_charge_fatigue  = float(office.get("seuil_charge_fatigue", 0.70))
                    tech.taux_montee_fatigue   = float(office.get("taux_montee_fatigue", 0.01))
                    tech.capacite_max_tubes    = int(office.get("capacite_max_tubes", 10))
                    self.technicians.append(tech)

                # Créer l'environnement SimPy et lancer les processus
                self.env = simpy.Environment()
                self._sol_cache = self.config_manager.data.get("sol", {})  # cache sol
                self.env.process(self.tube_generation())
                for t in self.technicians:
                    self.env.process(self.technician_process(t))
                self.env.process(self.stats_collector())
                # Lancer un processus de panne indépendant pour chaque machine avec TMEP/TMR
                machines_reload = self.config_manager.get_machines()
                for nom_m, m_conf in machines_reload.items():
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
            tech_offices = [m for m in machines.values() if m["type"] == "TECH_OFFICE"]
            if not tech_offices:
                tech_offices_default = [{"coords": {"x": 125, "y": 125}}]
                tech_offices = tech_offices_default
            for idx, office in enumerate(tech_offices):
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
                tech.nom            = office.get("nom", f"Tech {idx + 1}")
                tech.experience     = int(office.get("experience", 3))
                tech.age            = int(office.get("age", 35))
                tech.seuil_charge_fatigue  = float(office.get("seuil_charge_fatigue", 0.70))
                tech.taux_montee_fatigue   = float(office.get("taux_montee_fatigue", 0.01))
                tech.capacite_max_tubes    = int(office.get("capacite_max_tubes", 10))
                tech.canvas_id = self.canvas.create_oval(
                    tech.x-10, tech.y-10, tech.x+10, tech.y+10,
                    fill=tech.color, outline="black", width=2, tags="tech")
                # Emoji bien-être affiché au-dessus du sprite
                emoji_init, _, _ = tech.etat_bien_etre()
                tech.label_bienetre_id = self.canvas.create_text(
                    tech.x, tech.y - 18, text=emoji_init,
                    font=("Segoe UI", 10), tags="tech_bienetre")
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
                                  "rejetes": [], "degrades": [], "pannes": {},
                                  "distances_tech": {}}
            self._jours_connus_dist = set()
            self.stats_tubes_total = 0
            self.tubes_sortis = 0
            self.transit_times_raw = []
            self.panne_machines = set()
            self.paillasse_analyste = set()
            self.machine_repair_events = {}
            self.tubes_rejetes = 0
            self.tubes_degrades = 0

            self.mettre_a_jour_compteur()

            self.env.process(self.tube_generation())
            for t in self.technicians:
                self.env.process(self.technician_process(t))
            self.env.process(self.stats_collector())
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
                if m["type"] in ("ENTREE", "SORTIE", "TECH_OFFICE"):
                    continue
                # File d'attente
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

            # Compteurs d'erreurs (valeurs cumulatives, parallèles à "time")
            self.stats_history["rejetes"].append(self.tubes_rejetes)
            self.stats_history["degrades"].append(self.tubes_degrades)

            # Distance journalière par technicien (1 jour SimPy = 1440 min)
            # 1 px = 1 cm (grille : 1 case = 50 px = 50 cm). Distance stockée en mètres.
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
                    for tech in self.technicians:
                        tech._distance_debut_jour_px = tech.distance_parcourue_px
                        # Mécontentement : comparaison tubes livrés hier vs capacité normale
                        tubes_jour = tech.tubes_livres_session - tech._tubes_livres_debut_jour
                        tech.mettre_a_jour_mecontentement(tubes_jour, cap_jour)
                        tech._tubes_livres_debut_jour = tech.tubes_livres_session
                        # Risque arrêt maladie : tirage aléatoire journalier
                        import random as _rnd
                        risque = tech.calculer_risque_arret_maladie()
                        if risque > 0 and _rnd.random() < risque:
                            tech.en_arret_maladie = True
                        self._update_tech_sprite_bienetre(tech)
            for idx, tech in enumerate(self.technicians):
                k = tech.nom if tech.nom else f"Tech {idx + 1}"
                if k not in self.stats_history["distances_tech"]:
                    self.stats_history["distances_tech"][k] = {}
                d_m = (tech.distance_parcourue_px - tech._distance_debut_jour_px) * 0.01
                self.stats_history["distances_tech"][k][jour_actuel] = round(d_m, 1)
                # Historique bien-être (valeur courante)
                if k not in self.stats_history["bienetre"]:
                    self.stats_history["bienetre"][k] = {}
                self.stats_history["bienetre"][k][jour_actuel] = round(tech.mecontentement, 3)

            yield self.env.timeout(interval)

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
                    tube = {
                        "type":    nom_type,
                        "workflow": list(conf.get("workflow", [])),
                        "couleur":  conf.get("couleur", "#3498db"),
                        "arrivee":  self.env.now,
                        "urgent":   random.random() < conf.get("pct_urgent", 0.0)
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
                    self.stats_tubes_total += 1

                self.prochaine_arrivee = self.env.now + prochaine_interarrivee()

            yield self.env.timeout(0.5)


    def technician_process(self, tech):
        """Processus d'un technicien : collecte tous les tubes disponibles, vérifie la capacité des files, dépose et récupère."""
        machines = self.config_manager.get_machines()
        entrees = [m for m in machines.values() if m["type"] == "ENTREE"]
        sorties = [m for m in machines.values() if m["type"] == "SORTIE"]

        while self.running:

            # --- Priorité 1 : tubes ayant fini un traitement, à récupérer ---
            # Claim immédiat : vider output_queues AVANT de yielder pour éviter
            # qu'un autre tech parte vers les mêmes tubes.
            tubes_finis = []
            noms_a_vider = []
            for nom_m in list(self.output_queues.keys()):
                if self.output_queues[nom_m]:
                    tubes_finis.extend(self.output_queues[nom_m])
                    noms_a_vider.append(nom_m)

            if tubes_finis:
                # Réserver les tubes immédiatement — avant tout déplacement
                for nom_m in noms_a_vider:
                    self.output_queues[nom_m] = []
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
                        places_par_machine[nom] = max(0, fm - deja)

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

            tech.carried_tubes = self.entry_queue[:nb_a_prendre]
            del self.entry_queue[:nb_a_prendre]

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
                places_dispo = file_max - deja_en_queue

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
                    queue = self.machine_queues[nom_machine]
                    has_urgent = any(t.get("urgent") for t in queue)
                    # Lancer si : batch complet OU (urgence présente ET seuil atteint)
                    should_trigger = (
                        len(queue) >= capacite
                        or (has_urgent and len(queue) >= seuil)
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

                            # Bloquer le tech pour toute la durée de l'analyse
                            yield self.env.timeout(temps_analyse / 10)
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
                    yield self.env.process(self.deplacer_vers(tech, libre_x, libre_y))
                # Enregistrer le temps de transit
                now = self.env.now
                for tube in vers_sortie:
                    if "arrivee" in tube:
                        self.transit_times_raw.append(now - tube["arrivee"])
                # Retirer + supprimer APRÈS l'arrivée
                self.tubes_sortis += len(vers_sortie)
                tech.carried_tubes = [t for t in tech.carried_tubes if t not in vers_sortie]
                if not self.headless:
                    for tube in vers_sortie:
                        if self.canvas.winfo_exists() and tube.get("id"):
                            self.canvas.delete(tube["id"])

            # Si certains tubes n'ont pas pu être déposés (file pleine), attendre et réessayer
            if tubes_reportes:
                etapes_bloquees = list({t["workflow"][0] for t in tubes_reportes if t.get("workflow")})
                print(f"[INFO] {len(tubes_reportes)} tube(s) en attente (machines pleines pour {etapes_bloquees}), retry dans 2 min")
                yield self.env.timeout(2)
                tubes = tubes_reportes
            else:
                break

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
        if tech.canvas_id:
            self.canvas.itemconfig(tech.canvas_id, fill=tech.color)
        if tech.label_bienetre_id:
            self.canvas.itemconfig(tech.label_bienetre_id, text=emoji)
            self.canvas.coords(tech.label_bienetre_id, tech.x, tech.y - 18)

    def machine_breakdown_process(self, nom_machine, machine):
        """Processus indépendant modélisant les pannes par loi exponentielle (TMEP/TMR).

        TMEP (Temps Moyen Entre Pannes) et TMR (Temps Moyen de Réparation) sont en minutes.
        Taux de disponibilité théorique : A = TMEP / (TMEP + TMR).
        """
        tmep = machine.get("tmep", 0)
        tmr  = machine.get("tmr",  0)
        if not tmep or not tmr or tmep <= 0 or tmr <= 0:
            return

        while self.running:
            # Attendre le prochain incident (distribution exponentielle)
            delai_avant_panne = random.expovariate(1.0 / tmep) / 10
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
            duree_reparation = random.expovariate(1.0 / tmr) / 10
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
        return trouver_prochaine_machine(tube, machines, self.machine_queues, virtual_queues)

    def traiter_batch_machine(self, nom_machine, machine):
        """Traite un batch de tubes sur une machine et les place en file de sortie."""
        capacite = machine.get("capacite", 4)
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

        # Relancer automatiquement s'il reste des tubes en attente,
        # mais seulement si la condition capacité/urgence est remplie
        queue_restante = self.machine_queues.get(nom_machine, [])
        if queue_restante:
            seuil = machine.get("seuil", 1)
            has_urgent = any(t.get("urgent") for t in queue_restante)
            should_trigger = (
                len(queue_restante) >= capacite
                or (has_urgent and len(queue_restante) >= seuil)
            )
            if should_trigger:
                self.env.process(self.traiter_batch_machine(nom_machine, machine))