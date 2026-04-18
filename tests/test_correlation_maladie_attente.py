"""Tests de corrélation : arrêts maladie → montée du pending_max des tubes.

Principe
--------
On fait tourner la même simulation multi-jours dans deux conditions :

  1. **Contrôle (sans maladie)** — ``calculer_risque_arret_maladie`` patché à 0
     → aucun arrêt maladie, flux continu, pending_max reste bas.

  2. **Maladie forcée** — un processus SimPy injecte ``en_arret_maladie = True``
     à un instant précis (T_INJECTION) en contournant le mécanisme de risque pour
     un scénario déterministe.  ``mecontentement = 0.90`` → ``proba_retour = 0``
     → le tech reste absent pour toute la simulation.

La désactivation du risque naturel dans les deux runs (``risque = 0`` via patch)
isole l'injection comme seule source d'arrêt maladie : les résultats sont
100 % reproductibles quelle que soit la graine aléatoire.

Assertions clés
---------------
- Après l'injection, ``transit_time_pending_max`` grimpe bien au-delà du niveau
  de contrôle (tubes qui s'accumulent sans tech disponible).
- Le pic du pending_max survient APRÈS l'instant d'injection, pas avant.
- Le run de contrôle ne dépasse jamais un seuil raisonnable.

Lancer :
    cd "f:\\code python\\MAGsim"
    python -m pytest tests/test_correlation_maladie_attente.py -v
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
DUREE_JOUR  = 1440            # 1 journée en minutes SimPy
DUREE_TEST  = 3 * DUREE_JOUR  # 3 jours
T_INJECTION = DUREE_JOUR      # Le tech tombe malade au début du jour 2
SEED        = 42

# ─────────────────────────────────────────────────────────────────────────────
#  Config minimale : 1 tech, 1 machine, profil horaire plat, 0 % erreur.
#  Flux soutenu (frequence=4) pour que l'accumulation soit visible rapidement.
# ─────────────────────────────────────────────────────────────────────────────
_CFG = {
    "nom_projet": "test_correlation_maladie",
    "machines": {
        "IN": {
            "type": "ENTREE",
            "coords": {"x": 250, "y": 500},
            "capacite": 4, "protocoles": {},
            "frequence": 4.0,
            "gamma_k": 2.0,
            "heure_debut": 7.0,
            "pct_mauvais_prelevements": 0.0,
            "profil_horaire": [[0.0, 1.0], [24.0, 1.0]],
        },
        "ct1": {
            "type": "Centrifugeuse",
            "coords": {"x": 250, "y": 400},
            "capacite": 3, "file_max": 9999, "seuil": 1,
            "protocoles": {"centi1": {"temps": 8, "type_compatible": "Centrifugeuse"}},
            "timeout_batch": 30,
        },
        "OUT": {
            "type": "SORTIE",
            "coords": {"x": 250, "y": 300},
            "capacite": 4, "file_max": 9999, "seuil": 1, "protocoles": {},
        },
        "b1": {
            "type": "TECH_OFFICE",
            "coords": {"x": 250, "y": 600},
            "capacite": 4, "protocoles": {},
            "nom": "Alice",
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

def _make_cm(cfg=None):
    cm = ConfigManager.__new__(ConfigManager)
    cm.filepath = ":memory:"
    cm.data = copy.deepcopy(cfg or _CFG)
    return cm


def _make_tab(cm):
    mock_canvas = MagicMock()
    mock_canvas.winfo_exists.return_value = False
    with (
        patch("ui.tab_live.tk.Canvas",    return_value=mock_canvas),
        patch("ui.tab_live.ttk.Scrollbar",return_value=MagicMock()),
        patch("ui.tab_live.ttk.Frame",    return_value=MagicMock()),
        patch("ui.tab_live.ttk.Button",   return_value=MagicMock()),
        patch("ui.tab_live.ttk.Label",    return_value=MagicMock()),
    ):
        from ui.tab_live import TabLive
        tab = TabLive(MagicMock(), cm)
    tab.canvas = mock_canvas
    return tab


def _init_sim_local(tab, seed):
    """Initialise l'environnement SimPy (copie fidèle de test_coherence_sim._init_sim)."""
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
        tech.office_x               = office["coords"]["x"]
        tech.office_y               = office["coords"]["y"]
        tab.technicians.append(tech)

    tab.env = simpy.Environment()
    tab.env.process(tab.tube_generation())
    for t in tab.technicians:
        tab.env.process(tab.technician_process(t))
    tab.env.process(tab.stats_collector())
    for nom_m, m_conf in machines.items():
        if m_conf.get("tmep") and m_conf.get("tmr"):
            tab.env.process(tab.machine_breakdown_process(nom_m, m_conf))


def _run_sim(tab, duree):
    """Exécute la simulation pas-à-pas jusqu'à duree."""
    try:
        while tab.env.now < duree and tab.running:
            tab.env.step()
    except StopIteration:
        pass
    tab.running = False


