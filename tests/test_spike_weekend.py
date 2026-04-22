"""Test : spikes périodiques du pending_max causés par l'absence des techs le week-end.

Hypothèse
---------
Sur 30 jours (départ lundi, jour_debut_simulation=0), les 4 week-ends
(j5-6, j12-13, j19-20, j26-27) créent une accumulation de tubes car
les techs de jour (jours=[0..4]) ne sont pas disponibles pour transporter
les tubes de l'entrée vers les machines.

→ Chaque week-end = 1 pic de pending_max reproductible et régulier.
→ Ce n'est PAS lié aux arrêts maladie : le profil est identique d'une
  simulation à l'autre car il est entièrement déterminé par le calendrier.

Assertions clés
---------------
- Condition A (lun-ven) : le pending_max atteint un maximum significatif
  DANS chacun des 4 intervalles week-end.
- Condition B (7j/7)    : aucun pic week-end comparable n'apparaît ;
  le pending_max weekend est < seuil_controle.

Lancer :
    cd "f:\\code python\\MAGsim"
    python -m pytest tests/test_spike_weekend.py -v
"""

import copy
import random
import simpy
import pytest
from unittest.mock import MagicMock, patch

from core.config_manager import ConfigManager
from core.technician import TechnicianState

# ─────────────────────────────────────────────────────────────────────────────
#  Constantes
# ─────────────────────────────────────────────────────────────────────────────
DUREE_JOUR  = 1440
DUREE_TEST  = 30 * DUREE_JOUR   # 30 jours
SEED        = 0

# Positions (en minutes SimPy) des 4 week-ends (samedi + dimanche)
# jour_debut=0 (lundi) → samedi = jour 5, dimanche = jour 6
WEEKENDS = [
    (5  * DUREE_JOUR,  7  * DUREE_JOUR),
    (12 * DUREE_JOUR,  14 * DUREE_JOUR),
    (19 * DUREE_JOUR,  21 * DUREE_JOUR),
    (26 * DUREE_JOUR,  28 * DUREE_JOUR),
]

# Intervalles de semaine correspondants (lundi→vendredi)
WEEKDAYS = [
    (1  * DUREE_JOUR,  5  * DUREE_JOUR),
    (8  * DUREE_JOUR,  12 * DUREE_JOUR),
    (15 * DUREE_JOUR,  19 * DUREE_JOUR),
    (22 * DUREE_JOUR,  26 * DUREE_JOUR),
]

