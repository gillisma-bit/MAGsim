"""Tests unitaires — tracking de la distance journalière par technicien.

Le bug original : _jours_connus_dist.add() était appelé DANS la boucle for idx,
tech. Dès que Tech 1 était traité, le set contenait jour_actuel → le snapshot
n'était jamais mis à jour pour Tech 2, 3, 4 → leur distance journalière
semblait exploser (valeur cumulative depuis le début au lieu du delta du jour).

Lancer avec :
    cd "f:\\code python\\MAGsim"
    python -m pytest tests/test_distance_journaliere.py -v
"""

import pytest
from core.technician import TechnicianState


# ── Helpers – simule la logique du stats_collector ──────────────────────────

def _snapshot_buggy(techs, jour_actuel, distances_tech, jours_connus):
    """Réplique exacte du code BUGGY : add() à l'intérieur de la boucle."""
    for idx, tech in enumerate(techs):
        k = f"Tech {idx + 1}"
        if k not in distances_tech:
            distances_tech[k] = {}
        d_m = (tech.distance_parcourue_px - tech._distance_debut_jour_px) * 0.01
        distances_tech[k][jour_actuel] = round(d_m, 1)
        if jour_actuel not in jours_connus:
            if jour_actuel > 0:
                tech._distance_debut_jour_px = tech.distance_parcourue_px
            jours_connus.add(jour_actuel)   # BUG : ajouté avant les autres techs


def _snapshot_correct(techs, jour_actuel, distances_tech, jours_connus):
    """Version CORRIGÉE : snapshot mis à jour AVANT d_m, EN DEHORS de la boucle."""
    nouveau_jour = jour_actuel not in jours_connus
    if nouveau_jour:
        jours_connus.add(jour_actuel)
        if jour_actuel > 0:
            # Snapshot de TOUS les techs avant de calculer quoi que ce soit
            for tech in techs:
                tech._distance_debut_jour_px = tech.distance_parcourue_px

    for idx, tech in enumerate(techs):
        k = f"Tech {idx + 1}"
        if k not in distances_tech:
            distances_tech[k] = {}
        d_m = (tech.distance_parcourue_px - tech._distance_debut_jour_px) * 0.01
        distances_tech[k][jour_actuel] = round(d_m, 1)


# ── Tests exposant le bug ─────────────────────────────────────────────────────

