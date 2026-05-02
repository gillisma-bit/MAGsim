"""core/sim/machine.py — Machine de traitement SimPy (batch + respawn + panne).

Règles :
- Aucun import Tkinter dans ce fichier.
- La Machine est un générateur SimPy autonome : elle se respawn elle-même
  via env.process() à chaque batch tant qu'il reste des tubes en file.
- L'EventBus est le seul canal de communication vers l'extérieur (finance,
  stats, UI). La Machine ne connaît pas ses consommateurs.
- Pas de singleton : chaque machine est une instance indépendante.

Anti-deadlock garanti par conception :
  - _actif (bool) remplace _machines_batch_actif (set global partagé).
  - Le respawn passe TOUJOURS par env.process() — jamais de yield-from récursif.
  - Le finally du générateur remet _actif=False AVANT le respawn éventuel,
    ce qui est sûr car SimPy est single-threaded (aucune fenêtre de race).
"""

from __future__ import annotations
import random
from typing import List, Optional, Callable

import simpy

from core.sim.tube import Tube
from core import event_bus as eb


class Machine:
    """Machine de traitement par batch dans une simulation SimPy.

    Paramètres de configuration (tous issus du JSON config_mag.json) :
      nom          : identifiant unique (ex: "ct1")
      protocoles   : {etape: {"temps": float}}
      capacite     : taille de batch (nb tubes traités ensemble)
      file_max     : taille maximale de la file d'attente
      seuil        : nb minimum de tubes pour déclencher un batch urgent
      tmep         : temps moyen entre pannes (heures) — 0 = pas de panne
      tmr          : temps moyen de réparation (heures)
    """

    def __init__(
        self,
        env: simpy.Environment,
        nom: str,
        protocoles: dict,
        capacite: int = 4,
        file_max: Optional[int] = None,
        seuil: int = 1,
        tmep: float = 0.0,
        tmr: float = 0.0,
        event_bus: Optional[object] = None,
    ):
        self.env = env
        self.nom = nom
        self.protocoles = protocoles        # {etape: {"temps": float, ...}}
        self.capacite = capacite
        self.file_max = file_max if file_max is not None else capacite
        self.seuil = seuil
        self.tmep = tmep                    # heures
        self.tmr = tmr                      # heures
        self.event_bus = event_bus          # peut être None (tests sans bus)

        # ── État interne ──────────────────────────────────────────────────────
        self._queue: List[Tube] = []        # tubes en attente
        self._output: List[Tube] = []       # tubes traités prêts à ramasser
        self._actif: bool = False           # True = un batch est en cours
        self._en_panne: bool = False        # True = machine hors service
        self._repair_event: Optional[simpy.Event] = None

        # ── Métriques internes ────────────────────────────────────────────────
        self.nb_batches = 0
        self.nb_tubes_traites = 0
        self.nb_pannes = 0

    # ── Interface publique ────────────────────────────────────────────────────

    @property
    def queue_len(self) -> int:
        return len(self._queue)

    @property
    def output_len(self) -> int:
        return len(self._output)

    @property
    def busy(self) -> bool:
        return self._actif

    @property
    def en_panne(self) -> bool:
        return self._en_panne

    def accepte_tube(self) -> bool:
        """True si la file n'est pas pleine et la machine n'est pas en panne."""
        return len(self._queue) < self.file_max and not self._en_panne

    def enqueue(self, tube: Tube, tri_fn: Optional[Callable] = None) -> bool:
        """Ajouter un tube en file. Retourne False si la file est pleine.

        tri_fn : fonction de clé de tri optionnelle — appelée après l'ajout
                 pour maintenir l'ordre de priorité.
        """
        if len(self._queue) >= self.file_max:
            return False
        self._queue.append(tube)
        if tri_fn is not None:
            self._queue.sort(key=tri_fn, reverse=True)
        return True

    def drain_output(self) -> List[Tube]:
        """Retirer et retourner tous les tubes de la file de sortie."""
        tubes = list(self._output)
        self._output.clear()
        return tubes

    def snapshot(self) -> dict:
        """État courant sérialisable pour l'UI et les stats."""
        return {
            "nom":             self.nom,
            "queue":           self.queue_len,
            "output":          self.output_len,
            "busy":            self._actif,
            "en_panne":        self._en_panne,
            "nb_batches":      self.nb_batches,
            "nb_tubes_traites": self.nb_tubes_traites,
            "nb_pannes":       self.nb_pannes,
        }

    # ── Déclenchement du batch ────────────────────────────────────────────────

    def essayer_lancer_batch(self) -> bool:
        """Lancer un batch si les conditions sont réunies.

        Conditions :
          - File non vide
          - Pas de batch en cours (_actif == False)
          - Machine non en panne

        Retourne True si un batch a été lancé.
        """
        if self._actif or self._en_panne or not self._queue:
            return False
        has_urgent = any(t.urgent for t in self._queue)
        if len(self._queue) >= self.capacite or (has_urgent and len(self._queue) >= self.seuil):
            self._actif = True
            self.env.process(self._batch_process())
            return True
        return False

    # ── Processus SimPy ───────────────────────────────────────────────────────

    def _batch_process(self):
        """Générateur SimPy : traite un batch et se respawn si file non vide.

        Garantie anti-deadlock :
          - _actif = False dans le finally AVANT tout respawn.
          - SimPy est single-threaded : le bloc finally s'exécute atomiquement
            entre deux yields, aucune autre coroutine ne peut interférer.
        """
        _respawn = False
        try:
            # Prendre jusqu'à `capacite` tubes en tête de file
            batch = self._queue[:self.capacite]
            del self._queue[:self.capacite]

            # Déterminer le temps de traitement depuis les protocoles
            etape = next(iter(self.protocoles), None)
            temps_min = self.protocoles[etape].get("temps", 60) if etape else 60

            self._publier(eb.MACHINE_BATCH_DEBUT, {
                "machine":  self.nom,
                "batch_sz": len(batch),
                "etape":    etape,
                "temps":    temps_min,
                "q_apres":  len(self._queue),
            })

            # Temps SimPy = minutes réelles / 10 (compression ×10 de tab_live)
            yield self.env.timeout(temps_min / 10)

            # Attendre la réparation si panne survenue pendant le traitement
            if self._en_panne and self._repair_event is not None:
                if not self._repair_event.triggered:
                    yield self._repair_event

            # Déposer les tubes en sortie
            self._output.extend(batch)
            self.nb_batches += 1
            self.nb_tubes_traites += len(batch)

            self._publier(eb.MACHINE_BATCH_FIN, {
                "machine":  self.nom,
                "batch_sz": len(batch),
                "etape":    etape,
                "output_sz": len(self._output),
            })

            # Respawn si la file contient encore des tubes
            if self._queue:
                _respawn = True

        finally:
            # _actif = False AVANT le respawn : garantit qu'aucun doublon
            # ne peut être créé par un appelant extérieur entre ce finally
            # et le env.process() ci-dessous.
            self._actif = False
            if _respawn:
                self._actif = True
                self.env.process(self._batch_process())

    def _panne_process(self):
        """Processus SimPy optionnel : pannes aléatoires par loi exponentielle.

        À lancer avec env.process(machine._panne_process()) si tmep > 0.
        """
        if not self.tmep or not self.tmr:
            return
        tmep_min = self.tmep * 60
        tmr_min  = self.tmr  * 60

        while True:
            yield self.env.timeout(random.expovariate(1.0 / tmep_min))

            self._en_panne = True
            self.nb_pannes += 1
            self._repair_event = self.env.event()

            self._publier(eb.MACHINE_PANNE, {
                "machine": self.nom,
                "t":       self.env.now,
            })

            yield self.env.timeout(random.expovariate(1.0 / tmr_min))

            self._en_panne = False
            self._repair_event.succeed()
            self._repair_event = None

            self._publier(eb.MACHINE_REPAREE, {
                "machine": self.nom,
                "t":       self.env.now,
            })

    def _publier(self, event_type: str, payload: dict):
        """Publier un événement sur l'EventBus si disponible."""
        if self.event_bus is not None:
            payload.setdefault("t", self.env.now)
            self.event_bus.publish(event_type, payload)
