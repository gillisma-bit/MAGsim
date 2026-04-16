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
        "capacite": 4, "file_max": 10,
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
    def test_prefere_machine_proche_du_seuil(self):
        """fill-first : choisit la machine qui a le moins de place restante (plus proche de capacite)."""
        tube = make_tube()
        # ct1 a 3 tubes sur 4 (1 place libre), ct2 a 0 tubes (4 places libres)
        # fill-first → doit choisir ct1 (score = 4-3 = 1 < 4-0 = 4)
        machine_queues = {
            "ct1": [{}, {}, {}],  # 3/4 remplie
            "ct2": [],            # vide
        }
        _, nom, _ = trouver_prochaine_machine(tube, MACHINES, machine_queues)
        assert nom == "ct1", f"fill-first devrait choisir ct1 (presque pleine), obtenu '{nom}'"

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
