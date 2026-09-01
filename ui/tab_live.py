import tkinter as tk
from tkinter import ttk
import simpy
import math
import random
import heapq
import bisect
import json
import os
from collections import deque
from core.technician import TechnicianState
from core.stats_aggregator import StatsAggregator
from core.coordinateur_stress import CoordonnateurStress
import ui.theme as theme

from ui._tablivegeneration import _TabLiveGeneration
from ui._tabliveheadless import _TabLiveHeadless
from ui._tablivelivraison import _TabLiveLivraison
from ui._tablivemachine import _TabLiveMachine
from ui._tablivepathfinding import _TabLivePathfinding
from ui._tablivestats import _TabLiveStats
from ui._tablivetechnician import _TabLiveTechnician
from ui._tablivetoggle import _TabLiveToggle

# ─── Pont simulation → Gradio ────────────────────────────────────────────────
_LAST_SIM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "last_sim.json")

def _deep_to_list(obj):
    """Convertit récursivement deques et sets en listes pour la sérialisation JSON."""
    if isinstance(obj, dict):
        return {k: _deep_to_list(v) for k, v in obj.items()}
    if isinstance(obj, (deque, list, tuple, set)):
        return [_deep_to_list(v) for v in obj]
    return obj

def sauver_stats_sim(stats_history, transit_times_raw):
    """Écrit data/last_sim.json — lu automatiquement par gradio_app au prochain chat."""
    try:
        data = _deep_to_list(dict(stats_history))
        data["transit_times_raw"] = list(transit_times_raw)
        with open(_LAST_SIM_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        jours = data["time"][-1] / 1440.0 if data.get("time") else 0
        print(f"[INFO] Stats simulation sauvées → last_sim.json ({jours:.1f} j simulés)")
    except Exception as exc:
        print(f"[WARN] Impossible de sauvegarder last_sim.json : {exc}")


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

    Calcul EDD (Earliest Deadline First) :
      - Si deadline absolue présente (t_generation + duree_validite) :
        pct = 1 - slack/duree_totale  →  reflète l'urgence depuis la CRÉATION
        (plus précis que age/validite qui comptait depuis l'arrivée labo)
      - Sinon fallback : age/validite depuis arrivée labo (tubes sans deadline).
    """
    validite = tube.get("duree_validite", 0)
    deadline = tube.get("deadline", 0)
    if deadline > 0 and validite > 0:
        slack = deadline - now                  # temps restant avant péremption
        pct   = max(0.0, 1.0 - slack / validite)  # 0 à la génération → >1 si périmé
    else:
        age  = now - tube.get("arrivee", now)
        pct  = (age / validite) if validite > 0 else 0.0
    age_abs = now - tube.get("t_generation", tube.get("arrivee", now))
    # Urgents : flag absolu 1_000_000 + score intra-urgents amplifié par mult_urgence
    # Non-urgents : score validité + ancienneté seulement
    if tube.get("urgent"):
        return (1_000_000.0
                + (pct * 1_000.0 * mult_validite + age_abs * mult_age) * mult_urgence)
    else:
        return pct * 1_000.0 * mult_validite + age_abs * mult_age


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


class TabLive(_TabLiveGeneration, _TabLiveHeadless, _TabLiveLivraison, _TabLiveMachine,
              _TabLivePathfinding, _TabLiveStats, _TabLiveTechnician, _TabLiveToggle):
    def __init__(self, parent, config_manager, db_manager=None):
        self.parent = parent
        self.config_manager = config_manager
        self.db_manager = db_manager  # optionnel — persiste le journal des épisodes de stress
        self.env = None
        self.running = False
        self._episode_stress_ouvert = None  # {"id", "zone", "tension_max"} pendant VIGILANCE/CRITIQUE
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
        _MX = 43_200  # 60 jours @ 1 pt / 2 min
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
        self.coordinateur = CoordonnateurStress(intervalle_min=15)
        self.stats_tubes_total = 0
        self.tubes_sortis = 0  # Tubes ayant atteint la sortie
        self.transit_times_raw = deque(maxlen=10_000)  # Durées de transit individuelles (minutes réelles)
        self._transit_sum = 0.0       # somme courante pour avg O(1)
        self.transit_times_urgents = deque(maxlen=10_000)  # Idem pour les tubes urgents uniquement
        self.transit_times_normaux = deque(maxlen=10_000)  # Idem pour les tubes non-urgents
        # TAT et préanalyse par type de tube : {type_key: {"normal": deque, "urgent": deque}}
        self.tat_par_type: dict = {}
        # Temps préanalytique par type : {type_key: deque de durées en min réelles}
        self.preanalyse_par_type: dict = {}
        self.headless = False  # True = simulation accélérée sans animation (mode goulots)
        self.turbo = False  # True = 10 pas SimPy par tick (×10 vitesse)
        self.paused = False  # True = simulation gelée (bouton ⏸)
        self._sol_cache = None  # Cache du sol grid, initialisé au lancement de la simulation
        self._machine_cells = set()  # Cases occupées par les machines (obstacles A*)
        self._lab_col_min = 0   # Périmètre labo (calculé depuis sol à l'init du cache)
        self._lab_col_max = 60
        self._lab_row_min = 0
        self._lab_row_max = 40
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
        self.navette_queues:      dict = {}  # {fournisseur_id: [tubes en attente navette]}
        self.navette_stats:       dict = {}  # {fournisseur_id: {en_transit, total_envoye, en_queue}}
        self.navette_en_transit:  dict = {}  # {fournisseur_id: [tubes en cours de trajet]} — données prospectives
        self.anticipation_active: bool = True  # si False, désactive _reequilibrer_pour_rush (utile pour tests)
        # Cache lecture disque pour _analyse_prospective (reset à chaque démarrage de sim)
        self._cache_navette_conf:  dict | None = None
        self._cache_fournisseurs:  dict | None = None
        # ── Réservation de slots machine ──────────────────────────────────────
        # Slots réservés par un tech en transit mais pas encore déposés.
        # Empêche un second tech de prendre la même place de file.
        self.machine_slots_reserved: dict = {}  # {nom_machine: nb_slots_réservés}
        # Garde contre les doublons de traiter_batch_machine.
        # Une machine ne doit jamais avoir deux processus de batch actifs simultanément.
        # Le watchdog et l'auto-restart vérifient ce set avant de spawner.
        self._machines_batch_actif: set = set()
        # Attributs de diagnostic (actifs uniquement en mode DEBUG)
        self._debug_mode: bool = False
        self._debug_entries: deque = deque(maxlen=5000)
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

        self.btn_reset = ttk.Button(self.info_frame, text="⏹ FORCER ARRÊT",
                                    command=self.forcer_arret, width=15)
        self.btn_reset.pack(side=tk.LEFT, padx=5)
        self.btn_reset.config(state="disabled")

        self.btn_turbo = ttk.Button(self.info_frame, text="⚡ ×10", command=self.toggle_turbo, width=7)
        self.btn_turbo.pack(side=tk.LEFT, padx=5)

        self.btn_pause = ttk.Button(self.info_frame, text="⏸ PAUSE",
                                    command=self.toggle_pause, width=10)
        self.btn_pause.pack(side=tk.LEFT, padx=5)
        self.btn_pause.config(state="disabled")

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

        # ── Tableau TAT par type de tube ─────────────────────────────────────
        _tat_outer = ttk.LabelFrame(self.parent,
                                    text="Temps de traitement par type de tube (20 derniers)")
        _tat_outer.pack(fill="x", padx=10, pady=(0, 4))

        _cols = ("type", "theorique", "tat_normal", "tat_urgent", "preanalyse")
        self.treeview_tat = ttk.Treeview(_tat_outer, columns=_cols, show="headings",
                                         height=4, selectmode="none")
        _hdrs = [
            ("type",       "Type de tube",                   160),
            ("theorique",  "Temps théorique",                120),
            ("tat_normal", "TAT moy. normaux (20 dern.)",    160),
            ("tat_urgent", "TAT moy. urgents (20 dern.)",    160),
            ("preanalyse", "Préanalyse moy. (transit)",      160),
        ]
        for col, hdr, w in _hdrs:
            self.treeview_tat.heading(col, text=hdr)
            self.treeview_tat.column(col, width=w, anchor="center", stretch=True)

        _sb = ttk.Scrollbar(_tat_outer, orient="vertical",
                            command=self.treeview_tat.yview)
        self.treeview_tat.configure(yscrollcommand=_sb.set)
        self.treeview_tat.pack(side="left", fill="x", expand=True)
        _sb.pack(side="right", fill="y")

        # Afficher le plan du labo dès l'ouverture (avant de lancer la simulation)
        self.parent.after(50, self.dessiner_labo_complet)

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

        # ── Mise à jour du tableau TAT par type de tube ─────────────────────
        self._maj_tableau_tat()

    def _maj_tableau_tat(self):
        """Recalcule et rafraîchit le Treeview des temps de traitement par type."""

        def _fmt(val_min):
            """Formate une durée en minutes réelles (ex: 3h05 ou 47 min)."""
            if val_min is None:
                return "—"
            v = int(val_min)
            return f"{v // 60}h{v % 60:02d}" if v >= 60 else f"{v} min"

        def _moy20(dq):
            """Retourne la moyenne des 20 dernières valeurs d'une deque, ou None."""
            if not dq:
                return None
            w = list(dq)[-20:]
            return sum(w) / len(w)

        def _temps_theorique(type_key):
            """Somme des durées de protocole pour un type de tube (min réelles)."""
            conf = self.types_tubes.get(type_key, {})
            workflow = conf.get("workflow", [])
            machines = self.config_manager.get_machines()
            total = 0
            for step in workflow:
                for m in machines.values():
                    protos = m.get("protocoles", {})
                    if step in protos:
                        total += protos[step].get("temps", 0)
                        break
            return total

        # Reconstruire toutes les lignes
        tree = self.treeview_tat
        existing = tree.get_children()
        existing_map = {tree.set(iid, "type"): iid for iid in existing}

        for tkey, tconf in self.types_tubes.items():
            label = tconf.get("label") or tconf.get("nom") or tkey
            theorique = _temps_theorique(tkey)

            tat_n_dq  = self.tat_par_type.get(tkey, {}).get("normal")
            tat_u_dq  = self.tat_par_type.get(tkey, {}).get("urgent")
            preana_dq = self.preanalyse_par_type.get(tkey)

            vals = (
                label,
                _fmt(theorique),
                _fmt(_moy20(tat_n_dq)),
                _fmt(_moy20(tat_u_dq)),
                _fmt(_moy20(preana_dq)),
            )

            if tkey in existing_map:
                tree.item(existing_map[tkey], values=vals)
            else:
                tree.insert("", "end", iid=tkey, values=vals)

        # Supprimer les lignes obsolètes (type retiré de la config)
        for iid in existing:
            if tree.set(iid, "type") not in {
                (c.get("label") or c.get("nom") or k)
                for k, c in self.types_tubes.items()
            }:
                tree.delete(iid)


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
            except ValueError as e:
                print(f"[sol] Tuile ignorée, clé malformée '{cle}': {e}")
        
        # Machines
        _COULEURS_MACHINE = {
            "Centrifugeuse":    "#3498db",
            "Automate":         "#e67e22",
            "Paillasse":        "#95a5a6",
            "Incubateur":       "#e91e63",
            "Réfrigérateur":    "#00bcd4",
            "Laveur de plaque": "#009688",
            "Lecteur de plaque":"#4caf50",
            "Bain-marie":       "#ff5722",
            "Agitateur":        "#9c27b0",
            "Microscope":       "#607d8b",
            "Hotte":            "#795548",
            "Congélateur":      "#5c6bc0",
            "ENTREE":           "#2ecc71",
            "SORTIE":           "#e74c3c",
        }
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
                color = _COULEURS_MACHINE["ENTREE"]
            elif typ == "SORTIE":
                color = _COULEURS_MACHINE["SORTIE"]
            else:
                color = _COULEURS_MACHINE.get(typ, "#3498db")

            larg = m.get("largeur_cases", 1)
            haut = m.get("hauteur_cases", 1)
            half_w = larg * 25
            half_h = haut * 25

            rect_id = self.canvas.create_rectangle(x - half_w, y - half_h, x + half_w, y + half_h,
                                                   fill=color, outline="black", width=2)
            if typ not in ("ENTREE", "SORTIE"):
                self.machine_rect_ids[nom] = rect_id
            self.canvas.create_text(x, y + half_h + 10, text=nom, font=theme.FONT_NOTE)

            # Point indicateur (rouge = en travail) — masqué par défaut
            if typ not in ("ENTREE", "SORTIE"):
                ind_id = self.canvas.create_oval(x + half_w - 10, y - half_h,
                                                 x + half_w, y - half_h + 10,
                                                 fill="", outline="", tags=f"ind_{nom}")
                self.machine_indicators[nom] = ind_id

            # --- Labels par machine (sauf SORTIE) ---
            if typ == "ENTREE":
                # ENTREE : un seul label haut (nb tubes en attente à l'entrée)
                self.canvas.create_rectangle(x - 40, y - half_h - 17, x + 40, y - half_h - 2,
                                             fill="white", outline="#27ae60", width=1)
                lbl = self.canvas.create_text(x, y - half_h - 10, text=f"{nom}: 0",
                                              font=theme.FONT_NOTE, fill="#27ae60")
                self.machine_labels[nom] = lbl

            elif typ == "SORTIE":
                # Label SORTIE : compteur de tubes traités
                self.canvas.create_rectangle(x - 40, y - half_h - 17, x + 40, y - half_h - 2,
                                             fill="white", outline="#e74c3c", width=1)
                lbl_s = self.canvas.create_text(x, y - half_h - 10, text="Sortis : 0",
                                                font=theme.FONT_NOTE, fill="#e74c3c")
                self.machine_labels[nom] = lbl_s

            else:
                # --- Label HAUT : nom de la machine ---
                self.canvas.create_rectangle(x - 35, y - half_h - 17, x + 35, y - half_h - 2,
                                             fill="white", outline="gray", width=1)
                lbl_top = self.canvas.create_text(x, y - half_h - 10, text=f"{nom}",
                                                  font=theme.FONT_NOTE, fill="#2c3e50")
                self.machine_labels[nom] = lbl_top

                # --- Label DROITE : file d'attente ---
                self.canvas.create_rectangle(x + half_w + 2, y - 12, x + half_w + 44, y + 12,
                                             fill="#fef9e7", outline="#e67e22", width=1)
                self.canvas.create_text(x + half_w + 23, y - 16, text="Attente",
                                        font=theme.FONT_NOTE, fill="#e67e22")
                lbl_q = self.canvas.create_text(x + half_w + 23, y, text="0",
                                                font=theme.FONT_BODY, fill="#e67e22")
                self.machine_labels_queue[nom] = lbl_q

                # --- Label GAUCHE : tubes traités prêts ---
                self.canvas.create_rectangle(x - half_w - 44, y - 12, x - half_w - 2, y + 12,
                                             fill="#eafaf1", outline="#27ae60", width=1)
                self.canvas.create_text(x - half_w - 23, y - 16, text="Prêts",
                                        font=theme.FONT_NOTE, fill="#27ae60")
                lbl_o = self.canvas.create_text(x - half_w - 23, y, text="0",
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
        """Vérifie si une position est libre (ni COUNTER/WALL ni machine)."""
        if self._sol_cache is None:
            self._init_sol_cache()
        col, row = int(x // 50), int(y // 50)
        cle = f"{col}_{row}"
        if cle in self._sol_cache and self._sol_cache[cle] in ("COUNTER", "WALL"):
            return False
        if (col, row) in self._machine_cells:
            return False
        return True


    # ── Données prospectives ──────────────────────────────────────────────────


    # ──────────────────────────────────────────────────────────────────────
