"""Mixin _TabLiveHeadless pour TabLive — extrait de ui/tab_live.py.

Ces méthodes utilisent `self.xxx` défini dans TabLive.__init__.
"""
from collections import deque
import simpy
import random
import json
import tkinter as tk
from tkinter import ttk
from core.sim.sim_io import sauver_stats_sim
from core.sim.priorite import (
    _score_priorite, _inserer_par_priorite,
    _trier_queue_par_priorite, _inserer_par_anciennete,
)
from core.stats_aggregator import StatsAggregator
from core.technician import TechnicianState
import ui.theme as theme


class _TabLiveHeadless:
    """Mixin : ne pas instancier directement."""

    def lancer_simulation_headless(self, duree_sim, on_progress=None, on_complete=None, seed=None):
        """Lance une simulation accélérée (sans animation) dans un thread séparé.
        - duree_sim   : durée en unités SimPy
        - on_progress : callback(t, total) appelé toutes les 5 % de progression
        - on_complete : callback() appelé à la fin (depuis le thread — utiliser .after())
        - seed        : graine random optionnelle (reproductibilité / tests)
        """
        import threading
        # Capturer ia_active MAINTENANT, avant que le thread ne démarre.
        # Cela évite que reset() ou un changement tardif ne l'écrase.
        _ia_pour_cette_sim = self.coordinateur.ia_active

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
                _MX = 43_200
                self.stats_history = {"time": deque(maxlen=_MX), "queues": {}, "output": {}, "busy": {}, "entry": deque(maxlen=_MX),
                                      "transit_time_avg": deque(maxlen=_MX), "transit_time_rolling": deque(maxlen=_MX),
                                      "transit_time_pending_max": deque(maxlen=_MX),
                                      "tat_normal_rolling": deque(maxlen=_MX), "tat_urgent_rolling": deque(maxlen=_MX),
                                      "rejetes": deque(maxlen=_MX), "degrades": deque(maxlen=_MX), "pannes": {},
                                      "distances_tech": {}, "bienetre": {},
                                      "arrivees_par_heure": {},
                                      "arrivees_par_heure_par_service": {},
                                      "events_arret_maladie": [],
                                      "stress_events": deque(maxlen=10_000),
                                      "anticipations": deque(maxlen=2_000)}
                self.aggregator = StatsAggregator()
                self.coordinateur.reset()
                # Réappliquer ia_active capturé AVANT le thread — reset() ne le touche pas
                # mais d'autres appels (toggle_sim, _toggle_ia) auraient pu le modifier.
                self.coordinateur.ia_active = _ia_pour_cette_sim
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
                    # Vitesse calibrée sur l'échelle réelle : 5 km/h équivaut à 20.83/mpc px/tick
                    # (1 tick = 0.05 SimPy = 0.3 s réelles ; 50 px = 1 case = metres_par_case)
                    _mpc1 = float(self.config_manager.data.get("personnel", {}).get("metres_par_case", 2.6))
                    tech.vitesse_base_px = 20.83 / max(0.1, _mpc1)
                    tech.office_x = office["coords"]["x"]
                    tech.office_y = office["coords"]["y"]
                    self.technicians.append(tech)

                # Créer l'environnement SimPy et lancer les processus
                self.env = simpy.Environment()
                self._init_sol_cache()  # sol + périmètre labo
                self.navette_queues     = {}
                self.navette_stats      = {}
                self.navette_en_transit = {}
                self.machine_slots_reserved = {}
                self._machines_batch_actif = set()
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
                import time as _time
                _t_reel_debut = _time.monotonic()
                _derniere_tranche_lente = False
                while t < duree_sim and self.running:
                    t_next = min(t + tranche, duree_sim)
                    _t0 = _time.monotonic()
                    self.env.run(until=t_next)
                    _duree_reel = _time.monotonic() - _t0
                    t = t_next
                    # Diagnostic : signaler si une tranche prend > 10 s réelles
                    if _duree_reel > 10.0:
                        jours_sim = t / 1440.0
                        entry_sz  = len(self.entry_queue)
                        mq_total  = sum(len(q) for q in self.machine_queues.values())
                        oq_total  = sum(len(q) for q in self.output_queues.values())
                        nb_batch  = len(self._machines_batch_actif)
                        print(f"[PERF] t={t:.0f} ({jours_sim:.1f}j) tranche={_duree_reel:.1f}s "
                              f"| entry={entry_sz} mq={mq_total} oq={oq_total} "
                              f"batch_actifs={nb_batch}")
                        _derniere_tranche_lente = True
                    elif _derniere_tranche_lente:
                        _derniere_tranche_lente = False
                    if on_progress:
                        on_progress(t, duree_sim)

            except Exception as e:
                print(f"[ERREUR HEADLESS] {e}")
                import traceback; traceback.print_exc()
            finally:
                self.running = False
                self.headless = False
                sauver_stats_sim(self.stats_history, self.transit_times_raw)
                if on_complete:
                    on_complete()

                self.headless = False
                if on_complete:
                    on_complete()

        threading.Thread(target=_run, daemon=True).start()

    def lancer_debug(self, on_fin=None):
        """Lance une simulation headless instrumentée (tranches de 10 min) pour
        détecter les blocages stochastiques. Écrit debug_sim.log et affiche un
        panneau en temps réel.

        Deux mécanismes de détection :
          1. Tranche > SEUIL_CRITIQUE secondes réelles → blocage sur cette tranche.
          2. Thread moniteur : env.now immobile 6 s → freeze confirmé.

        on_fin : callback optionnel appelé depuis le thread quand la session se termine.
        """
        import threading
        import time as _time
        import json

        if self.running:
            from tkinter import messagebox
            messagebox.showwarning("Simulation en cours",
                                   "Arrêter d'abord la simulation en cours.")
            return

        # ── Fenêtre de suivi ────────────────────────────────────────────────
        win = tk.Toplevel(self.parent)
        win.title("Simulation DEBUG")
        win.geometry("700x440")
        win.resizable(True, True)

        frm_top = ttk.Frame(win)
        frm_top.pack(fill=tk.X, padx=8, pady=4)
        lbl_status = ttk.Label(frm_top, text="Initialisation...", font=theme.FONT_BODY)
        lbl_status.pack(side=tk.LEFT)
        btn_stop = ttk.Button(frm_top, text="Arrêter",
                              command=lambda: setattr(self, 'running', False))
        btn_stop.pack(side=tk.RIGHT)

        txt = tk.Text(win, height=22, width=90, font=("Consolas", 8),
                      state=tk.DISABLED, wrap=tk.NONE)
        sb_y = ttk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=sb_y.set)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        lbl_log = ttk.Label(win, text="", font=("Consolas", 8), foreground="#7f8c8d")
        lbl_log.pack(anchor=tk.W, padx=8, pady=2)

        LOG_PATH = "debug_sim.log"
        log_lines: list = []

        def ui_log(msg: str):
            log_lines.append(msg)
            def _append():
                txt.configure(state=tk.NORMAL)
                txt.insert(tk.END, msg + "\n")
                txt.see(tk.END)
                txt.configure(state=tk.DISABLED)
            self.parent.after(0, _append)

        def dump_state(prefix: str = ""):
            t = self.env.now if self.env else -1.0
            mq = {k: len(v) for k, v in self.machine_queues.items() if v}
            oq = {k: len(v) for k, v in self.output_queues.items() if v}
            if self.env and self.env._queue:
                eq_size = len(self.env._queue)
                eq_at_now = sum(1 for e in self.env._queue if abs(e[0] - t) < 1e-9)
                eq_times = sorted(set(round(e[0], 1) for e in self.env._queue[:200]))[:8]
            else:
                eq_size = eq_at_now = 0
                eq_times = []
            lines = [
                f"{prefix}t_sim={t:.1f} ({t/1440:.3f}j)",
                f"  batch_actifs({len(self._machines_batch_actif)}): {sorted(self._machines_batch_actif)}",
                f"  blinking({len(self.blinking_machines)}): {sorted(self.blinking_machines)}",
                f"  machine_queues={mq}",
                f"  output_queues={oq}",
                f"  entry_queue={len(self.entry_queue)}",
                f"  SimPy_events={eq_size} | a_t_now={eq_at_now} | prochains_t={eq_times}",
            ]
            for line in lines:
                ui_log(line)

        # ── Thread moniteur (détecte le freeze depuis l'extérieur) ──────────
        _freeze_signale = [False]

        def _moniteur():
            prev_t = -1.0
            stale = 0
            while self.running:
                _time.sleep(3.0)
                if not self.running:
                    break
                if self.env is None:
                    continue
                cur = self.env.now
                if abs(cur - prev_t) < 0.001:
                    stale += 1
                    if stale >= 2 and not _freeze_signale[0]:
                        # Distinguer vrai blocage (aucun event SimPy) de simple lenteur
                        n_events = len(self.env._queue) if (self.env and self.env._queue) else 0
                        if n_events == 0:
                            # Vrai gel : SimPy n'a plus d'événements à traiter
                            _freeze_signale[0] = True
                            ui_log(f"\n>>> FREEZE DETECTE : env.now={cur:.1f} immobile depuis ~{stale*3}s (0 events) <<<")
                            dump_state("FREEZE ")
                            self.running = False
                        else:
                            # Simulation lente mais pas bloquée : logguer sans arrêter
                            ui_log(f"\n>>> RALENTISSEMENT : env.now={cur:.1f} immobile ~{stale*3}s ({n_events} events en attente) <<<")
                            dump_state("LENT  ")
                else:
                    stale = 0
                prev_t = cur

        # ── Thread simulation ───────────────────────────────────────────────
        def _run_debug():
            try:
                self._debug_mode = True
                self._debug_entries.clear()
                self.headless = True
                self.running = True
                self.parent.after(0, lambda: self.btn_reset.config(state="normal"))

                # -- Init identique à lancer_simulation_headless --
                self.entry_queue = []
                self.machine_queues = {}
                self.output_queues = {}
                self.technicians = []
                self.blinking_machines = set()
                self.machine_indicators = {}
                self.machine_labels = {}
                self.machine_labels_queue = {}
                self.machine_labels_output = {}
                _MX = 43_200
                self.stats_history = {
                    "time": deque(maxlen=_MX), "queues": {}, "output": {}, "busy": {},
                    "entry": deque(maxlen=_MX),
                    "transit_time_avg": deque(maxlen=_MX),
                    "transit_time_rolling": deque(maxlen=_MX),
                    "transit_time_pending_max": deque(maxlen=_MX),
                    "tat_normal_rolling": deque(maxlen=_MX), "tat_urgent_rolling": deque(maxlen=_MX),
                    "rejetes": deque(maxlen=_MX), "degrades": deque(maxlen=_MX),
                    "pannes": {}, "distances_tech": {}, "bienetre": {},
                    "arrivees_par_heure": {}, "arrivees_par_heure_par_service": {},
                    "events_arret_maladie": [],
                    "stress_events": deque(maxlen=10_000),
                    "anticipations": deque(maxlen=2_000),
                }
                self.aggregator = StatsAggregator()
                self.coordinateur.reset()
                self.coordinateur.ia_active = False  # pas d'IA en debug
                self._jours_connus_dist = set()
                self._cache_navette_conf = None
                self._cache_fournisseurs = None
                self.stats_tubes_total = 0
                self.tubes_sortis = 0
                self.transit_times_raw = deque(maxlen=10_000)
                self._transit_sum = 0.0
                self.transit_times_urgents = deque(maxlen=10_000)
                self.transit_times_normaux = deque(maxlen=10_000)
                self.tat_par_type = {}
                self.preanalyse_par_type = {}
                self.prochaine_arrivee = 0
                self.panne_machines = set()
                self.paillasse_analyste = set()
                self.machine_repair_events = {}
                self.tubes_rejetes = 0
                self.tubes_degrades = 0
                self.tubes_perimes = 0

                config_types = self.config_manager.data.get("types_tubes", {})
                if config_types:
                    self.types_tubes = config_types

                machines = self.config_manager.get_machines()
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
                    tech.seuil_charge_fatigue   = float(office.get("seuil_charge_fatigue", 0.70))
                    tech.taux_montee_fatigue    = float(office.get("taux_montee_fatigue", 0.01))
                    tech.taux_recuperation_nuit = float(office.get("taux_recuperation_nuit", 0.15))
                    tech.capacite_max_tubes     = int(office.get("capacite_max_tubes", 10))
                    _mpc2 = float(self.config_manager.data.get("personnel", {}).get("metres_par_case", 2.6))
                    tech.vitesse_base_px = 20.83 / max(0.1, _mpc2)
                    tech.office_x = office["coords"]["x"]
                    tech.office_y = office["coords"]["y"]
                    self.technicians.append(tech)

                self.env = simpy.Environment()
                self._init_sol_cache()  # sol + périmètre labo
                self.navette_queues     = {}
                self.navette_stats      = {}
                self.navette_en_transit = {}
                self.machine_slots_reserved = {}
                self._machines_batch_actif = set()

                fournisseurs_cfg = self.config_manager.get_fournisseurs()
                fournisseurs_actifs = {
                    fid: f for fid, f in fournisseurs_cfg.items()
                    if f.get("actif", True)
                }
                if fournisseurs_actifs:
                    navette_conf = self.config_manager.get_navette_principale()
                    for fid, fconf in fournisseurs_actifs.items():
                        self.navette_queues[fid] = []
                        self.navette_stats[fid] = {"en_transit": 0, "total_envoye": 0, "en_queue": 0}
                        self.env.process(self.tube_generation_fournisseur(fid, fconf))
                        self.env.process(self.navette_process(fid, fconf, navette_conf))
                else:
                    self.env.process(self.tube_generation())
                for tech in self.technicians:
                    self.env.process(self.technician_process(tech))
                self.env.process(self.stats_collector())
                self.env.process(self.coordinateur_process())
                for nom_m, m_conf in machines.items():
                    if m_conf.get("tmep") and m_conf.get("tmr"):
                        self.env.process(self.machine_breakdown_process(nom_m, m_conf))

                # Démarrer le thread moniteur
                threading.Thread(target=_moniteur, daemon=True).start()

                duree_sim = float(self.config_manager.data.get("duree_simulation", 10080))
                # Tranches fines : 10 min sim → détection précise au ~1/1000 de journée
                TRANCHE = 10.0
                SEUIL_LENT = 0.5      # secondes réelles pour 10 min sim = anormal
                SEUIL_CRITIQUE = 20.0  # = figé sur cette tranche

                t_sim = 0.0
                nb_lentes = 0

                ui_log(f"=== DEBUG SIM — durée={duree_sim:.0f} min ({duree_sim/1440:.1f}j) ===")
                ui_log(f"Tranche={TRANCHE:.0f} min sim | Seuil lent={SEUIL_LENT}s | Critique={SEUIL_CRITIQUE}s\n")

                while t_sim < duree_sim and self.running:
                    t_next = min(t_sim + TRANCHE, duree_sim)
                    t0 = _time.monotonic()
                    self.env.run(until=t_next)
                    elapsed = _time.monotonic() - t0
                    t_sim = t_next

                    pct = t_sim / duree_sim * 100
                    self.parent.after(0, lambda p=pct, ts=t_sim, ms=elapsed * 1000:
                        lbl_status.config(
                            text=f"t={ts:.0f} ({ts/1440:.2f}j) — {p:.0f}% | {ms:.0f} ms/tranche"
                        ))

                    if elapsed > SEUIL_LENT:
                        nb_lentes += 1
                        ui_log(f"\n--- Tranche LENTE #{nb_lentes} "
                               f"t=[{t_sim-TRANCHE:.0f},{t_sim:.0f}] : {elapsed:.3f}s ---")
                        dump_state()
                        # Dump des 20 dernières entrées debug
                        recentes = list(self._debug_entries)[-20:]
                        if recentes:
                            ui_log("  Derniers events batch:")
                            for e in recentes:
                                ui_log(f"    {e}")

                    if elapsed > SEUIL_CRITIQUE:
                        ui_log(f"\n>>> TRANCHE CRITIQUE ({elapsed:.1f}s) — blocage confirmé <<<")
                        self.running = False
                        break

            except Exception as exc:
                import traceback
                ui_log(f"\nEXCEPTION: {exc}\n{traceback.format_exc()}")
            finally:
                self._debug_mode = False
                self.running = False
                self.headless = False

                # Sérialiser les entrées debug en JSON
                try:
                    with open(LOG_PATH, "w", encoding="utf-8") as fh:
                        json.dump({
                            "log": log_lines,
                            "debug_entries": list(self._debug_entries),
                        }, fh, ensure_ascii=False, indent=2)
                    self.parent.after(0, lambda: lbl_log.config(
                        text=f"Log écrit : {LOG_PATH}"))
                except Exception as exc_w:
                    # La variable d'exception est effacée à la sortie du except:,
                    # donc on doit capturer le message avant le lambda différé.
                    _msg_erreur_log = f"Erreur écriture log : {exc_w}"
                    self.parent.after(0, lambda: lbl_log.config(
                        text=_msg_erreur_log))

                self.parent.after(0, lambda: lbl_status.config(text="Terminé."))
                self.parent.after(0, lambda: btn_stop.config(
                    text="Fermer", command=win.destroy))
                self.parent.after(0, lambda: self.btn_reset.config(state="disabled"))
                if on_fin:
                    on_fin()

        threading.Thread(target=_run_debug, daemon=True).start()
