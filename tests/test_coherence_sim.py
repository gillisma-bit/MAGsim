"""Test de cohérence : mode live (env.step) == mode headless (env.run).

Principe
--------
SimPy garantit que ``env.step()`` répété jusqu'à t=T et ``env.run(until=T)``
parcourent exactement la même file d'événements dans le même ordre.
Ce test vérifie concrètement cette propriété sur le moteur MAGsim :

  - Mode **bulk**      → ``env.run(until=T)``  = ce que fait « Analyse / Goulots »
  - Mode **pas-à-pas** → ``env.step()`` en boucle = ce que fait la simulation live

Pour la même graine aléatoire et la même config, les deux modes doivent
produire des résultats strictement identiques (tubes traités, rejets, dégradés,
arrivées par heure, nombre d'échantillons de stats).

Lancer :
    cd "f:\\code python\\MAGsim"
    python -m pytest tests/test_coherence_sim.py -v
"""

import copy
import random
import threading
import simpy
import pytest
from unittest.mock import MagicMock, patch

from core.config_manager import ConfigManager
from core.technician import TechnicianState

# ─────────────────────────────────────────────────────────────────────────────
#  Config minimale déterministe
#  · profil horaire plat (facteur 1.0 à toute heure) → pas de variation
#  · aucun mauvais prélèvement ni erreur tech → pas de bruit
#  · aucune panne machine (pas de tmep/tmr) → pas de bruit
#  · un seul type de tube, workflow simple (centrifugeuse → sortie)
# ─────────────────────────────────────────────────────────────────────────────
DUREE_TEST = 480  # 8 h en minutes SimPy
SEED = 1234

_CFG = {
    "nom_projet": "test_coherence",
    "machines": {
        "IN": {
            "type": "ENTREE",
            "coords": {"x": 250, "y": 500},
            "capacite": 4,
            "protocoles": {},
            "frequence": 8.0,
            "gamma_k": 1.0,
            "heure_debut": 7.0,
            "pct_mauvais_prelevements": 0.0,
            "profil_horaire": [[0.0, 1.0], [24.0, 1.0]],
        },
        "ct1": {
            "type": "Centrifugeuse",
            "coords": {"x": 250, "y": 400},
            "capacite": 4,
            "file_max": 40,
            "seuil": 1,
            "protocoles": {"centi1": {"temps": 15, "type_compatible": "Centrifugeuse"}},
            # Pas de tmep/tmr → aucune panne
        },
        "OUT": {
            "type": "SORTIE",
            "coords": {"x": 250, "y": 300},
            "capacite": 4,
            "file_max": 100,
            "seuil": 1,
            "protocoles": {},
        },
        "b1": {
            "type": "TECH_OFFICE",
            "coords": {"x": 250, "y": 600},
            "capacite": 4,
            "protocoles": {},
            "nom": "TestTech",
            "experience": 3,
            "age": 35,
            "pct_erreur_tech": 0.0,
            "seuil_charge_fatigue": 0.7,
            "taux_montee_fatigue": 0.01,
            "capacite_max_tubes": 10,
        },
    },
    "sol": {},
    "catalog_protocoles": {},
    "types_tubes": {
        "A": {
            "workflow": ["centi1"],
            "couleur": "#3498db",
            "pct_urgent": 0.0,
            "taille_lot_min": 1,
            "taille_lot_max": 1,
        }
    },
    "personnel": {
        "capacite_journaliere_normale": 150,
        "metres_par_case": 3.0,
        "jour_debut_simulation": 0,
    },
    "horaires": {},
}

# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_cm():
    """ConfigManager en mémoire — aucune I/O fichier."""
    cm = ConfigManager.__new__(ConfigManager)
    cm.filepath = ":memory:"
    cm.data = copy.deepcopy(_CFG)
    return cm


