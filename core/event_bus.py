"""EventBus — pub/sub synchrone léger, compatible SimPy.

Règles d'utilisation :
- Les modules communiquent UNIQUEMENT via l'EventBus (jamais d'import croisé
  entre core/sim/, core/finance/, core/department/, etc.)
- Les handlers sont appelés de manière synchrone dans le thread SimPy.
- Pas de dépendance Tkinter, SimPy ou autre framework dans ce fichier.

Événements standards (constantes) :
  TUBE_ARRIVE, TUBE_SORTI, TUBE_REJETE, TUBE_PERIME
  MACHINE_BATCH_DEBUT, MACHINE_BATCH_FIN, MACHINE_PANNE, MACHINE_REPAREE
  TECH_DEPLACEMENT
  TUBE_INTER_DEPT   ← transfert entre départements
"""

# ── Constantes d'événements ───────────────────────────────────────────────────
TUBE_ARRIVE        = "tube.arrive"
TUBE_SORTI         = "tube.sorti"
TUBE_REJETE        = "tube.rejete"
TUBE_PERIME        = "tube.perime"

MACHINE_BATCH_DEBUT = "machine.batch_debut"
MACHINE_BATCH_FIN   = "machine.batch_fin"
MACHINE_PANNE       = "machine.panne"
MACHINE_REPAREE     = "machine.reparee"

TECH_DEPLACEMENT   = "tech.deplacement"

TUBE_INTER_DEPT    = "tube.transfert_dept"


class EventBus:
    """Bus d'événements synchrone.

    Usage :
        bus = EventBus()
        bus.subscribe(TUBE_SORTI, lambda evt: print(evt))
        bus.publish(TUBE_SORTI, {"tube_id": 42, "t": 120.0})
    """

    def __init__(self):
        self._handlers: dict = {}   # {event_type: [callable, ...]}

    def subscribe(self, event_type: str, handler):
        """Abonner un callable à un type d'événement."""
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler):
        """Désabonner un callable."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def publish(self, event_type: str, payload: dict):
        """Publier un événement — tous les abonnés sont appelés immédiatement.

        Le payload doit toujours contenir au minimum "t" (temps SimPy courant).
        """
        for handler in self._handlers.get(event_type, []):
            handler(payload)

    def clear(self):
        """Réinitialiser tous les abonnements (utile entre deux simulations)."""
        self._handlers.clear()
