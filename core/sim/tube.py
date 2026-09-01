"""core/sim/tube.py — Entité Tube, unité de base de toute simulation MAGsim.

Règles :
- Aucun import Tkinter, SimPy ou UI dans ce fichier.
- Tube est une dataclass mutable (le workflow se consume au fil du traitement).
- Les champs finance (cost_entries) sont remplis par core/finance/ via l'EventBus.
- Compatible Python 3.8+ (pas de X | Y dans les type hints).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Tube:
    """Représente un échantillon biologique traversant le système.

    Cycle de vie :
      génération → navette → entry_queue → machine(s) → sortie

    Champs immuables à la création :
      type, workflow_initial, couleur, fournisseur, departement_source

    Champs mutables pendant la simulation :
      workflow      : étapes restantes (pop à chaque dépôt en machine)
      arrivee       : mis à jour à l'arrivée effective au labo (après navette)
      urgent        : peut passer à True par escalade
      cost_entries  : alimenté par core/finance/ledger.py via EventBus
    """

    # ── Identité ─────────────────────────────────────────────────────────────
    id: int                         # unique dans la simulation courante
    type: str                       # clé dans config types_tubes
    couleur: str                    # couleur d'affichage (hex)
    fournisseur: str = ""           # fid du fournisseur source
    departement_source: str = ""    # dept d'origine (pour inter-dept futur)

    # ── Workflow ──────────────────────────────────────────────────────────────
    workflow: List[str] = field(default_factory=list)
    # Snapshot immuable de la liste initiale — pour audit et finance
    workflow_initial: List[str] = field(default_factory=list)

    # ── Temporel ─────────────────────────────────────────────────────────────
    t_generation: float = 0.0       # t SimPy de création chez le fournisseur
    arrivee: float = 0.0            # t SimPy d'arrivée effective au labo
    duree_validite: float = 0.0     # 0 = pas de péremption

    # ── Priorité ─────────────────────────────────────────────────────────────
    urgent: bool = False
    escalade: int = 0               # 0=non, 1=niveau1, 2=niveau2

    # ── État ─────────────────────────────────────────────────────────────────
    perime: bool = False
    rejete: bool = False

    # ── Finance — alimenté par core/finance/ ─────────────────────────────────
    cost_entries: List[dict] = field(default_factory=list)

    # ── Canvas Tkinter — géré uniquement par ui/ ─────────────────────────────
    # Stocké ici pour éviter un dict séparé, mais jamais lu par core/.
    canvas_id: Optional[int] = None

    def etape_courante(self) -> Optional[str]:
        """Retourne la prochaine étape du workflow sans la consommer."""
        return self.workflow[0] if self.workflow else None

    def consommer_etape(self) -> Optional[str]:
        """Retire et retourne la première étape du workflow."""
        return self.workflow.pop(0) if self.workflow else None

    def est_termine(self) -> bool:
        """True si le workflow est vide (tube prêt pour la sortie)."""
        return len(self.workflow) == 0

    def age(self, t_now: float) -> float:
        """Âge du tube depuis son arrivée au labo (minutes SimPy)."""
        return t_now - self.arrivee

    def ratio_validite(self, t_now: float) -> float:
        """Part de la durée de validité consommée (0.0–1.0). 0 si pas de validité."""
        if self.duree_validite <= 0:
            return 0.0
        return min(1.0, self.age(t_now) / self.duree_validite)

    def score_priorite(self, t_now: float,
                       mult_urgence: float = 1.0,
                       mult_validite: float = 1.0,
                       mult_age: float = 1.0) -> float:
        """Score de priorité : plus élevé = traiter EN PREMIER.

        Trois composantes :
          1. Urgence absolue      : +1 000 000 (toujours devant les non-urgents)
          2. Ratio validité × mv : tubes proches de la péremption prioritaires
          3. Ancienneté × ma     : tiebreaker FIFO entre tubes équivalents
        """
        score = 0.0
        if self.urgent:
            score += 1_000_000 * mult_urgence
        score += self.ratio_validite(t_now) * 1_000 * mult_validite
        score += self.age(t_now) * mult_age
        return score

    def to_dict(self) -> dict:
        """Sérialisation pour snapshot UI et logs — sans canvas_id."""
        return {
            "id":                self.id,
            "type":              self.type,
            "couleur":           self.couleur,
            "fournisseur":       self.fournisseur,
            "departement_source": self.departement_source,
            "workflow":          list(self.workflow),
            "workflow_initial":  list(self.workflow_initial),
            "t_generation":      self.t_generation,
            "arrivee":           self.arrivee,
            "duree_validite":    self.duree_validite,
            "urgent":            self.urgent,
            "escalade":          self.escalade,
            "perime":            self.perime,
            "rejete":            self.rejete,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Tube":
        """Reconstruction depuis un dict (tests, replay)."""
        t = cls(
            id=d["id"],
            type=d["type"],
            couleur=d.get("couleur", "#3498db"),
            fournisseur=d.get("fournisseur", ""),
            departement_source=d.get("departement_source", ""),
            workflow=list(d.get("workflow", [])),
            workflow_initial=list(d.get("workflow_initial", d.get("workflow", []))),
            t_generation=d.get("t_generation", 0.0),
            arrivee=d.get("arrivee", 0.0),
            duree_validite=d.get("duree_validite", 0.0),
            urgent=d.get("urgent", False),
            escalade=d.get("escalade", 0),
            perime=d.get("perime", False),
            rejete=d.get("rejete", False),
        )
        return t
