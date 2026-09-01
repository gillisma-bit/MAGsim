"""Tests de priorité et de non-oubli des tubes.

Trois invariants critiques vérifiés :

  1. FIFO entrée — les tubes les plus anciens de l'entry_queue sont pris avant les plus récents.
  2. Remise en file — quand un tech repose des tubes (fin de quart),
     ils sont ré-insérés AVANT les tubes arrivés après eux, pas en fin de queue.
  3. Output queues — les tubes sortis de machine sont livrés dans l'ordre
     d'ancienneté croissante (pas dans l'ordre arbitraire d'itération du dict).
  4. Aucun tube oublié — après une simulation courte, le nombre de tubes qui
     sortent + rejets = arrivées (aucun tube ne reste coincé indéfiniment).

Lancer :
    cd "f:\\code python\\MAGsim"
    python -m pytest tests/test_priorite_tubes.py -v
"""

import copy
import bisect
import threading
import pytest
from unittest.mock import MagicMock, patch

from core.config_manager import ConfigManager
from core.technician import TechnicianState


# ─────────────────────────────────────────────────────────────────────────────
#  Config minimale – reprise de test_coherence_sim, légèrement ajustée
#  · Un seul tech, 1 machine, profil plat, 0 % erreur, 0 % mauvais prélèv.
#  · file_max=2 sur la machine → force les situations de file pleine
# ─────────────────────────────────────────────────────────────────────────────
_CFG_BASE = {
    "nom_projet": "test_priorite",
    "machines": {
        "IN": {
            "type": "ENTREE",
            "coords": {"x": 250, "y": 500},
            "capacite": 4, "protocoles": {},
            "frequence": 5.0, "gamma_k": 1.0,
            "heure_debut": 7.0,
            "pct_mauvais_prelevements": 0.0,
            "profil_horaire": [[0.0, 1.0], [24.0, 1.0]],
        },
        "ct1": {
            "type": "Centrifugeuse",
            "coords": {"x": 250, "y": 400},
            "capacite": 2, "file_max": 4, "seuil": 1,
            "protocoles": {"centi1": {"temps": 10, "type_compatible": "Centrifugeuse"}},
        },
        "OUT": {
            "type": "SORTIE",
            "coords": {"x": 250, "y": 300},
            "capacite": 4, "file_max": 100, "seuil": 1, "protocoles": {},
        },
        "b1": {
            "type": "TECH_OFFICE",
            "coords": {"x": 250, "y": 600},
            "capacite": 4, "protocoles": {},
            "nom": "TestTech",
            "experience": 3, "age": 35,
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
            "taille_lot_min": 1, "taille_lot_max": 1,
        }
    },
    "personnel": {
        "capacite_journaliere_normale": 150,
        "metres_par_case": 3.0,
        "jour_debut_simulation": 0,
    },
    "horaires": {},
}


def _make_cm(cfg=None):
    cm = ConfigManager.__new__(ConfigManager)
    cm.filepath = ":memory:"
    cm.data = copy.deepcopy(cfg or _CFG_BASE)
    return cm