def _processus_injecteur_maladie(env, techs, t_injection, mecontentement_force=0.90):
    """Processus SimPy qui met les techs en arrêt maladie à t=t_injection.

    ``mecontentement_force=0.90`` rend la probabilité de retour = 0 :
        proba_retour = max(0, 0.60 − 0.90 × 0.80) = 0
    → le tech reste absent pour le reste de la simulation.
    """
    yield env.timeout(t_injection)
    for tech in techs:
        tech.en_arret_maladie = True
        tech.mecontentement   = mecontentement_force


def _pending_non_null(h, t_min=None, t_max=None):
    """Retourne la liste des valeurs pending_max non-None dans la fenêtre [t_min, t_max[."""
    times   = h["time"]
    pending = h["transit_time_pending_max"]
    return [
        v for t, v in zip(times, pending)
        if v is not None
        and (t_min is None or t >= t_min)
        and (t_max is None or t <  t_max)
    ]


# ─────────────────────────────────────────────────────────────────────────────
#  Classe 1 — Contrôle : risque d'arrêt maladie = 0
# ─────────────────────────────────────────────────────────────────────────────

class TestControle:
    """Sans aucun risque de maladie, le pending_max doit rester stable et bas."""

    def _run(self):
        cm  = _make_cm()
        tab = _make_tab(cm)
        with patch.object(TechnicianState, "calculer_risque_arret_maladie",
                          new=lambda self: 0.0):
            _init_sim_local(tab, seed=SEED)
            _run_sim(tab, DUREE_TEST)
        return tab

    def test_aucun_evenement_arret_maladie(self):
        """Aucun événement ne doit être journalisé quand le risque est nul."""
        tab = self._run()
        events = tab.stats_history["events_arret_maladie"]
        assert events == [], (
            f"Aucun événement arrêt maladie attendu, got {events}"
        )

    def test_pending_max_ne_depasse_pas_seuil_raisonnable(self):
        """Sans maladie, le tube le plus vieux ne doit pas dépasser 2 h d'attente."""
        tab  = self._run()
        vals = _pending_non_null(tab.stats_history)
        assert vals, "Des échantillons pending_max attendus"
        assert max(vals) < 120, (
            f"Pending max sans maladie trop élevé : {max(vals):.1f} min (attendu < 120 min)"
        )

    def test_tubes_sortis_non_nul(self):
        """Vérification de cohérence : des tubes doivent sortir en 3 jours."""
        tab = self._run()
        assert tab.tubes_sortis > 0, "Des tubes doivent être traités en 3 jours"


# ─────────────────────────────────────────────────────────────────────────────
#  Classe 2 — Injection directe d'arrêt maladie via processus SimPy
# ─────────────────────────────────────────────────────────────────────────────

