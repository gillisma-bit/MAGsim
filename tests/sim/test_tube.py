"""tests/sim/test_tube.py — Tests unitaires de core/sim/tube.py.

Lancez avec : pytest tests/sim/test_tube.py -v
"""

import pytest
from core.sim.tube import Tube


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_tube(workflow=None, urgent=False, duree_validite=0.0, arrivee=0.0):
    wf = list(workflow) if workflow is not None else ["centi1", "proto1"]
    return Tube(
        id=1,
        type="sang_total",
        couleur="#e74c3c",
        workflow=wf,
        workflow_initial=list(wf),
        arrivee=arrivee,
        duree_validite=duree_validite,
        urgent=urgent,
    )


# ── Tests workflow ─────────────────────────────────────────────────────────────

def test_etape_courante_retourne_premiere_etape():
    t = make_tube(["centi1", "proto1"])
    assert t.etape_courante() == "centi1"


def test_etape_courante_vide():
    t = make_tube([])
    assert t.etape_courante() is None


def test_consommer_etape_reduit_workflow():
    t = make_tube(["centi1", "proto1"])
    etape = t.consommer_etape()
    assert etape == "centi1"
    assert t.workflow == ["proto1"]


def test_consommer_etape_vide():
    t = make_tube([])
    assert t.consommer_etape() is None


def test_est_termine_vrai_quand_workflow_vide():
    t = make_tube([])
    assert t.est_termine()


def test_est_termine_faux_quand_workflow_non_vide():
    t = make_tube(["centi1"])
    assert not t.est_termine()


def test_workflow_initial_immutable_apres_consommation():
    """workflow_initial ne doit jamais changer même quand on consomme workflow."""
    t = make_tube(["centi1", "proto1"])
    t.consommer_etape()
    t.consommer_etape()
    assert t.workflow_initial == ["centi1", "proto1"]
    assert t.workflow == []


# ── Tests temporel / validité ─────────────────────────────────────────────────

def test_age_calcul_correct():
    t = make_tube(arrivee=100.0)
    assert t.age(160.0) == pytest.approx(60.0)


def test_ratio_validite_zero_si_pas_de_validite():
    t = make_tube(duree_validite=0.0, arrivee=0.0)
    assert t.ratio_validite(500.0) == 0.0


def test_ratio_validite_partiel():
    t = make_tube(duree_validite=100.0, arrivee=0.0)
    assert t.ratio_validite(50.0) == pytest.approx(0.5)


def test_ratio_validite_plafonne_a_1():
    t = make_tube(duree_validite=100.0, arrivee=0.0)
    assert t.ratio_validite(999.0) == pytest.approx(1.0)


# ── Tests score_priorite ──────────────────────────────────────────────────────

def test_urgent_toujours_devant_non_urgent():
    t_urgent = make_tube(urgent=True, arrivee=0.0)
    t_normal = make_tube(urgent=False, arrivee=0.0)
    assert t_urgent.score_priorite(100.0) > t_normal.score_priorite(100.0)


def test_tube_plus_vieux_score_plus_eleve():
    t_vieux = make_tube(arrivee=0.0)
    t_neuf  = make_tube(arrivee=50.0)
    t_now = 100.0
    assert t_vieux.score_priorite(t_now) > t_neuf.score_priorite(t_now)


def test_tube_proche_peremption_score_plus_eleve():
    t_proche = make_tube(duree_validite=100.0, arrivee=0.0)   # ratio=0.9 à t=90
    t_loin   = make_tube(duree_validite=1000.0, arrivee=0.0)  # ratio=0.09 à t=90
    assert t_proche.score_priorite(90.0) > t_loin.score_priorite(90.0)


# ── Tests sérialisation ───────────────────────────────────────────────────────

def test_to_dict_contient_champs_essentiels():
    t = make_tube(["centi1"])
    d = t.to_dict()
    assert d["id"] == 1
    assert d["workflow"] == ["centi1"]
    assert "canvas_id" not in d      # canvas_id ne doit pas sortir du dict


def test_from_dict_roundtrip():
    t = make_tube(["centi1", "proto1"], urgent=True, duree_validite=120.0, arrivee=30.0)
    d = t.to_dict()
    t2 = Tube.from_dict(d)
    assert t2.workflow == t.workflow
    assert t2.urgent == t.urgent
    assert t2.duree_validite == t.duree_validite
    assert t2.arrivee == t.arrivee