class TestBugSnapshotManquant:
    """Ces tests RÉUSSISSENT avec le code corrigé."""

    def _multi_tick_scenario(self, fn):
        """
        Scénario réaliste multi-ticks :
         - Jour 0 : 2 ticks, Tech1 finit à 1000 px, Tech2 à 500 px.
         - Jour 1 (1er tick) : transition détectée, snap mis à jour, d_m = 0.
         - Jour 1 (2ème tick) : Tech1 = 1200 px (+200), Tech2 = 800 px (+300).
        Vérifie que les distances jour 1 sont 2.0 m et 3.0 m.
        """
        t1 = TechnicianState(0, 0, index=0)
        t2 = TechnicianState(0, 0, index=1)
        distances, jours = {}, set()

        # Jour 0 – tick 1
        t1.distance_parcourue_px = 500.0
        t2.distance_parcourue_px = 250.0
        fn([t1, t2], 0, distances, jours)

        # Jour 0 – tick 2 (fin de journée)
        t1.distance_parcourue_px = 1000.0
        t2.distance_parcourue_px = 500.0
        fn([t1, t2], 0, distances, jours)

        # Jour 1 – premier tick (transition : snap mis à jour, d_m attendu ≈ 0)
        fn([t1, t2], 1, distances, jours)

        # Jour 1 – deuxième tick (Tech1 marche 200 px, Tech2 300 px)
        t1.distance_parcourue_px = 1200.0
        t2.distance_parcourue_px = 800.0
        fn([t1, t2], 1, distances, jours)

        return distances

    def test_tech1_distance_jour1_correcte(self):
        d = self._multi_tick_scenario(_snapshot_correct)
        assert d["Tech 1"][1] == 2.0, (
            f"Tech 1 jour 1 attendu 2.0 m (200 px), obtenu {d['Tech 1'][1]}"
        )

    def test_tech2_distance_jour1_correcte(self):
        d = self._multi_tick_scenario(_snapshot_correct)
        assert d["Tech 2"][1] == 3.0, (
            f"Tech 2 jour 1 attendu 3.0 m (300 px), obtenu {d['Tech 2'][1]}"
        )

    def test_distance_jour0_correcte_pour_les_deux_techs(self):
        d = self._multi_tick_scenario(_snapshot_correct)
        assert d["Tech 1"][0] == 10.0
        assert d["Tech 2"][0] == 5.0

    def test_trois_jours_pas_de_croissance_cumulative(self):
        t1 = TechnicianState(0, 0, index=0)
        t2 = TechnicianState(0, 0, index=1)
        distances, jours = {}, set()

        # Jour 0
        t1.distance_parcourue_px = 1000.0
        t2.distance_parcourue_px = 500.0
        _snapshot_correct([t1, t2], 0, distances, jours)

        # Jour 1 – transition (snap = 1000/500)
        _snapshot_correct([t1, t2], 1, distances, jours)
        t1.distance_parcourue_px = 1200.0
        t2.distance_parcourue_px = 800.0
        _snapshot_correct([t1, t2], 1, distances, jours)

        # Jour 2 – transition (snap = 1200/800)
        _snapshot_correct([t1, t2], 2, distances, jours)
        t1.distance_parcourue_px = 1600.0
        t2.distance_parcourue_px = 900.0
        _snapshot_correct([t1, t2], 2, distances, jours)

        assert distances["Tech 1"][0] == 10.0
        assert distances["Tech 1"][1] == 2.0
        assert distances["Tech 1"][2] == 4.0
        assert distances["Tech 2"][0] == 5.0
        assert distances["Tech 2"][1] == 3.0
        assert distances["Tech 2"][2] == 1.0

    def test_snapshot_stable_quand_meme_jours_appele_plusieurs_fois(self):
        """Le snap ne change pas si on reste sur le même jour."""
        t1 = TechnicianState(0, 0, index=0)
        t2 = TechnicianState(0, 0, index=1)
        distances, jours = {}, set()

        # Jour 0 – plusieurs ticks
        for dist in [100, 300, 600, 1000]:
            t1.distance_parcourue_px = float(dist)
            t2.distance_parcourue_px = float(dist // 2)
            _snapshot_correct([t1, t2], 0, distances, jours)

        # Fin jour 0 : valeurs finales
        assert distances["Tech 1"][0] == 10.0
        assert distances["Tech 2"][0] == 5.0

        # Jour 1 – transition puis marche
        _snapshot_correct([t1, t2], 1, distances, jours)   # snap = 1000/500
        t1.distance_parcourue_px = 1050.0
        t2.distance_parcourue_px = 525.0
        _snapshot_correct([t1, t2], 1, distances, jours)

        assert distances["Tech 1"][1] == 0.5
        assert distances["Tech 2"][1] == 0.2  # 25*0.01=0.25 → 0.2 (arrondi Python)

    def test_quatre_techs_tous_ont_snapshot_correct(self):
        techs = [TechnicianState(0, 0, index=i) for i in range(4)]
        px_fin_jour0 = [1000, 800, 600, 400]
        px_jour1_extra = [100, 200, 300, 400]
        distances, jours = {}, set()

        for i, t in enumerate(techs):
            t.distance_parcourue_px = float(px_fin_jour0[i])
        _snapshot_correct(techs, 0, distances, jours)

        # Transition jour 1
        _snapshot_correct(techs, 1, distances, jours)
        for i, t in enumerate(techs):
            t.distance_parcourue_px += px_jour1_extra[i]
        _snapshot_correct(techs, 1, distances, jours)

        for i in range(4):
            expected = round(px_jour1_extra[i] * 0.01, 1)
            assert distances[f"Tech {i + 1}"][1] == expected, (
                f"Tech {i + 1} : attendu {expected} m, obtenu {distances[f'Tech {i+1}'][1]}"
            )


# ── Tests prouvant que le code buggy échoue ──────────────────────────────────

class TestBuggyCodeEchoue:
    """Documente que la version buggée produit des résultats erronés."""

    def test_buggy_tech2_recoit_valeur_cumulative(self):
        t1 = TechnicianState(0, 0, index=0)
        t2 = TechnicianState(0, 0, index=1)
        distances, jours = {}, set()

        t1.distance_parcourue_px = 1000.0
        t2.distance_parcourue_px = 500.0
        _snapshot_buggy([t1, t2], 0, distances, jours)

        # Transition jour 1 (buggy)
        _snapshot_buggy([t1, t2], 1, distances, jours)
        t1.distance_parcourue_px = 1200.0
        t2.distance_parcourue_px = 800.0
        _snapshot_buggy([t1, t2], 1, distances, jours)

        # BUG confirmé : Tech 1 a son snapshot (premier dans la boucle) → correct
        assert distances["Tech 1"][1] == 2.0
        # Tech 2 n'a jamais eu son snapshot mis à jour → renvoie distance cumulative
        assert distances["Tech 2"][1] == 8.0, (
            "Si ce test échoue, le bug a été introduit différemment que prévu"
        )

    def test_buggy_empire_avec_plus_de_techs(self):
        """Avec 4 techs, seul Tech 1 est correct ; tous les autres sont cumulatifs."""
        techs = [TechnicianState(0, 0, index=i) for i in range(4)]
        px_j0 = [1000, 800, 600, 400]
        for i, t in enumerate(techs):
            t.distance_parcourue_px = float(px_j0[i])
        distances, jours = {}, set()
        _snapshot_buggy(techs, 0, distances, jours)

        # Transition jour 1 (buggy)
        _snapshot_buggy(techs, 1, distances, jours)
        extras = [100, 200, 300, 400]
        for i, t in enumerate(techs):
            t.distance_parcourue_px += extras[i]
        _snapshot_buggy(techs, 1, distances, jours)

        # Tech 1 a le snap → correct (1000+100 - 1000)*0.01 = 1.0
        assert distances["Tech 1"][1] == 1.0
        # Tech 2, 3, 4 n'ont pas de snap → cumulatifs
        assert distances["Tech 2"][1] > 2.0   # cumul > delta
        assert distances["Tech 3"][1] > 3.0
        assert distances["Tech 4"][1] > 4.0

