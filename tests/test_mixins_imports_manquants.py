"""Régression : les mixins déjà hérités (TabReseau, TabDiagnostic) référençaient
des noms jamais importés dans leur propre module (math, colorchooser, des
constantes de ui/_reseau_const.py, les niveaux de sévérité du diagnostic) —
un NameError réel en production dès que le code path concerné s'exécutait.

Ces tests exercent directement la logique concernée sans passer par Tkinter,
pour confirmer que les imports manquants ont bien été ajoutés.
"""
from unittest.mock import MagicMock

from ui._tabdiagia import _TabDiagIA, ERROR, WARN, OK
from ui._reseau_const import BOX_W, BOX_H, LABO_H, MODE_CHEMIN, MODE_EDIT_WP


class TestDiagnosticNiveauxSeverite:
    """lancer_diagnostic() plantait avec NameError sur ERROR/WARN/OK/INFO."""

    def _config_minimale(self, machines=None, types_tubes=None):
        cm = MagicMock()
        cm.get_machines.return_value = machines or {}
        cm.get_types_tubes.return_value = types_tubes or {}
        return cm

    def _diag_factice(self, config_manager):
        # MagicMock plutôt qu'une vraie instance : lancer_diagnostic() s'appuie
        # sur plusieurs helpers UI (_clear, _section, _write, _freeze, .text...)
        # définis dans TabDiagnostic/_TabDiagObs, pas dans _TabDiagIA seul. Seul
        # le dispatch ERROR/WARN/OK/INFO (le bug corrigé ici) nous intéresse.
        diag = MagicMock()
        diag.config_manager = config_manager
        diag.tab_live = None
        return diag

    def _lancer(self, diag):
        _TabDiagIA.lancer_diagnostic(diag)

    def test_config_vide_ne_leve_pas_nameerror(self):
        diag = self._diag_factice(self._config_minimale())
        self._lancer(diag)  # ne doit lever aucune exception

    def test_absence_entree_journalisee_en_error(self):
        diag = self._diag_factice(self._config_minimale())
        self._lancer(diag)
        appels = [c.args for c in diag._result.call_args_list]
        assert any(level == ERROR and "ENTREE" in msg for level, msg in appels)

    def test_config_complete_journalise_en_ok(self):
        machines = {
            "in1":  {"type": "ENTREE"},
            "out1": {"type": "SORTIE"},
            "t1":   {"type": "TECH_OFFICE"},
        }
        diag = self._diag_factice(self._config_minimale(machines=machines))
        self._lancer(diag)
        appels = [c.args for c in diag._result.call_args_list]
        assert any(level == OK and "ENTREE" in msg for level, msg in appels)
        assert any(level == OK and "SORTIE" in msg for level, msg in appels)

    def test_type_tube_sans_workflow_journalise_en_warn(self):
        machines = {"in1": {"type": "ENTREE"}, "out1": {"type": "SORTIE"}}
        types_tubes = {"biochimie": {"workflow": []}}
        diag = self._diag_factice(self._config_minimale(machines, types_tubes))
        self._lancer(diag)
        appels = [c.args for c in diag._result.call_args_list]
        assert any(level == WARN and "workflow vide" in msg for level, msg in appels)


class TestReseauConstantesImportees:
    """_tabreseauedit.py / _tabreseaupanel.py référençaient BOX_W, BOX_H, LABO_H,
    MODE_CHEMIN, MODE_EDIT_WP, math, colorchooser sans les importer."""

    def test_dimensions_disponibles(self):
        assert BOX_W > 0
        assert BOX_H > 0
        assert LABO_H > 0

    def test_modes_disponibles(self):
        assert MODE_CHEMIN
        assert MODE_EDIT_WP

    def test_tabreseauedit_importable_et_utilise_les_constantes(self):
        import ui._tabreseauedit as mod
        assert mod.BOX_W == BOX_W
        assert mod.math is not None
        assert mod.colorchooser is not None

    def test_tabreseaupanel_importable_et_calcule_duree_trajet(self):
        import ui._tabreseaupanel as mod
        # _duree_trajet référence BOX_W/BOX_H/LABO_H/math — plantait avant le correctif
        duree = mod._TabReseauPanel._duree_trajet(
            {"x": 0, "y": 0}, {"x": 590, "y": 272}, ppm=1.0
        )
        assert duree > 0
