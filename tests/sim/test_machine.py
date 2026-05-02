"""tests/sim/test_machine.py — Tests unitaires de core/sim/machine.py.

Ces tests couvrent spécifiquement le pattern respawn (origine du bug de gel)
et garantissent qu'aucun deadlock ne peut survenir.

Lancez avec : pytest tests/sim/test_machine.py -v
"""

import pytest
import simpy
from core.sim.machine import Machine
from core.sim.tube import Tube
from core.event_bus import EventBus


# ── Helpers ───────────────────────────────────────────────────────────────────

PROTOCOLES_SIMPLE = {"centi1": {"temps": 30}}


def make_machine(env, capacite=4, file_max=None, seuil=1, event_bus=None):
    return Machine(
        env=env,
        nom="ct1",
        protocoles=PROTOCOLES_SIMPLE,
        capacite=capacite,
        file_max=file_max,
        seuil=seuil,
        event_bus=event_bus,
    )


def make_tube(tube_id=1, urgent=False, workflow=None):
    wf = list(workflow) if workflow is not None else ["centi1"]
    return Tube(
        id=tube_id,
        type="sang_total",
        couleur="#e74c3c",
        workflow=wf,
        workflow_initial=list(wf),
        urgent=urgent,
    )


def run_sim(env, duree=100_000):
    """Lance la simulation et retourne env."""
    env.run(until=duree)
    return env


# ── Tests de base ─────────────────────────────────────────────────────────────

def test_machine_inerte_sans_tubes():
    env = simpy.Environment()
    m = make_machine(env)
    run_sim(env, 1000)
    assert m.nb_batches == 0
    assert m.nb_tubes_traites == 0
    assert not m.busy


def test_batch_complet_traite_tous_les_tubes():
    env = simpy.Environment()
    m = make_machine(env, capacite=4)
    for i in range(4):
        m.enqueue(make_tube(i))
    m.essayer_lancer_batch()
    run_sim(env, 10_000)
    assert m.nb_tubes_traites == 4
    assert m.output_len == 4
    assert m.queue_len == 0
    assert not m.busy


def test_batch_partiel_urgent_sous_capacite():
    """Un seul tube urgent doit déclencher un batch même si file < capacite."""
    env = simpy.Environment()
    m = make_machine(env, capacite=4, seuil=1)
    m.enqueue(make_tube(1, urgent=True))
    m.essayer_lancer_batch()
    run_sim(env, 10_000)
    assert m.nb_tubes_traites == 1


def test_pas_de_batch_si_file_insuffisante_et_pas_urgent():
    """Batch non lancé si nb tubes < capacite et pas d'urgence."""
    env = simpy.Environment()
    m = make_machine(env, capacite=4, seuil=4)
    m.enqueue(make_tube(1, urgent=False))
    m.essayer_lancer_batch()
    run_sim(env, 10_000)
    assert m.nb_batches == 0
    assert m.nb_tubes_traites == 0


def test_file_pleine_refuse_nouveau_tube():
    env = simpy.Environment()
    m = make_machine(env, capacite=2, file_max=2)
    m.enqueue(make_tube(1))
    m.enqueue(make_tube(2))
    accepte = m.enqueue(make_tube(3))
    assert accepte is False
    assert m.queue_len == 2


# ── Tests anti-deadlock : le cœur du bug original ────────────────────────────

def test_respawn_vide_file_nombreux_tubes():
    """50 tubes injectés → la machine doit tous les traiter via respawn.

    C'est le test qui aurait détecté le bug de gel en production.
    La simulation doit se terminer proprement (sans timeout) avec
    tous les tubes en sortie.
    """
    env = simpy.Environment()
    m = make_machine(env, capacite=5, file_max=100)
    for i in range(50):
        m.enqueue(make_tube(i))
    m.essayer_lancer_batch()
    run_sim(env, 100_000)
    assert m.nb_tubes_traites == 50
    assert m.output_len == 50
    assert m.queue_len == 0
    assert not m.busy     # terminé proprement, pas bloqué


