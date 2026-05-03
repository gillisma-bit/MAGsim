"""Tests unitaires — logique de distribution des tubes par étape de workflow.

Lancer avec :
    cd "f:\\code python\\MAGsim"
    python -m pytest tests/test_workflow.py -v

Ces tests vérifient que :
  1. Un tube est toujours envoyé vers la première étape de son workflow.
  2. Quand TOUTES les machines pour l'étape courante sont pleines, le tube
     est mis en attente (retour None) et NE PASSE PAS à l'étape suivante.
  3. Un tube dont le workflow est vide renvoie (None, None, None) → direction sortie.
  4. La logique fill-first fonctionne : on remplit la machine la plus proche
     de sa capacité avant de déborder sur la suivante.
  5. virtual_queues est respecté (tubes déjà attribués dans le même batch).
  6. Une étape sans machine du tout dans la config est ignorée avec warning, mais
     les étapes suivantes restent traitées.
"""

import copy
import pytest
from core.sim_utils import trouver_prochaine_machine

# ── Fixtures ─────────────────────────────────────────────────────────────────

MACHINES = {
    "ct1": {
        "type": "Centrifugeuse",
        "capacite": 4, "file_max": 10,
        "protocoles": {"centi1": {"temps": 30}},
        "coords": {"x": 825, "y": 675},
    },
    "ct2": {
        "type": "Centrifugeuse",
        "capacite": 10, "file_max": 10,
        "protocoles": {"centi1": {"temps": 30}},
        "coords": {"x": 675, "y": 675},
    },
    "pa1": {
        "type": "Paillasse",
        "capacite": 5, "file_max": 25,
        "protocoles": {"culot 1": {"temps": 100}},
        "coords": {"x": 675, "y": 425},
    },
    "au1": {
        "type": "Automate",
        "capacite": 10, "file_max": 20,
        "protocoles": {"proto1": {"temps": 120}},
        "coords": {"x": 475, "y": 125},
    },
}

WORKFLOW_COMPLET = ["centi1", "culot 1", "proto1"]


def make_tube(workflow=None):
    if workflow is None:
        workflow = WORKFLOW_COMPLET
    return {"type": "tube1", "workflow": list(workflow)}


# ── Tests de base ─────────────────────────────────────────────────────────────

class TestPremièreÉtape:
    def test_envoie_vers_centri_en_premier(self):
        """Un tube [centi1, culot 1, proto1] doit aller à une centrifugeuse, pas à la paillasse."""
        tube = make_tube()
        machine, nom, etape = trouver_prochaine_machine(tube, MACHINES, {})
        assert etape == "centi1", f"Étape attendue : centi1, obtenu : {etape}"
        assert nom in ("ct1", "ct2"), f"Doit aller en centri, pas en '{nom}'"

    def test_workflow_non_mutilé_après_appel(self):
        """L'appel ne doit PAS modifier le workflow du tube (juste peek)."""
        tube = make_tube()
        original = list(tube["workflow"])
        trouver_prochaine_machine(tube, MACHINES, {})
        assert tube["workflow"] == original, "Le workflow a été modifié par trouver_prochaine_machine !"

    def test_workflow_vide_retourne_none(self):
        """Un tube sans étapes restantes doit renvoyer (None, None, None) → sortie."""
        tube = make_tube(workflow=[])
        machine, nom, etape = trouver_prochaine_machine(tube, MACHINES, {})
        assert machine is None and nom is None and etape is None