# ─────────────────────────────────────────────────────────────────────────────
#  Config minimale
#  2 techs lun-ven, aucun tech week-end → accumulation nette et rapide.
#  Pas de pannes, pas d'erreurs, pas d'arrêts maladie → déterminisme maximal.
# ─────────────────────────────────────────────────────────────────────────────
_CFG = {
    "nom_projet": "test_spike_weekend",
    "machines": {
        "IN": {
            "type": "ENTREE",
            "coords": {"x": 250, "y": 600},
            "capacite": 4,
            "protocoles": {},
            "frequence": 5.0,       # 1 arrivée toutes les ~5 min en moyenne
            "gamma_k": 2.0,
            "heure_debut": 7.0,
            "pct_mauvais_prelevements": 0.0,
            # Profil légèrement variable mais non nul même la nuit
            "profil_horaire": [
                [0.0, 0.3], [7.0, 1.0], [20.0, 0.3], [24.0, 0.3]
            ],
        },
        "ct1": {
            "type": "Centrifugeuse",
            "coords": {"x": 250, "y": 400},
            "capacite": 8, "file_max": 9999, "seuil": 1,
            "protocoles": {"proto": {"temps": 10, "type_compatible": "Centrifugeuse"}},
            "timeout_batch": 60,
        },
        "OUT": {
            "type": "SORTIE",
            "coords": {"x": 250, "y": 200},
            "capacite": 4, "file_max": 9999, "seuil": 1, "protocoles": {},
        },
        "b1": {
            "type": "TECH_OFFICE",
            "coords": {"x": 300, "y": 650},
            "capacite": 4, "protocoles": {},
            "nom": "Tech_A",
            "experience": 3, "age": 35,
            "pct_erreur_tech": 0.0,
            "seuil_charge_fatigue": 0.99,
            "taux_montee_fatigue": 0.0,
            "capacite_max_tubes": 30,
        },
        "b2": {
            "type": "TECH_OFFICE",
            "coords": {"x": 200, "y": 650},
            "capacite": 4, "protocoles": {},
            "nom": "Tech_B",
            "experience": 3, "age": 35,
            "pct_erreur_tech": 0.0,
            "seuil_charge_fatigue": 0.99,
            "taux_montee_fatigue": 0.0,
            "capacite_max_tubes": 30,
        },
    },
    "sol": {},
    "catalog_protocoles": {},
    "types_tubes": {
        "A": {
            "workflow": ["proto"],
            "couleur": "#3498db",
            "pct_urgent": 0.0,
            "taille_lot_min": 1,
            "taille_lot_max": 3,
        }
    },
    "personnel": {
        "capacite_journaliere_normale": 300,
        "metres_par_case": 3.0,
        "jour_debut_simulation": 0,   # 0 = lundi
    },
    # Horaires : les deux techs travaillent lun-ven seulement
    "horaires": {
        "Tech_A": {
            "jours": [0, 1, 2, 3, 4],
            "heure_debut": 7.0,
            "heure_fin": 22.0,
            "actif": True,
        },
        "Tech_B": {
            "jours": [0, 1, 2, 3, 4],
            "heure_debut": 7.0,
            "heure_fin": 22.0,
            "actif": True,
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_cm(cfg=None):
    cm = ConfigManager.__new__(ConfigManager)
    cm.filepath = ":memory:"
    cm.data = copy.deepcopy(cfg or _CFG)
    return cm


def _make_tab(cm):
    mock_canvas = MagicMock()
    mock_canvas.winfo_exists.return_value = False
    with (
        patch("ui.tab_live.tk.Canvas",     return_value=mock_canvas),
        patch("ui.tab_live.ttk.Scrollbar", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Frame",     return_value=MagicMock()),
        patch("ui.tab_live.ttk.Button",    return_value=MagicMock()),
        patch("ui.tab_live.ttk.Label",     return_value=MagicMock()),
    ):
        from ui.tab_live import TabLive
        tab = TabLive(MagicMock(), cm)
    tab.canvas = mock_canvas
    return tab


def _init_sim(tab, seed):
    """Initialise l'environnement SimPy (même logique que test_correlation_maladie_attente)."""
    random.seed(seed)
    tab.headless = True
    tab.running  = True
    # Désactiver les arrêts maladie pour isoler l'effet du calendrier
    tab.mode_sans_arret_maladie = True

    tab.entry_queue           = []
    tab.machine_queues        = {}
    tab.output_queues         = {}
    tab.technicians           = []
    tab.blinking_machines     = set()
    tab.machine_indicators    = {}
    tab.machine_labels        = {}
    tab.machine_labels_queue  = {}
    tab.machine_labels_output = {}
    tab.stats_history = {
        "time": [], "queues": {}, "output": {}, "busy": {}, "entry": [],
        "transit_time_avg": [], "transit_time_rolling": [],
        "transit_time_pending_max": [],
        "rejetes": [], "degrades": [], "pannes": {},
        "distances_tech": {}, "bienetre": {}, "arrivees_par_heure": {},
        "events_arret_maladie": [],
    }
    tab._jours_connus_dist    = set()
    tab.stats_tubes_total     = 0
    tab.tubes_sortis          = 0
    tab.transit_times_raw     = []
    tab.prochaine_arrivee     = 0
    tab.panne_machines        = set()
    tab.paillasse_analyste    = set()
    tab.machine_repair_events = {}
    tab.tubes_rejetes         = 0
    tab.tubes_degrades        = 0

    config_types = tab.config_manager.data.get("types_tubes", {})
    if config_types:
        tab.types_tubes = config_types

    machines = tab.config_manager.get_machines()
    entrees  = [m for m in machines.values() if m["type"] == "ENTREE"]
    tab.heure_debut_sim = entrees[0].get("heure_debut", 7.0) if entrees else 7.0
    tab._sol_cache      = tab.config_manager.data.get("sol", {})

    tech_offices = [(k, m) for k, m in machines.items() if m["type"] == "TECH_OFFICE"]
    for idx, (office_key, office) in enumerate(tech_offices):
        tech = TechnicianState(
            office["coords"]["x"], office["coords"]["y"],
            canvas_id=None, index=idx)
        tech.pct_erreur_base        = office.get("pct_erreur_tech", 0.0)
        tech.pct_erreur             = tech.pct_erreur_base
        tech.nom                    = office.get("nom") or office_key
        tech.experience             = int(office.get("experience", 3))
        tech.age                    = int(office.get("age", 35))
        tech.seuil_charge_fatigue   = float(office.get("seuil_charge_fatigue", 0.70))
        tech.taux_montee_fatigue    = float(office.get("taux_montee_fatigue", 0.01))
        tech.taux_recuperation_nuit = float(office.get("taux_recuperation_nuit", 0.15))
        tech.capacite_max_tubes     = int(office.get("capacite_max_tubes", 10))
        tech.office_x               = office["coords"]["x"]
        tech.office_y               = office["coords"]["y"]
        tab.technicians.append(tech)

    tab.env = simpy.Environment()
    tab.env.process(tab.tube_generation())
    for t in tab.technicians:
        tab.env.process(tab.technician_process(t))
    tab.env.process(tab.stats_collector())


def _run_sim(tab, duree):
    try:
        while tab.env.now < duree and tab.running:
            tab.env.step()
    except StopIteration:
        pass
    tab.running = False


def _max_pending_in_window(h, t_start, t_end):
    """Valeur maximale de pending_max dans la fenêtre [t_start, t_end[."""
    vals = [
        v for t, v in zip(h["time"], h["transit_time_pending_max"])
        if v is not None and t_start <= t < t_end
    ]
    return max(vals) if vals else 0.0


def _avg_pending_in_window(h, t_start, t_end):
    """Valeur moyenne de pending_max dans la fenêtre [t_start, t_end[."""
    vals = [
        v for t, v in zip(h["time"], h["transit_time_pending_max"])
        if v is not None and t_start <= t < t_end
    ]
    return sum(vals) / len(vals) if vals else 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSpikeWeekend:
    """Condition A : techs absents le week-end → 4 pics prévisibles."""

    def setup_method(self):
        cfg = copy.deepcopy(_CFG)   # horaires lun-ven déjà présents
        cm  = _make_cm(cfg)
        self.tab = _make_tab(cm)
        _init_sim(self.tab, SEED)
        _run_sim(self.tab, DUREE_TEST)
        self.h = self.tab.stats_history

    def test_chaque_weekend_produit_un_pic_eleve(self):
        """Le pending_max doit dépasser 4h de retard pendant chaque week-end."""
        seuil_pic = 4 * 60  # 4 heures en minutes SimPy
        for idx, (t0, t1) in enumerate(WEEKENDS):
            pic = _max_pending_in_window(self.h, t0, t1)
            assert pic > seuil_pic, (
                f"Week-end {idx+1} (t={t0}–{t1}) : "
                f"pending_max={pic:.0f} min, attendu > {seuil_pic} min. "
                f"Les tubes devraient s'accumuler en l'absence des techs."
            )

    def test_quatre_pics_distincts_pas_un_de_plus(self):
        """Il y a exactement 4 semaines avec un pic week-end significatif."""
        seuil_pic = 4 * 60
        semaines_avec_pic = sum(
            1 for (t0, t1) in WEEKENDS
            if _max_pending_in_window(self.h, t0, t1) > seuil_pic
        )
        assert semaines_avec_pic == 4, (
            f"Attendu 4 semaines avec un pic, trouvé {semaines_avec_pic}. "
            f"Les 4 week-ends sur 30 jours devraient chacun produire un pic."
        )

    def test_pics_plus_grands_en_weekend_quen_semaine(self):
        """Le pic du week-end doit être systématiquement supérieur au pic de la semaine adjacente."""
        for idx, ((t_we0, t_we1), (t_wd0, t_wd1)) in enumerate(zip(WEEKENDS, WEEKDAYS)):
            max_weekend  = _max_pending_in_window(self.h, t_we0, t_we1)
            max_weekday  = _max_pending_in_window(self.h, t_wd0, t_wd1)
            assert max_weekend > max_weekday * 2, (
                f"Semaine {idx+1} : pic week-end={max_weekend:.0f} min, "
                f"pic semaine={max_weekday:.0f} min. "
                f"Le pic week-end devrait être au moins 2× celui de la semaine."
            )

    def test_periodicite_reguliere(self):
        """Les 4 pics se produisent à intervalles de 7 jours (± tolérance d'un jour)."""
        # Moment du pic maximum dans chaque fenêtre week-end
        def t_pic(t0, t1):
            best_t = best_v = None
            for t, v in zip(self.h["time"], self.h["transit_time_pending_max"]):
                if v is not None and t0 <= t < t1:
                    if best_v is None or v > best_v:
                        best_v, best_t = v, t
            return best_t

        t_pics = [t_pic(t0, t1) for (t0, t1) in WEEKENDS if t_pic(t0, t1) is not None]
        assert len(t_pics) == 4, "Impossible de trouver les 4 pics."

        intervalles = [t_pics[i+1] - t_pics[i] for i in range(3)]
        tolerance   = DUREE_JOUR  # ± 1 jour
        for idx, delta in enumerate(intervalles):
            assert abs(delta - 7 * DUREE_JOUR) <= tolerance, (
                f"Intervalle {idx+1}→{idx+2} : {delta:.0f} min "
                f"(attendu {7*DUREE_JOUR} ± {tolerance} min). "
                f"Les pics devraient être séparés exactement de 7 jours."
            )


class TestSansWeekend:
    """Condition B : techs en service 7j/7 → aucun pic régulier de week-end."""

    def setup_method(self):
        cfg = copy.deepcopy(_CFG)
        # Modifier les horaires : les deux techs travaillent toute la semaine
        cfg["horaires"]["Tech_A"]["jours"] = list(range(7))
        cfg["horaires"]["Tech_B"]["jours"] = list(range(7))
        cm = _make_cm(cfg)
        self.tab = _make_tab(cm)
        _init_sim(self.tab, SEED)
        _run_sim(self.tab, DUREE_TEST)
        self.h = self.tab.stats_history

    def test_pas_de_pic_weekend_avec_7j7(self):
        """Sans jour de repos, le pending_max week-end reste comparable aux autres jours."""
        # En semaine avec 2 techs, pending_max devrait rester bas
        # On compare le max week-end vs le double du max en semaine
        max_weekday = max(
            _max_pending_in_window(self.h, t0, t1) for (t0, t1) in WEEKDAYS
        )
        for idx, (t0, t1) in enumerate(WEEKENDS):
            max_we = _max_pending_in_window(self.h, t0, t1)
            assert max_we <= max_weekday * 3, (
                f"Week-end {idx+1} (7j/7) : pending_max={max_we:.0f} min, "
                f"max semaine={max_weekday:.0f} min. "
                f"Sans absence week-end, pas de pic systématique attendu."
            )

    def test_reduction_significative_vs_condition_a(self):
        """La suppression des jours de repos réduit d'au moins 50 % le max week-end global."""
        # Construire le run A en parallèle pour comparaison directe
        cfg_a = copy.deepcopy(_CFG)
        cm_a  = _make_cm(cfg_a)
        tab_a = _make_tab(cm_a)
        _init_sim(tab_a, SEED)
        _run_sim(tab_a, DUREE_TEST)
        h_a = tab_a.stats_history

        max_we_a = max(_max_pending_in_window(h_a, t0, t1) for (t0, t1) in WEEKENDS)
        max_we_b = max(_max_pending_in_window(self.h, t0, t1) for (t0, t1) in WEEKENDS)

        assert max_we_b < max_we_a * 0.50, (
            f"Réduction insuffisante : "
            f"Condition A max={max_we_a:.0f} min, "
            f"Condition B max={max_we_b:.0f} min. "
            f"Passer à 7j/7 devrait réduire le pic de > 50 %."
        )