def test_pas_de_doublon_batch_actif():
    """Appeler essayer_lancer_batch() deux fois de suite ne doit créer
    qu'un seul batch — pas deux processus concurrents."""
    env = simpy.Environment()
    m = make_machine(env, capacite=4, file_max=20)
    for i in range(8):
        m.enqueue(make_tube(i))
    m.essayer_lancer_batch()
    m.essayer_lancer_batch()   # deuxième appel : doit être ignoré
    run_sim(env, 100_000)
    assert m.nb_tubes_traites == 8
    # Si doublon, on aurait 16 ou une exception


def test_actif_false_entre_deux_batches():
    """Entre la fin d'un batch et le démarrage du respawn, _actif ne doit
    jamais rester True indéfiniment (vérification à t_fin_batch + epsilon)."""
    env = simpy.Environment()
    m = make_machine(env, capacite=4, file_max=20)
    for i in range(4):
        m.enqueue(make_tube(i))
    m.essayer_lancer_batch()

    # Avancer juste après la fin du premier batch (30 min / 10 = 3 unités)
    env.run(until=3.1)
    # Le batch est fini, le respawn n'a pas eu lieu (file vide après batch)
    assert not m.busy
    assert m.nb_tubes_traites == 4


def test_injection_progressive_declenche_plusieurs_batches():
    """Injection de tubes APRÈS le premier batch : le watchdog extérieur
    (ou un nouvel appel à essayer_lancer_batch) doit relancer la machine."""
    env = simpy.Environment()
    m = make_machine(env, capacite=4, file_max=20)

    def injecteur():
        # Premier lot : déclenche batch #1
        for i in range(4):
            m.enqueue(make_tube(i))
        m.essayer_lancer_batch()
        yield env.timeout(50)    # après la fin du batch (3 unités suffit)
        # Deuxième lot
        for i in range(4, 8):
            m.enqueue(make_tube(i))
        m.essayer_lancer_batch()

    env.process(injecteur())
    run_sim(env, 100_000)
    assert m.nb_tubes_traites == 8
    assert m.output_len == 8


def test_respawn_continu_100_tubes():
    """Test de charge : 100 tubes, capacite=5 → 20 batches successifs."""
    env = simpy.Environment()
    m = make_machine(env, capacite=5, file_max=200)
    for i in range(100):
        m.enqueue(make_tube(i))
    m.essayer_lancer_batch()
    run_sim(env, 1_000_000)
    assert m.nb_tubes_traites == 100
    assert m.nb_batches == 20
    assert not m.busy


# ── Tests EventBus ────────────────────────────────────────────────────────────

def test_eventbus_recoit_batch_debut_et_fin():
    bus = EventBus()
    events = []
    bus.subscribe("machine.batch_debut", lambda e: events.append(("debut", e)))
    bus.subscribe("machine.batch_fin",   lambda e: events.append(("fin",   e)))

    env = simpy.Environment()
    m = make_machine(env, capacite=4, event_bus=bus)
    for i in range(4):
        m.enqueue(make_tube(i))
    m.essayer_lancer_batch()
    run_sim(env, 10_000)

    types = [e[0] for e in events]
    assert "debut" in types
    assert "fin" in types


def test_drain_output_vide_la_sortie():
    env = simpy.Environment()
    m = make_machine(env, capacite=4)
    for i in range(4):
        m.enqueue(make_tube(i))
    m.essayer_lancer_batch()
    run_sim(env, 10_000)

    tubes = m.drain_output()
    assert len(tubes) == 4
    assert m.output_len == 0


# ── Tests snapshot ────────────────────────────────────────────────────────────

def test_snapshot_structure():
    env = simpy.Environment()
    m = make_machine(env)
    snap = m.snapshot()
    assert snap["nom"] == "ct1"
    assert "queue" in snap
    assert "output" in snap
    assert "busy" in snap
    assert "en_panne" in snap
    assert "nb_batches" in snap
    assert "nb_tubes_traites" in snap