class TestMachinesPlaines:
    def test_centri_pleine_renvoie_none_pas_paillasse(self):
        """
        SCÉNARIO DU BUG SUSPECT : les deux centris sont à file_max.
        Le tube NE doit PAS être dirigé vers la paillasse — il doit attendre.
        """
        tube = make_tube()
        # Remplir ct1 et ct2 à file_max
        machine_queues = {
            "ct1": [{}] * MACHINES["ct1"]["file_max"],   # 10 tubes fictifs
            "ct2": [{}] * MACHINES["ct2"]["file_max"],   # 10 tubes fictifs
        }
        machine, nom, etape = trouver_prochaine_machine(tube, MACHINES, machine_queues)

        # Résultat attendu : None, None, None  (tube reporté, pas sauté à pa1)
        assert machine is None, (
            f"Bug détecté : le tube a été envoyé à '{nom}' alors que toutes les centris sont pleines !"
        )
        assert etape is None, "Aucune étape ne devrait être assignée quand la machine est pleine."

    def test_workflow_intact_apres_machines_pleines(self):
        """Après un retour None (machines pleines), le workflow doit rester intact."""
        tube = make_tube()
        original = list(tube["workflow"])
        machine_queues = {
            "ct1": [{}] * MACHINES["ct1"]["file_max"],
            "ct2": [{}] * MACHINES["ct2"]["file_max"],
        }
        trouver_prochaine_machine(tube, MACHINES, machine_queues)
        assert tube["workflow"] == original, (
            "Le workflow a été altéré alors que les machines étaient pleines !"
        )

    def test_une_centri_libre_suffit(self):
        """Si ct1 est pleine mais ct2 est disponible, tube doit aller à ct2."""
        tube = make_tube()
        machine_queues = {
            "ct1": [{}] * MACHINES["ct1"]["file_max"],  # ct1 pleine
            # ct2 : vide
        }
        machine, nom, etape = trouver_prochaine_machine(tube, MACHINES, machine_queues)
        assert nom == "ct2", f"Devrait aller à ct2, est allé à '{nom}'"
        assert etape == "centi1"


class TestFillFirst:
    def test_prefere_machine_plus_petite_capacite_quand_toutes_vides(self):
        """Batch-first : à slots restants égaux... non, ct1(rem=4) < ct2(rem=10) → ct1 gagne.
        MACHINES : ct1 cap=4, ct2 cap=10. Quand les deux sont vides,
        ct1 a moins de slots restants → on la remplit en 4 tubes au lieu de 10.
        """
        tube = make_tube()
        _, nom, _ = trouver_prochaine_machine(tube, MACHINES, {})
        assert nom == "ct1", (
            f"Batch-first devrait choisir ct1 (remaining=4 < ct2 remaining=10) quand les deux "
            f"sont vides, obtenu '{nom}'"
        )

    def test_continue_a_remplir_machine_en_cours(self):
        """Si ct1 est déjà partiellement remplie (remaining=1), on la complète avant ct2.
        ct1 à 3/4 (remaining=1) vs ct2 à 0/10 (remaining=10) → ct1 gagne."""
        tube = make_tube()
        machine_queues = {
            "ct1": [{}, {}, {}],  # 3/4 = remaining 1
            "ct2": [],            # 0/10 = remaining 10
        }
        _, nom, _ = trouver_prochaine_machine(tube, MACHINES, machine_queues)
        assert nom == "ct1", (
            f"ct1 n'a plus qu'1 slot avant cycle (remaining=1 vs ct2 remaining=10), "
            f"doit être complétée en premier, obtenu '{nom}'"
        )

    def test_prefere_machine_au_seuil_le_plus_proche(self):
        """Parmi deux machines non vides, préfère celle au seuil le plus proche.
        ct1 2/4 (remaining=2) vs ct2 5/10 (remaining=5) → ct1 gagne."""
        tube = make_tube()
        machine_queues = {
            "ct1": [{}, {}],             # 2/4 → remaining 2
            "ct2": [{}, {}, {}, {}, {}], # 5/10 → remaining 5
        }
        _, nom, _ = trouver_prochaine_machine(tube, MACHINES, machine_queues)
        assert nom == "ct1", (
            f"ct1 est plus proche du seuil (remaining=2 vs ct2 remaining=5), "
            f"doit être choisie, obtenu '{nom}'"
        )

    def test_4_tubes_tous_en_ct1_via_virtual_queues(self):
        """Scénario utilisateur : 4 tubes de l'entrée, ct1 cap=4, ct2 cap=10, toutes vides.
        Les 4 tubes doivent TOUS aller en ct1 pour déclencher le cycle immédiatement,
        plutôt que d'être répartis ct1:1/ct2:3 qui laisse les deux machines en attente.
        """
        virtual_queues = {}
        destinations = []
        for _ in range(4):
            tube = make_tube()
            _, nom, _ = trouver_prochaine_machine(tube, MACHINES, {}, virtual_queues)
            destinations.append(nom)
            virtual_queues[nom] = virtual_queues.get(nom, 0) + 1
        assert all(d == "ct1" for d in destinations), (
            f"4 tubes devraient tous aller en ct1 (cap=4) pour déclencher le cycle : "
            f"obtenu {destinations}"
        )

    def test_debordement_vers_ct2_quand_ct1_pleine(self):
        """Après ct1 pleine (via virtual_queues), le 5e tube déborde vers ct2."""
        virtual_queues = {"ct1": 4}   # ct1 saturée (cap=4)
        tube = make_tube()
        _, nom, _ = trouver_prochaine_machine(tube, MACHINES, {}, virtual_queues)
        assert nom == "ct2", (
            f"ct1 pleine → débordement vers ct2, obtenu '{nom}'"
        )

    def test_virtual_queues_bloquent_attribution(self):
        """
        virtual_queues simule des tubes déjà attribués dans le même batch.
        Si ct1 est remplie via virtual + réelle, doit aller à ct2.
        """
        tube = make_tube()
        machine_queues = {"ct1": [{}] * 8}  # 8 tubes réels dans ct1 (file_max=10 → 2 places)
        virtual_queues = {"ct1": 2}          # 2 autres déjà attribués dans ce batch → ct1 pleine
        _, nom, _ = trouver_prochaine_machine(tube, MACHINES, machine_queues, virtual_queues)
        assert nom == "ct2", f"ct1 devrait être pleine (via virtual_queues), doit aller à ct2, obtenu '{nom}'"