def _make_tab_live(cm):
    """Crée un TabLive avec tous les widgets Tkinter mockés.

    En mode headless, le code est entièrement protégé par ``if not self.headless:``
    donc le canvas n'est jamais appelé d'une façon qui exige un vrai widget.
    """
    mock_canvas = MagicMock()
    mock_canvas.winfo_exists.return_value = False

    with (
        patch("ui.tab_live.tk.Canvas", return_value=mock_canvas),
        patch("ui.tab_live.ttk.Scrollbar", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Frame", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Button", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Label", return_value=MagicMock()),
    ):
        from ui.tab_live import TabLive
        tab = TabLive(MagicMock(), cm)

    tab.canvas = mock_canvas
    return tab


def _extraire_stats(tab):
    """Retourne un dict des métriques comparables."""
    return {
        "tubes_sortis":        tab.tubes_sortis,
        "tubes_rejetes":       tab.tubes_rejetes,
        "tubes_degrades":      tab.tubes_degrades,
        "arrivees_par_heure":  dict(tab.stats_history["arrivees_par_heure"]),
        "n_time_samples":      len(tab.stats_history["time"]),
    }


def _run_bulk(tab, duree, seed):
    """Exécute la simulation en mode bulk (env.run) dans un thread — même moteur
    que l'onglet « Analyse / Goulots »."""
    done = threading.Event()
    tab.lancer_simulation_headless(duree, on_complete=lambda: done.set(), seed=seed)
    assert done.wait(timeout=60), "Timeout : la simulation bulk n'a pas terminé en 60 s"
    return _extraire_stats(tab)


def _init_sim(tab, seed):
    """Initialise l'environnement SimPy sur tab — même logique que lancer_simulation_headless,
    sans démarrer le run. Permet de piloter l'exécution manuellement (mode pas-à-pas)."""
    random.seed(seed)
    tab.headless = True
    tab.running  = True

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
        "rejetes": [], "degrades": [], "pannes": {},
        "distances_tech": {}, "bienetre": {}, "arrivees_par_heure": {},
    }
    tab._jours_connus_dist  = set()
    tab.stats_tubes_total   = 0
    tab.tubes_sortis        = 0
    tab.transit_times_raw   = []
    tab.prochaine_arrivee   = 0
    tab.panne_machines      = set()
    tab.paillasse_analyste  = set()
    tab.machine_repair_events = {}
    tab.tubes_rejetes       = 0
    tab.tubes_degrades      = 0

    config_types = tab.config_manager.data.get("types_tubes", {})
    if config_types:
        tab.types_tubes = config_types

    machines = tab.config_manager.get_machines()
    entrees  = [m for m in machines.values() if m["type"] == "ENTREE"]
    tab.heure_debut_sim = entrees[0].get("heure_debut", 7.0) if entrees else 7.0
    tab._sol_cache = tab.config_manager.data.get("sol", {})

    tech_offices = [(k, m) for k, m in machines.items() if m["type"] == "TECH_OFFICE"]
    if not tech_offices:
        tech_offices = [("tech_0", {"coords": {"x": 125, "y": 125}})]
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
        tech.office_x = office["coords"]["x"]
        tech.office_y = office["coords"]["y"]
        tab.technicians.append(tech)

    tab.env = simpy.Environment()
    tab.env.process(tab.tube_generation())
    for t in tab.technicians:
        tab.env.process(tab.technician_process(t))
    tab.env.process(tab.stats_collector())
    for nom_m, m_conf in machines.items():
        if m_conf.get("tmep") and m_conf.get("tmr"):
            tab.env.process(tab.machine_breakdown_process(nom_m, m_conf))


def _run_stepbystep(tab, duree, seed):
    """Exécute la simulation en mode pas-à-pas (env.step) — même moteur
    que la simulation live (run_sim_loop)."""
    _init_sim(tab, seed)
    try:
        while tab.env.now < duree and tab.running:
            tab.env.step()
    except StopIteration:
        pass
    tab.running = False
    tab.headless = False
    return _extraire_stats(tab)


