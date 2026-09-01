"""Mixin _TabLiveToggle pour TabLive — extrait de ui/tab_live.py.

Ces méthodes utilisent `self.xxx` défini dans TabLive.__init__.
"""
from collections import deque
import simpy
import tkinter as tk
from tkinter import ttk
import ui.theme as theme
from core.stats_aggregator import StatsAggregator
from core.technician import TechnicianState
from core.sim.sim_io import sauver_stats_sim


class _TabLiveToggle:
    """Mixin : ne pas instancier directement."""

    def forcer_arret(self):
        """Réinitialise l'état de la simulation sans fermer l'application.

        Stratégie thread-safe : on pose uniquement les flags d'arrêt (running,
        headless, _debug_mode). Le thread daemon SimPy verra running=False à son
        prochain yield et s'arrêtera proprement sans accéder aux dicts partagés.
        Les structures de données (queues, stats, env…) sont réinitialisées au
        prochain lancement de simulation dans toggle_sim / lancer_simulation_headless
        — pas ici, pour éviter les KeyError/AttributeError sur l'env encore actif.
        """
        self.running = False
        self.headless = False
        self._debug_mode = False
        # Réinitialiser uniquement les compteurs UI (pas les dicts partagés
        # avec le thread encore en cours d'arrêt).
        self.turbo = False
        self.paused = False
        self.btn_turbo.config(text="⚡ ×10")
        self.btn_pause.config(text="⏸ PAUSE", state="disabled")
        self.btn_start.config(text="▶ LANCER SIMULATION")
        self.btn_reset.config(state="disabled")
        self.lbl_queue.config(text="Tubes en attente : 0")
        self.lbl_erreurs.config(text="⚠ Rejets: 0 | Dégradés: 0")
        if hasattr(self, 'lbl_stress'):
            self.lbl_stress.config(text="⚪ Stress: —", foreground="#7f8c8d")
        print("[INFO] Simulation forcée à l'arrêt — état réinitialisé.")

    def toggle_sim(self):
        """Démarre ou arrête la simulation"""
        if not self.running:
            # DÉMARRAGE
            self.running = True
            self.btn_start.config(text="⏹ ARRÊTER SIMULATION")
            self.btn_reset.config(state="normal")
            self.paused = False
            self.btn_pause.config(text="⏸ PAUSE", state="normal")
            
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
                _mpc3 = float(self.config_manager.data.get("personnel", {}).get("metres_par_case", 2.6))
                tech.vitesse_base_px = 20.83 / max(0.1, _mpc3)
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
                # Label tubes portés : "ct1:3; au2:1" affiché à droite du sprite
                tech.label_tubes_id = self.canvas.create_text(
                    tech.x + 14, tech.y, text="",
                    font=theme.FONT_NOTE, fill="#2c3e50",
                    anchor="w", tags="tech_tubes")
                self.technicians.append(tech)
            self.canvas.update()
            
            # Démarrer SimPy
            self.env = simpy.Environment()
            self._init_sol_cache()  # sol + périmètre labo rafraîchi
            # Initialiser heure_debut_sim depuis la config ENTREE
            entrees_cfg = [m for m in machines.values() if m["type"] == "ENTREE"]
            self.heure_debut_sim = entrees_cfg[0].get("heure_debut", 7.0) if entrees_cfg else 7.0
            self.prochaine_arrivee = 0

            # Réinitialiser les statistiques
            _MX = 43_200
            self.stats_history = {"time": deque(maxlen=_MX), "queues": {}, "output": {}, "busy": {}, "entry": deque(maxlen=_MX),
                                  "bienetre": {},
                                  "transit_time_avg": deque(maxlen=_MX), "transit_time_rolling": deque(maxlen=_MX),
                                  "transit_time_pending_max": deque(maxlen=_MX),
                                  "tat_normal_rolling": deque(maxlen=_MX), "tat_urgent_rolling": deque(maxlen=_MX),
                                  "rejetes": deque(maxlen=_MX), "degrades": deque(maxlen=_MX), "pannes": {},
                                  "distances_tech": {},
                                  "arrivees_par_heure": {},
                                  "arrivees_par_heure_par_service": {},
                                  "events_arret_maladie": [],
                                  "stress_events": deque(maxlen=10_000),
                                  "anticipations": deque(maxlen=2_000)}
            self.aggregator = StatsAggregator()
            self.coordinateur.reset()
            # Synchroniser ia_active avec le toggle UI de l'onglet Live
            self.coordinateur.ia_active = self._var_ia.get()
            if not self.headless and hasattr(self, 'lbl_stress'):
                self.lbl_stress.config(text="⚪ Stress: —", foreground="#7f8c8d")
            self._jours_connus_dist = set()
            self._cache_navette_conf = None  # reset cache lecture disque
            self._cache_fournisseurs = None
            self.stats_tubes_total = 0
            self.tubes_sortis = 0
            self.transit_times_raw = deque(maxlen=10_000)
            self._transit_sum = 0.0
            self.transit_times_urgents = deque(maxlen=10_000)
            self.transit_times_normaux = deque(maxlen=10_000)
            self.tat_par_type = {}
            self.preanalyse_par_type = {}
            self.panne_machines = set()
            self.paillasse_analyste = set()
            self.machine_repair_events = {}
            self.tubes_rejetes = 0
            self.tubes_degrades = 0
            self.tubes_perimes = 0

            # Réinitialiser les navettes multi-source
            self.navette_queues     = {}
            self.navette_stats      = {}
            self.navette_en_transit = {}
            self.machine_slots_reserved = {}
            self._machines_batch_actif = set()

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
            self.btn_reset.config(state="disabled")
            for t in self.technicians:
                if t.canvas_id:
                    try:
                        self.canvas.delete(t.canvas_id)
                    except Exception:
                        pass
            self.technicians = []
            sauver_stats_sim(self.stats_history, self.transit_times_raw)
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

    def toggle_pause(self):
        """Gèle / reprend la simulation sans la stopper."""
        self.paused = not self.paused
        self.btn_pause.config(text="▶ REPRENDRE" if self.paused else "⏸ PAUSE")

    def run_sim_loop(self):
        """Boucle qui exécute la simulation par étapes"""
        if self.running and self.env:
            try:
                if not self.paused:
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
                self.paused = False
                self.btn_turbo.config(text="⚡ ×10")
                self.btn_pause.config(text="⏸ PAUSE", state="disabled")
                self.btn_start.config(text="▶ LANCER SIMULATION")
                self.btn_reset.config(state="disabled")
            except Exception as e:
                if self.running:
                    print(f"[ERREUR LOOP] {e}")
                    self.running = False