class TestÉtapeSansConfigMachine:
    def test_etape_inconnue_est_sautee(self, capsys):
        """Une étape sans machine dans la config est ignorée et on passe à la suivante."""
        tube = make_tube(workflow=["etape_fantome", "centi1", "culot 1", "proto1"])
        machine, nom, etape = trouver_prochaine_machine(tube, MACHINES, {})

        # L'étape fantôme doit avoir été sautée
        assert etape == "centi1", f"Étape après saut : attendu 'centi1', obtenu '{etape}'"
        assert "etape_fantome" not in tube["workflow"], "L'étape fantôme n'a pas été retirée du workflow"

        # Un warning doit avoir été imprimé
        captured = capsys.readouterr()
        assert "etape_fantome" in captured.out, "Aucun warning imprimé pour l'étape inconnue"

    def test_workflow_réduit_à_une_seule_étape_inconnue(self):
        """Un tube dont le seul workflow est une étape inconnue doit finir en (None, None, None)."""
        tube = make_tube(workflow=["etape_fantome"])
        machine, nom, etape = trouver_prochaine_machine(tube, MACHINES, {})
        assert machine is None and etape is None


class TestIntégration:
    def test_séquence_complète_de_dépôts(self):
        """
        Simule les 3 dépôts successifs d'un tube :
          centi1  → pop → culot 1 → pop → proto1 → pop → workflow vide
        Vérifie que chaque dépôt pointe vers la bonne machine ET que le workflow
        est consommé pas à pas (comme le fait _livrer_tubes).
        """
        tube = make_tube()
        machine_queues = {}

        # Étape 1 : doit aller en centri
        m, nom, etape = trouver_prochaine_machine(tube, MACHINES, machine_queues)
        assert etape == "centi1"
        assert nom in ("ct1", "ct2")
        # Simule le dépôt : pop l'étape
        tube["workflow"].pop(0)
        machine_queues.setdefault(nom, []).append(tube)

        # Étape 2 : doit aller en paillasse
        machine_queues_sans_centri = {k: v for k, v in machine_queues.items()}
        m2, nom2, etape2 = trouver_prochaine_machine(tube, MACHINES, machine_queues_sans_centri)
        assert etape2 == "culot 1", f"Attendu 'culot 1', obtenu '{etape2}'"
        assert nom2 == "pa1"
        tube["workflow"].pop(0)

        # Étape 3 : doit aller en automate
        m3, nom3, etape3 = trouver_prochaine_machine(tube, MACHINES, {})
        assert etape3 == "proto1"
        assert nom3 == "au1"
        tube["workflow"].pop(0)

        # Étape 4 : workflow vide → sortie
        m4, nom4, etape4 = trouver_prochaine_machine(tube, MACHINES, {})
        assert m4 is None and etape4 is None, "Workflow épuisé devrait retourner None"