# ─────────────────────────────────────────────────────────────────────────────
#  Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCoherenceLiveVsHeadless:
    """Vérifie que les deux modes d'exécution SimPy produisent des résultats identiques."""

    @pytest.fixture(autouse=True)
    def _init(self):
        self.cm_bulk  = _make_cm()
        self.cm_step  = _make_cm()
        self.tab_bulk = _make_tab_live(self.cm_bulk)
        self.tab_step = _make_tab_live(self.cm_step)
        self.res_bulk = _run_bulk(self.tab_bulk, DUREE_TEST, SEED)
        self.res_step = _run_stepbystep(self.tab_step, DUREE_TEST, SEED)

    # ── Tubes traités ─────────────────────────────────────────────────────────

    def test_tubes_sortis_identiques(self):
        """Les tubes ayant atteint la sortie doivent être en même nombre."""
        assert self.res_bulk["tubes_sortis"] == self.res_step["tubes_sortis"], (
            f"Bulk={self.res_bulk['tubes_sortis']}  "
            f"Step={self.res_step['tubes_sortis']}"
        )

    def test_tubes_sortis_non_nul(self):
        """Au moins un tube doit avoir été traité (sanity check de la durée)."""
        assert self.res_bulk["tubes_sortis"] > 0

    # ── Rejets et dégradations ────────────────────────────────────────────────

    def test_rejets_identiques(self):
        """Tubes rejetés (mauvais prélèvements + erreurs tech) doivent être identiques."""
        assert self.res_bulk["tubes_rejetes"] == self.res_step["tubes_rejetes"], (
            f"Bulk={self.res_bulk['tubes_rejetes']}  "
            f"Step={self.res_step['tubes_rejetes']}"
        )

    def test_degrades_identiques(self):
        """Tubes dégradés (délai dépassé) doivent être identiques."""
        assert self.res_bulk["tubes_degrades"] == self.res_step["tubes_degrades"], (
            f"Bulk={self.res_bulk['tubes_degrades']}  "
            f"Step={self.res_step['tubes_degrades']}"
        )

    # ── Arrivées par heure ───────────────────────────────────────────────────

    def test_arrivees_par_heure_identiques(self):
        """Le comptage des arrivées par tranche horaire doit être identique."""
        bulk = self.res_bulk["arrivees_par_heure"]
        step = self.res_step["arrivees_par_heure"]
        assert bulk == step, (
            f"Différences : { {k: (bulk.get(k), step.get(k)) for k in set(bulk)|set(step) if bulk.get(k) != step.get(k)} }"
        )

    def test_total_arrivees_coherent(self):
        """Total arrivées/heure == tubes_sortis + tubes_rejetes + tubes en cours."""
        total_aph = sum(self.res_bulk["arrivees_par_heure"].values())
        total_traites = self.res_bulk["tubes_sortis"] + self.res_bulk["tubes_rejetes"]
        # Certains tubes sont encore en transit à la fin → total_aph >= total_traites
        assert total_aph >= total_traites, (
            f"Incohérence : arrivées={total_aph} < traités={total_traites}"
        )

    # ── Statistiques collectées ───────────────────────────────────────────────

    def test_nombre_echantillons_identiques(self):
        """Le stats_collector doit avoir tourné quasiment le même nombre de fois.

        Note : ``env.run(until=T)`` ajoute un événement d'arrêt au temps T qui
        peut précéder dans la file l'événement stats programmé au même instant,
        causant une différence de ±1 par rapport à la boucle ``env.step()``.
        Cette différence de frontière est normale et n'affecte pas les métriques
        métier (tubes traités, rejets, arrivées).
        """
        diff = abs(self.res_bulk["n_time_samples"] - self.res_step["n_time_samples"])
        assert diff <= 1, (
            f"Bulk={self.res_bulk['n_time_samples']}  "
            f"Step={self.res_step['n_time_samples']}  "
            f"diff={diff} (attendu ≤ 1)"
        )

    def test_nombre_echantillons_plausible(self):
        """Le stats_collector tourne toutes les 2 min → ~240 échantillons sur 480 min."""
        n = self.res_bulk["n_time_samples"]
        assert 200 <= n <= 300, f"Nombre d'échantillons inattendu : {n} (attendu ~240)"


class TestDeterminisme:
    """Vérifie que deux runs bulk avec la même graine donnent des résultats identiques."""

    def test_deux_runs_bulk_identiques(self):
        cm1 = _make_cm()
        cm2 = _make_cm()
        tab1 = _make_tab_live(cm1)
        tab2 = _make_tab_live(cm2)
        res1 = _run_bulk(tab1, DUREE_TEST, SEED)
        res2 = _run_bulk(tab2, DUREE_TEST, SEED)
        assert res1["tubes_sortis"]  == res2["tubes_sortis"]
        assert res1["tubes_rejetes"] == res2["tubes_rejetes"]
        assert res1["arrivees_par_heure"] == res2["arrivees_par_heure"]

    def test_graines_differentes_donnent_resultats_differents(self):
        """Deux graines différentes doivent (très probablement) donner des comptages différents."""
        cm1 = _make_cm()
        cm2 = _make_cm()
        tab1 = _make_tab_live(cm1)
        tab2 = _make_tab_live(cm2)
        res1 = _run_bulk(tab1, DUREE_TEST, SEED)
        res2 = _run_bulk(tab2, DUREE_TEST, SEED + 1)
        # Les arrivées totales devraient différer (inter-arrivées random)
        total1 = sum(res1["arrivees_par_heure"].values())
        total2 = sum(res2["arrivees_par_heure"].values())
        assert total1 != total2, (
            "Deux graines différentes ont produit exactement les mêmes arrivals — "
            "le générateur aléatoire est peut-être non fonctionnel."
        )
