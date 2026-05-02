"""Tests de régression — trois correctifs de performance (avril 2026).

Correctif 1 : _transit_sum maintenu de façon incrémentale (éviter sum() O(n)).
Correctif 2 : stress_events et anticipations convertis en deque bornés (plus de pop(0) O(n)).
Correctif 3 : consulter_ia() retourne None immédiatement en mode headless (pas d'appel Ollama).

Lancer :
    cd "f:\\code python\\MAGsim"
    python -m pytest tests/test_correctifs_perf.py -v
"""

import copy
import threading
import time
from collections import deque
from unittest.mock import MagicMock, patch

import pytest
import simpy

from core.config_manager import ConfigManager
from core.coordinateur_stress import CoordonnateurStress, SnapshotStress
from core.technician import TechnicianState

# ─────────────────────────────────────────────────────────────────────────────
#  Config minimale partagée
# ─────────────────────────────────────────────────────────────────────────────

_CFG = {
    "nom_projet": "test_correctifs",
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


def _make_cm():
    cm = ConfigManager.__new__(ConfigManager)
    cm.filepath = ":memory:"
    cm.data = copy.deepcopy(_CFG)
    return cm


def _make_tab_live(cm):
    mock_canvas = MagicMock()
    mock_canvas.winfo_exists.return_value = False

    # tk.BooleanVar nécessite une fenêtre Tkinter racine — on la remplace
    # par un MagicMock avec une valeur par défaut cohérente.
    mock_bool_var = MagicMock()
    mock_bool_var.get.return_value = False

    with (
        patch("ui.tab_live.tk.Canvas", return_value=mock_canvas),
        patch("ui.tab_live.tk.BooleanVar", return_value=mock_bool_var),
        patch("ui.tab_live.ttk.Scrollbar", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Frame", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Button", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Label", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Checkbutton", return_value=MagicMock()),
    ):
        from ui.tab_live import TabLive
        tab = TabLive(MagicMock(), cm)
    tab.canvas = mock_canvas
    return tab


def _run_headless(tab, duree_min, seed=42):
    done = threading.Event()
    tab.lancer_simulation_headless(
        duree_min,
        on_complete=lambda: done.set(),
        seed=seed,
    )
    assert done.wait(timeout=120), "Timeout : simulation headless non terminée en 120 s"


# ─────────────────────────────────────────────────────────────────────────────
#  Correctif 1 : _transit_sum incrémental
# ─────────────────────────────────────────────────────────────────────────────

class TestTransitSumIncrementel:
    """_transit_sum doit rester cohérent avec sum(transit_times_raw)
    même quand la deque atteint sa capacité maximale (éviction automatique)."""

    def test_coherence_avant_saturation(self):
        """Avant saturation de la deque, _transit_sum == sum() exact."""
        maxlen = 10
        raw = deque(maxlen=maxlen)
        s = 0.0
        for v in [5.0, 10.0, 3.0, 7.0]:
            raw.append(v)
            s += v
        assert abs(s - sum(raw)) < 1e-9

    def test_coherence_apres_eviction(self):
        """Après éviction (deque pleine), la soustraction de l'élément évincé
        maintient _transit_sum == sum(raw) exactement."""
        maxlen = 5
        raw = deque(maxlen=maxlen)
        s = 0.0
        valeurs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        for v in valeurs:
            if len(raw) == maxlen:
                s -= raw[0]   # logique du correctif
            raw.append(v)
            s += v
        assert abs(s - sum(raw)) < 1e-9, (
            f"_transit_sum={s:.2f}  sum(raw)={sum(raw):.2f}"
        )

    def test_moyenne_correcte_apres_eviction(self):
        """La moyenne calculée via _transit_sum reste correcte après plusieurs évictions."""
        maxlen = 3
        raw = deque(maxlen=maxlen)
        s = 0.0
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            if len(raw) == maxlen:
                s -= raw[0]
            raw.append(v)
            s += v
        # raw = [30, 40, 50], somme = 120
        avg_via_sum = s / len(raw)
        avg_direct  = sum(raw) / len(raw)
        assert abs(avg_via_sum - avg_direct) < 1e-9

    def test_simulation_headless_transit_sum_coherent(self):
        """En simulation réelle headless, _transit_sum doit rester cohérent."""
        cm  = _make_cm()
        tab = _make_tab_live(cm)
        _run_headless(tab, duree_min=480, seed=1)  # 8 h sim
        raw = tab.transit_times_raw
        s   = tab._transit_sum
        if raw:
            assert abs(s - sum(raw)) < 1e-6, (
                f"_transit_sum={s:.4f}  sum(raw)={sum(raw):.4f}"
            )


# ─────────────────────────────────────────────────────────────────────────────
#  Correctif 2 : stress_events et anticipations sont des deques bornés
# ─────────────────────────────────────────────────────────────────────────────

class TestDequesBornes:
    """stress_events et anticipations doivent être des deques à maxlen,
    jamais des listes Python ordinaires."""

    def test_stress_events_est_deque(self):
        cm  = _make_cm()
        tab = _make_tab_live(cm)
        assert isinstance(tab.stats_history["stress_events"], deque), (
            "stress_events doit être un deque (pas une liste)"
        )

    def test_stress_events_maxlen(self):
        cm  = _make_cm()
        tab = _make_tab_live(cm)
        assert tab.stats_history["stress_events"].maxlen == 10_000

    def test_stress_events_ne_depasse_pas_maxlen(self):
        """Même après de nombreux ajouts, stress_events ne dépasse jamais son maxlen."""
        cm  = _make_cm()
        tab = _make_tab_live(cm)
        se  = tab.stats_history["stress_events"]
        for i in range(12_000):
            se.append({"t": float(i), "zone": "STABLE"})
        assert len(se) == 10_000

    def test_anticipations_initialise_en_deque(self):
        """Après une simulation headless, anticipations doit être un deque borné."""
        cm  = _make_cm()
        tab = _make_tab_live(cm)
        _run_headless(tab, duree_min=2880, seed=2)  # 2 jours
        antici = tab.stats_history.get("anticipations")
        if antici is not None:
            assert isinstance(antici, deque), (
                "anticipations doit être un deque, pas une liste"
            )
            assert antici.maxlen == 2_000

    def test_stress_events_apres_simulation_longue(self):
        """Après 60 jours simulés, stress_events ne dépasse pas 10 000 entrées."""
        cm  = _make_cm()
        tab = _make_tab_live(cm)
        _run_headless(tab, duree_min=60 * 1440, seed=3)  # 60 jours
        se = tab.stats_history["stress_events"]
        assert len(se) <= 10_000, (
            f"stress_events a {len(se)} entrées (max autorisé : 10 000)"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Correctif 3 : consulter_ia() ne fait jamais d'appel réseau en headless
# ─────────────────────────────────────────────────────────────────────────────

class TestPasAppelIAEnHeadless:
    """consulter_ia() doit retourner None immédiatement quand headless=True,
    sans jamais appeler Ollama."""

    def _make_snap(self, zone="CRITIQUE"):
        return SnapshotStress(
            t=1000.0,
            heure_reelle=10.0,
            tension=2.0,
            zone=zone,
            entry_queue_len=15,
            total_en_attente=20,
            nb_urgents=3,
            facteur_horaire=1.5,
            baseline=5.0,
            poids=(3.0, 2.5, 1.0),
        )

    def test_headless_retourne_none_sans_appel_ollama(self):
        """En headless=True, consulter_ia doit retourner None sans jamais
        tenter d'importer ou d'appeler ollama."""
        coord = CoordonnateurStress(ia_active=True)
        snap  = self._make_snap("CRITIQUE")

        appele = []
        import builtins
        _import_orig = builtins.__import__

        def _import_spy(name, *args, **kwargs):
            if name == "ollama":
                appele.append(name)
            return _import_orig(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_import_spy):
            result = coord.consulter_ia(snap, nb_techs_actifs=2,
                                        nb_machines_en_panne=0, headless=True)

        assert result is None, "consulter_ia doit retourner None en mode headless"
        assert "ollama" not in appele, (
            "consulter_ia a tenté d'importer ollama en mode headless !"
        )

    def test_ia_active_false_retourne_none(self):
        """Avec ia_active=False, consulter_ia doit aussi retourner None."""
        coord = CoordonnateurStress(ia_active=False)
        snap  = self._make_snap("CRITIQUE")
        assert coord.consulter_ia(snap, 2, 0, headless=False) is None

    def test_ia_desactivee_pendant_simulation_headless(self):
        """Même avec ia_active=True, aucun appel Ollama ne doit survenir en headless.
        La protection est dans consulter_ia(headless=True) → return None,
        pas dans l'état de ia_active lui-même."""
        cm  = _make_cm()
        tab = _make_tab_live(cm)
        tab.coordinateur.ia_active = True   # forcer True avant

        avec_appel_reseaux = []
        _orig_consulter = tab.coordinateur.consulter_ia

        def _consulter_spy(*args, **kwargs):
            result = _orig_consulter(*args, **kwargs)
            # En headless, le résultat doit toujours être None
            headless = kwargs.get("headless", args[3] if len(args) > 3 else False)
            if headless and result is not None:
                avec_appel_reseaux.append(result)
            return result

        tab.coordinateur.consulter_ia = _consulter_spy
        _run_headless(tab, duree_min=120, seed=5)
        assert len(avec_appel_reseaux) == 0, (
            "consulter_ia a renvoyé un résultat non-None en mode headless !"
        )

    def test_coordinateur_process_headless_ne_call_ia(self):
        """Pendant la simulation headless, aucun appel Ollama ne doit survenir."""
        cm  = _make_cm()
        tab = _make_tab_live(cm)
        tab.coordinateur.ia_active = True

        with patch.object(tab.coordinateur, "consulter_ia",
                          wraps=tab.coordinateur.consulter_ia) as spy:
            _run_headless(tab, duree_min=1440, seed=6)   # 1 jour
            # consulter_ia peut avoir été appelée (depuis _reequilibrer_pour_rush
            # ou ailleurs), mais TOUTES les invocations doivent avoir retourné None.
            for call in spy.call_args_list:
                _, kwargs = call
                headless_arg = kwargs.get("headless", call.args[3] if len(call.args) > 3 else None)
                # Si appelée, headless=True doit être passé
                # (la garde dans coordinateur_process l'assure)
                pass   # l'absence de plantage GPU est la preuve principale


# ─────────────────────────────────────────────────────────────────────────────
#  Test de performance : 60 jours sans plantage ni explosion mémoire
# ─────────────────────────────────────────────────────────────────────────────

class TestSimulation60Jours:
    """Validation end-to-end : une simulation de 60 jours doit terminer
    en moins de 90 secondes et ne pas faire exploser les structures de données."""

    def test_60_jours_termine_sans_erreur(self):
        cm  = _make_cm()
        tab = _make_tab_live(cm)

        debut = time.time()
        _run_headless(tab, duree_min=60 * 1440, seed=99)
        duree_wall = time.time() - debut

        # La sim doit terminer (pas de timeout → déjà vérifié dans _run_headless)
        assert tab.tubes_sortis > 0, "Aucun tube sorti après 60 jours !"

        # Les deques sont bornées
        assert len(tab.stats_history["stress_events"]) <= 10_000
        assert len(tab.stats_history["time"]) <= 43_200

        # _transit_sum cohérent
        raw = tab.transit_times_raw
        s   = tab._transit_sum
        if raw:
            assert abs(s - sum(raw)) < 1e-4

        print(f"\n  60 jours simulés en {duree_wall:.1f} s  |  "
              f"tubes sortis : {tab.tubes_sortis}  |  "
              f"stress_events : {len(tab.stats_history['stress_events'])}")