class TestInjectionMaladieForcee:
    """Vérifie qu'une maladie injectée à T_INJECTION provoque un pic de pending_max."""

    def _run(self):
        cm  = _make_cm()
        tab = _make_tab(cm)
        # Le risque naturel reste nul → seule l'injection est source de maladie
        with patch.object(TechnicianState, "calculer_risque_arret_maladie",
                          new=lambda self: 0.0):
            _init_sim_local(tab, seed=SEED)
            tab.env.process(
                _processus_injecteur_maladie(tab.env, tab.technicians, T_INJECTION)
            )
            _run_sim(tab, DUREE_TEST)
        return tab

    def test_tech_est_malade_apres_injection(self):
        """Juste après T_INJECTION, le tech doit être marqué en_arret_maladie=True.

        On avance la simulation sur seulement les 2 premiers jours pour vérifier
        l'état immédiatement après l'injection, sans attendre de retour éventuel.
        """
        cm  = _make_cm()
        tab = _make_tab(cm)
        with patch.object(TechnicianState, "calculer_risque_arret_maladie",
                          new=lambda self: 0.0):
            _init_sim_local(tab, seed=SEED)
            tab.env.process(
                _processus_injecteur_maladie(tab.env, tab.technicians, T_INJECTION)
            )
            # Avancer juste après l'injection
            t_cible = T_INJECTION + 1
            try:
                while tab.env.now < t_cible and tab.running:
                    tab.env.step()
            except StopIteration:
                pass

        assert all(t.en_arret_maladie for t in tab.technicians), (
            "Tous les techs doivent être malades immédiatement après l'injection"
        )

    def test_pending_max_augmente_nettement_apres_injection(self):
        """Après T_INJECTION, la médiane du pending_max doit être > 10× celle d'avant.

        Mécanisme : le tech absent ne vient plus chercher les tubes en entry_queue.
        Les tubes s'accumulent et vieillissent → pending_max grimpe linéairement.
        """
        tab = self._run()
        h   = tab.stats_history

        avant = _pending_non_null(h, t_max=T_INJECTION)
        apres = _pending_non_null(h, t_min=T_INJECTION)

        assert avant, "Des échantillons avant l'injection sont attendus"
        assert apres, "Des échantillons après l'injection sont attendus"

        med_avant = sorted(avant)[len(avant) // 2]
        med_apres = sorted(apres)[len(apres) // 2]

        assert med_apres > med_avant * 10, (
            f"La médiane du pending_max devrait être ≥ 10× plus élevée après la maladie.\n"
            f"  Avant  : {med_avant:.1f} min\n"
            f"  Après  : {med_apres:.1f} min"
        )

    def test_pic_survient_apres_injection_pas_avant(self):
        """Le pic absolu du pending_max doit se produire APRÈS T_INJECTION.

        Si le pic était avant l'injection, cela indiquerait un autre bug indépendant
        (ex. : machine jamais déclenchée) — la corrélation ne serait pas prouvée.
        """
        tab = self._run()
        h   = tab.stats_history

        vals_non_null = [
            (t, v)
            for t, v in zip(h["time"], h["transit_time_pending_max"])
            if v is not None
        ]
        assert vals_non_null, "Des échantillons pending_max attendus"

        t_pic, _ = max(vals_non_null, key=lambda x: x[1])

        assert t_pic >= T_INJECTION, (
            f"Le pic du pending_max doit survenir après t={T_INJECTION} min (injection),\n"
            f"mais il est à t={t_pic:.1f} min."
        )

    def test_aucun_evenement_journalise_par_stats_collector(self):
        """L'injection directe (en_arret_maladie=True) ne passe pas par stats_collector.

        stats_collector ne journalise un événement que si calculer_risque_arret_maladie
        retourne > 0.  Ici le risque est patché à 0 → events_arret_maladie doit rester vide.
        Cela valide que le seul log d'événement raisonnable est celui du risque naturel.
        """
        tab    = self._run()
        events = tab.stats_history["events_arret_maladie"]
        assert events == [], (
            "Aucun événement journalisé via stats_collector attendu (risque=0).\n"
            f"Got {events}"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Classe 3 — Corrélation directe : comparaison avec/sans maladie
# ─────────────────────────────────────────────────────────────────────────────

class TestCorrelationMaladieVsControle:
    """Compare les runs avec/sans maladie pour quantifier l'impact sur le pending_max."""

    def _run_sans(self):
        cm  = _make_cm()
        tab = _make_tab(cm)
        with patch.object(TechnicianState, "calculer_risque_arret_maladie",
                          new=lambda self: 0.0):
            _init_sim_local(tab, seed=SEED)
            _run_sim(tab, DUREE_TEST)
        return tab.stats_history

    def _run_avec(self):
        cm  = _make_cm()
        tab = _make_tab(cm)
        with patch.object(TechnicianState, "calculer_risque_arret_maladie",
                          new=lambda self: 0.0):
            _init_sim_local(tab, seed=SEED)
            tab.env.process(
                _processus_injecteur_maladie(tab.env, tab.technicians, T_INJECTION)
            )
            _run_sim(tab, DUREE_TEST)
        return tab.stats_history

    def test_pic_avec_maladie_depasse_largement_controle(self):
        """Le max du pending_max APRÈS l'injection doit dépasser de 2 h le max du contrôle.

        2 h de marge arbitraire : dans le run de contrôle, l'accumulation normale
        ne dépasse pas ~60 min.  Avec le tech absent depuis le jour 2, des tubes
        attendent plusieurs heures voire jours.
        """
        h_sans = self._run_sans()
        h_avec = self._run_avec()

        max_sans = max(_pending_non_null(h_sans, t_min=T_INJECTION), default=0)
        max_avec = max(_pending_non_null(h_avec, t_min=T_INJECTION), default=0)

        assert max_avec > max_sans + 120, (
            f"Le pic avec maladie devrait dépasser le contrôle d'au moins 120 min.\n"
            f"  Contrôle (sans maladie) : {max_sans:.1f} min\n"
            f"  Avec maladie forcée     : {max_avec:.1f} min"
        )

    def test_periode_avant_injection_identique(self):
        """Avant T_INJECTION, les deux runs ont la même graine → comportement identique.

        Valide que l'injection ne rétroagit pas sur le passé : les niveaux
        d'accumulation AVANT la maladie doivent être très proches.
        """
        h_sans = self._run_sans()
        h_avec = self._run_avec()

        vals_sans = _pending_non_null(h_sans, t_max=T_INJECTION)
        vals_avec = _pending_non_null(h_avec, t_max=T_INJECTION)

        assert vals_sans and vals_avec, "Échantillons avant injection manquants"

        max_sans = max(vals_sans)
        max_avec = max(vals_avec)

        # Les deux runs étant identiques avant l'injection (même seed, même processus),
        # les maxima doivent être strictement égaux.
        assert max_avec == max_sans, (
            f"Avant l'injection, les deux runs devraient avoir le même pending_max.\n"
            f"  Sans maladie : {max_sans:.1f} min\n"
            f"  Avec maladie : {max_avec:.1f} min"
        )