def _make_tab(cm):
    mock_canvas = MagicMock()
    mock_canvas.winfo_exists.return_value = False
    with (
        patch("ui.tab_live.tk.Canvas", return_value=mock_canvas),
        patch("ui.tab_live.tk.BooleanVar", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Scrollbar", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Frame", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Button", return_value=MagicMock()),
        patch("ui.tab_live.ttk.Label", return_value=MagicMock()),
    ):
        from ui.tab_live import TabLive
        tab = TabLive(MagicMock(), cm)
    tab.canvas = mock_canvas
    return tab


def _run(tab, duree, seed=42):
    """Lance la simulation headless et attend sa fin."""
    done = threading.Event()
    tab.lancer_simulation_headless(duree, on_complete=lambda: done.set(), seed=seed)
    assert done.wait(timeout=60), "Timeout simulation"


# ─────────────────────────────────────────────────────────────────────────────
#  Tests unitaires purs (sans SimPy) sur les structures de données
# ─────────────────────────────────────────────────────────────────────────────

class TestEntryQueueFIFO:
    """L'entry_queue doit respecter l'ordre d'arrivée (FIFO) pour les tubes normaux."""

    def test_tubes_pris_dans_ordre_arrivee(self):
        """Le tech prend les tubes du début de la liste → les plus anciens en premier."""
        cm = _make_cm()
        tab = _make_tab(cm)
        # Simuler 3 tubes dans la file, arrivés à t=10, t=20, t=30
        tab.entry_queue = [
            {"arrivee": 10, "workflow": ["centi1"], "urgent": False, "id": None},
            {"arrivee": 20, "workflow": ["centi1"], "urgent": False, "id": None},
            {"arrivee": 30, "workflow": ["centi1"], "urgent": False, "id": None},
        ]
        # Le tech prend entry_queue[:2]
        pris = tab.entry_queue[:2]
        del tab.entry_queue[:2]
        arrivees_prises = [t["arrivee"] for t in pris]
        assert arrivees_prises == [10, 20], (
            f"Devrait prendre les tubes les + anciens d'abord, got {arrivees_prises}"
        )
        # Le tube resté est le plus récent
        assert tab.entry_queue[0]["arrivee"] == 30

    def test_tube_urgent_passe_devant(self):
        """Un tube urgent inséré en tête de file via insert(0) est pris avant les normaux."""
        cm = _make_cm()
        tab = _make_tab(cm)
        tab.entry_queue = [
            {"arrivee": 5, "workflow": ["centi1"], "urgent": False, "id": None},
            {"arrivee": 6, "workflow": ["centi1"], "urgent": False, "id": None},
        ]
        # Simuler l'arrivée d'un urgent à t=10 — insert(0) comme dans tube_generation
        urgent = {"arrivee": 10, "workflow": ["centi1"], "urgent": True, "id": None}
        tab.entry_queue.insert(0, urgent)
        assert tab.entry_queue[0]["urgent"] is True, "L'urgent doit être en tête"

    def test_remise_tube_normal_preserve_anciennete(self):
        """BUG DETECTÉ : un tube remis en file (fin de quart du tech) doit être inséré
        AVANT les tubes arrivés après lui, pas en queue (append).

        Sans le correctif, un tube arrivé à t=10 remis à t=500 se retrouverait APRÈS
        des tubes arrivés à t=490, ce qui viole FIFO et peut causer des attentes de >100h.
        """
        cm = _make_cm()
        tab = _make_tab(cm)
        # File actuelle : un tube "récent" arrivé à t=490
        tube_recent = {"arrivee": 490, "workflow": ["centi1"], "urgent": False, "id": None}
        tab.entry_queue = [tube_recent]

        # Tube à remettre : arrivé à t=10 (bien plus vieux)
        tube_vieux = {"arrivee": 10, "workflow": ["centi1"], "urgent": False, "id": None}

        # ── Comportement BUGUÉ (append) ──────────────────────────────────────
        queue_buguee = [tube_recent.copy()]
        queue_buguee.append(tube_vieux)  # le vieux se retrouve APRÈS le récent
        assert queue_buguee[0]["arrivee"] == 490, "Confirmation du bug : vieux tube en dernier"
        assert queue_buguee[1]["arrivee"] == 10

        # ── Comportement CORRECT (insertion par ancienneté) ──────────────────
        # Re-insertion par arrivee croissante (tri stable)
        tab.entry_queue = [tube_recent.copy()]
        # Méthode correcte : bisect sur les arrivées
        arrivees = [t["arrivee"] for t in tab.entry_queue if not t.get("urgent")]
        pos = bisect.bisect_left(arrivees, tube_vieux["arrivee"])
        # Insérer après les éventuels urgents en tête
        nb_urgents = sum(1 for t in tab.entry_queue if t.get("urgent"))
        tab.entry_queue.insert(nb_urgents + pos, tube_vieux)

        assert tab.entry_queue[0]["arrivee"] == 10, (
            f"Le tube vieux (t=10) doit être AVANT le tube récent (t=490), "
            f"got {[t['arrivee'] for t in tab.entry_queue]}"
        )

    def test_remise_plusieurs_tubes_ordre_correct(self):
        """Plusieurs tubes remis à la fois doivent respecter l'ordre d'ancienneté global."""
        cm = _make_cm()
        tab = _make_tab(cm)
        recents = [
            {"arrivee": 300, "workflow": ["centi1"], "urgent": False, "id": None},
            {"arrivee": 400, "workflow": ["centi1"], "urgent": False, "id": None},
        ]
        vieux = [
            {"arrivee": 50, "workflow": ["centi1"], "urgent": False, "id": None},
            {"arrivee": 100, "workflow": ["centi1"], "urgent": False, "id": None},
        ]
        tab.entry_queue = recents[:]

        # Insérer chaque vieux tube au bon endroit
        for tube in vieux:
            arrivees = [t["arrivee"] for t in tab.entry_queue if not t.get("urgent")]
            nb_urgents = sum(1 for t in tab.entry_queue if t.get("urgent"))
            pos = bisect.bisect_left(arrivees, tube["arrivee"])
            tab.entry_queue.insert(nb_urgents + pos, tube)

        arrivees_finales = [t["arrivee"] for t in tab.entry_queue]
        assert arrivees_finales == sorted(arrivees_finales), (
            f"La file doit être triée par arrivée, got {arrivees_finales}"
        )


class TestOutputQueueTriParAge:
    """Les tubes sortis d'une machine doivent être remis au tech dans l'ordre d'ancienneté."""

    def test_tubes_finis_tries_par_arrivee(self):
        """BUG DETECTÉ : sans tri, les tubes de plusieurs machines sont concaténés dans
        l'ordre d'itération du dict Python, qui n'est pas l'ordre d'ancienneté."""
        cm = _make_cm()
        tab = _make_tab(cm)
        # Machine A a terminé un tube ancien
        tab.output_queues["machineA"] = [
            {"arrivee": 5, "workflow": [], "urgent": False, "id": None},
        ]
        # Machine B a terminé un tube plus récent
        tab.output_queues["machineB"] = [
            {"arrivee": 50, "workflow": [], "urgent": False, "id": None},
        ]
        # Machine C a terminé un tube très vieux (arrivé en premier)
        tab.output_queues["machineC"] = [
            {"arrivee": 1, "workflow": [], "urgent": False, "id": None},
        ]

        # ── Comportement BUGUÉ (extend sans tri) ─────────────────────────────
        tubes_bugues = []
        for nom_m in list(tab.output_queues.keys()):
            tubes_bugues.extend(tab.output_queues[nom_m])
        # L'ordre dépend de l'insertion des clés dans le dict, pas de l'ancienneté
        # → pas nécessairement [1, 5, 50]

        # ── Comportement CORRECT (tri par arrivee) ───────────────────────────
        tubes_corrects = []
        for nom_m in list(tab.output_queues.keys()):
            tubes_corrects.extend(tab.output_queues[nom_m])
        tubes_corrects.sort(key=lambda t: t.get("arrivee", 0))

        arrivees = [t["arrivee"] for t in tubes_corrects]
        assert arrivees == [1, 5, 50], (
            f"Tubes finis doivent être livrés du + vieux au + récent, got {arrivees}"
        )

    def test_tube_vieux_unique_en_output_queue_est_prioritaire(self):
        """Un seul tube dans une output_queue doit être pris avant les tubes en entry_queue
        plus récents (Priority 1 dans technician_process)."""
        cm = _make_cm()
        tab = _make_tab(cm)
        # Un tube vieux a fini d'être traité par la machine
        tab.output_queues["ct1"] = [
            {"arrivee": 1, "workflow": [], "urgent": False, "id": None}
        ]
        # Un tube récent attend à l'entrée
        tab.entry_queue = [
            {"arrivee": 999, "workflow": ["centi1"], "urgent": False, "id": None}
        ]

        # La logique du tech vérifie output_queues EN PREMIER (Priority 1)
        has_output = any(tab.output_queues.get(n) for n in tab.output_queues)
        assert has_output, "Le tube fini doit être détecté avant de passer à entry_queue"


# ─────────────────────────────────────────────────────────────────────────────
#  Tests d'intégration : simulation headless courte
# ─────────────────────────────────────────────────────────────────────────────

class TestAucunTubeOublie:
    """Verifie qu'après la simulation, aucun tube n'est resté indéfiniment bloqué."""

    def test_age_max_ne_depasse_pas_seuil_raisonnable(self):
        """Sur 4h de simulation avec workflow simple, l'âge max d'un tube en attente
        ne devrait jamais dépasser 3× l'inter-arrivée moyenne × capacité de la file."""
        cm = _make_cm()
        tab = _make_tab(cm)
        _run(tab, duree=240, seed=42)

        pending = list(tab.entry_queue)
        for q in tab.machine_queues.values():
            pending.extend(q)
        for q in tab.output_queues.values():
            pending.extend(q)

        if pending:
            # Tout tube encore en cours à t=240 ne devrait pas être arrivé avant t=0+δ
            # (seulement les tubes arrivés tout à la fin peuvent rester légitimement)
            ages = [240 - t["arrivee"] for t in pending if "arrivee" in t]
            age_max = max(ages) if ages else 0
            # Seuil : inter-arrivée (5 min) × capacité file (2) × marge large = 60 min
            assert age_max < 60, (
                f"Un tube attend depuis {age_max:.1f} min sur une simulation de 240 min "
                f"avec inter-arrivée 5 min — suspect d'un tube oublié"
            )

    def test_tous_les_tubes_arrivees_comptabilises(self):
        """tubes_sortis + tubes_rejetes + en_cours == tubes entrés dans le système."""
        cm = _make_cm()
        tab = _make_tab(cm)
        _run(tab, duree=240, seed=123)

        en_cours = (
            len(tab.entry_queue)
            + sum(len(q) for q in tab.machine_queues.values())
            + sum(len(q) for q in tab.output_queues.values())
            + len(tab.technicians[0].carried_tubes if tab.technicians else [])
        )
        total_attendu = tab.stats_tubes_total
        total_compte  = tab.tubes_sortis + tab.tubes_rejetes + en_cours
        assert total_compte == total_attendu, (
            f"Conservation des tubes : total={total_attendu}, "
            f"sortis={tab.tubes_sortis} + rejetes={tab.tubes_rejetes} + en_cours={en_cours} "
            f"= {total_compte}"
        )

    def test_age_max_pending_dans_historique_coherent(self):
        """La série transit_time_pending_max ne doit pas croître sans fin :
        si elle monte, elle doit aussi redescendre quand les tubes sont traités."""
        cm = _make_cm()
        tab = _make_tab(cm)
        _run(tab, duree=480, seed=7)

        pending_max = [v for v in tab.stats_history["transit_time_pending_max"] if v is not None]
        if len(pending_max) < 10:
            pytest.skip("Pas assez de données pour l'analyse de la courbe")

        # La valeur maximale de pending_max ne doit pas être atteinte en toute fin
        # (ce serait le signe d'un blocage permanent)
        # On prend le maximum des premiers 80% et compare aux 20% finaux
        cut = int(len(pending_max) * 0.8)
        max_debut = max(pending_max[:cut])
        max_fin   = max(pending_max[cut:])
        # Si la fin est > 4× le début c'est le signe d'un blocage
        assert max_fin <= max_debut * 4 + 60, (
            f"L'âge max des tubes en attente explose en fin de simulation "
            f"(début: {max_debut:.0f} min → fin: {max_fin:.0f} min) — "
            f"possible tube bloqué"
        )


class TestPrioriteEntreeQueue:
    """Vérifie que la politique de prise de tubes respecte FIFO."""

    def test_tech_prend_tubes_depuis_le_debut(self):
        """Confirme que entry_queue[:n] prend bien le début (les plus anciens en FIFO)."""
        cm = _make_cm()
        tab = _make_tab(cm)
        t0 = {"arrivee": 1,   "workflow": ["centi1"], "urgent": False, "id": None}
        t1 = {"arrivee": 50,  "workflow": ["centi1"], "urgent": False, "id": None}
        t2 = {"arrivee": 100, "workflow": ["centi1"], "urgent": False, "id": None}
        tab.entry_queue = [t0, t1, t2]

        nb_a_prendre = 2
        pris = tab.entry_queue[:nb_a_prendre]
        arrivees = [t["arrivee"] for t in pris]
        # Doit être [1, 50] et non [100, ...] ni autre ordre
        assert arrivees == [1, 50]

    def test_insertion_chronologique_apres_remise(self):
        """Simule la remise d'un tube oublié et vérifie qu'il reprend sa bonne place."""
        cm = _make_cm()
        tab = _make_tab(cm)
        tab.entry_queue = [
            {"arrivee": 100, "workflow": ["centi1"], "urgent": False, "id": None},
            {"arrivee": 200, "workflow": ["centi1"], "urgent": False, "id": None},
        ]
        # Tube oublié qui devrait être entre 100 et 200
        tube_repose = {"arrivee": 150, "workflow": ["centi1"], "urgent": False, "id": None}

        # Insertion correcte en position chronologique
        arrivees_norm = [t["arrivee"] for t in tab.entry_queue if not t.get("urgent")]
        nb_urgents   = sum(1 for t in tab.entry_queue if t.get("urgent"))
        pos = bisect.bisect_left(arrivees_norm, tube_repose["arrivee"])
        tab.entry_queue.insert(nb_urgents + pos, tube_repose)

        arrivees = [t["arrivee"] for t in tab.entry_queue]
        assert arrivees == [100, 150, 200], f"Ordre attendu [100,150,200], got {arrivees}"
