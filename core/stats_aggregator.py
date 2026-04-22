"""stats_aggregator.py — Agrégation multi-niveaux des métriques de simulation.

Architecture à 4 niveaux :

  N0 — Ring buffer (60 derniers ticks bruts, ~2 min sim)   → zoom incident temps réel
  N1 — Agrégats horaires (1 valeur/h, horizon 7 jours)      → analyse tactique
  N2 — Agrégats journaliers (1 valeur/j, horizon illimité)  → vue opérationnelle
  N3 — Résumés hebdomadaires (texte, horizon illimité)       → vue haut niveau LLM

Les niveaux N1/N2/N3 sont mis à jour à chaque tick d'échantillonnage de `tab_live`
via `StatsAggregator.tick(t, snapshot)`. N3 est généré automatiquement à chaque
passage d'une semaine.

Toutes les opérations sont O(1) par tick grâce aux accumulateurs Welford.
"""

from __future__ import annotations
import math
from collections import deque
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
#  Welford en ligne — moyenne + variance + min + max sans stocker les données
# ─────────────────────────────────────────────────────────────────────────────

class _Accumulateur:
    """Accumule mean/variance/min/max/count en O(1) par valeur."""

    __slots__ = ("n", "mean", "_M2", "vmin", "vmax", "_sum")

    def __init__(self):
        self.n    = 0
        self.mean = 0.0
        self._M2  = 0.0
        self.vmin = math.inf
        self.vmax = -math.inf
        self._sum = 0.0

    def ajouter(self, v: float):
        if v is None:
            return
        self.n    += 1
        self._sum += v
        delta      = v - self.mean
        self.mean += delta / self.n
        self._M2  += delta * (v - self.mean)
        if v < self.vmin:
            self.vmin = v
        if v > self.vmax:
            self.vmax = v

    def to_dict(self) -> dict:
        if self.n == 0:
            return {}
        return {
            "n":    self.n,
            "moy":  round(self.mean, 2),
            "min":  round(self.vmin, 2),
            "max":  round(self.vmax, 2),
            "std":  round(math.sqrt(self._M2 / self.n) if self.n > 1 else 0.0, 2),
        }


def _acc() -> _Accumulateur:
    return _Accumulateur()


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

MINUTES_PAR_HEURE  = 60.0
MINUTES_PAR_JOUR   = 1440.0
MINUTES_PAR_SEMAINE = 10080.0


def _heure(t: float) -> int:
    """Index horaire absolu depuis le début de la sim."""
    return int(t // MINUTES_PAR_HEURE)


def _jour(t: float) -> int:
    """Index journalier depuis le début de la sim (0-based)."""
    return int(t // MINUTES_PAR_JOUR)


def _semaine(t: float) -> int:
    """Index hebdomadaire depuis le début de la sim (0-based)."""
    return int(t // MINUTES_PAR_SEMAINE)


def _fmt_min(mn: float) -> str:
    mn = int(mn)
    return f"{mn // 60}h{mn % 60:02d}min"


def _fmt_jour(j: int) -> str:
    return f"j{j + 1}"


# ─────────────────────────────────────────────────────────────────────────────
#  Niveau 0 — Ring buffer brut (derniers 60 ticks)
# ─────────────────────────────────────────────────────────────────────────────

class _RingBuffer:
    def __init__(self, maxlen: int = 120):
        self._buf: deque = deque(maxlen=maxlen)

    def push(self, entry: dict):
        self._buf.append(entry)

    def all(self) -> list[dict]:
        return list(self._buf)

    def last(self) -> dict | None:
        return self._buf[-1] if self._buf else None


# ─────────────────────────────────────────────────────────────────────────────
#  StatsAggregator — point d'entrée principal
# ─────────────────────────────────────────────────────────────────────────────

class StatsAggregator:
    """Agrège en temps réel les métriques de simulation à 4 niveaux.

    Utilisation dans tab_live :
        self.aggregator = StatsAggregator()
        # dans _echantillonner_stats, après avoir mis à jour stats_history :
        self.aggregator.tick(t, self._snapshot_aggregation())
    """

    def __init__(self, ring_size: int = 120):
        # N0
        self._ring = _RingBuffer(ring_size)

        # N1 — horaire : {heure_abs: {serie: _Accumulateur}}
        self._h1: dict[int, dict[str, _Accumulateur]] = {}
        self._h1_t_debut: dict[int, float] = {}   # timestamp début de chaque heure

        # N2 — journalier : {jour: {serie: _Accumulateur}}
        self._h2: dict[int, dict[str, _Accumulateur]] = {}
        self._h2_t_debut: dict[int, float] = {}

        # N3 — résumés hebdo (texte) : list[(semaine, texte)]
        self._n3: list[tuple[int, str]] = []
        self._semaine_courante = -1

        # Suivi des bornes de temps
        self.t_debut: float | None = None
        self.t_fin:   float        = 0.0

        # Pannes / arrets maladie (événements ponctuels — stockés exhaustivement)
        self.events: list[dict] = []

    # ─── Méthode principale ──────────────────────────────────────────────────

    def tick(self, t: float, snapshot: dict):
        """Appelé à chaque tick d'échantillonnage.

        snapshot doit contenir les clés scalaires et par-machine :
          entry, transit_rolling, transit_pending_max,
          busy: {nom: 0|1}, queues: {nom: int}, transit_times_raw: [float]
          (optionnel) events: [dict]
        """
        if self.t_debut is None:
            self.t_debut = t
        self.t_fin = t

        # N0 — ring buffer
        self._ring.push({"t": t, **snapshot})

        # Préparer les séries scalaires du tick
        scalaires = self._extraire_scalaires(snapshot)

        # N1 — heure courante
        h = _heure(t)
        if h not in self._h1:
            self._h1[h] = {}
            self._h1_t_debut[h] = t
        self._accumuler(self._h1[h], scalaires)

        # N2 — jour courant
        j = _jour(t)
        if j not in self._h2:
            self._h2[j] = {}
            self._h2_t_debut[j] = t
        self._accumuler(self._h2[j], scalaires)

        # N3 — passage de semaine → compresser la semaine précédente
        s = _semaine(t)
        if s != self._semaine_courante and self._semaine_courante >= 0:
            self._compresser_semaine(self._semaine_courante)
        self._semaine_courante = s

        # Événements ponctuels
        for ev in snapshot.get("events", []):
            self.events.append(ev)

    # ─── Extraction scalaires ────────────────────────────────────────────────

    def _extraire_scalaires(self, snap: dict) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        out["entry"]              = snap.get("entry")
        out["transit_rolling"]    = snap.get("transit_rolling")
        out["transit_pending"]    = snap.get("transit_pending_max")
        for nom, v in snap.get("busy", {}).items():
            out[f"busy_{nom}"] = float(v) if v is not None else None
        for nom, v in snap.get("queues", {}).items():
            out[f"queue_{nom}"] = float(v) if v is not None else None
        return out

    def _accumuler(self, bucket: dict[str, _Accumulateur], scalaires: dict):
        for cle, val in scalaires.items():
            if val is None:
                continue
            if cle not in bucket:
                bucket[cle] = _acc()
            bucket[cle].ajouter(val)

    # ─── Compression N3 ──────────────────────────────────────────────────────

    def _compresser_semaine(self, s: int):
        """Résume une semaine entière en texte lisible par le LLM."""
        j_debut = s * 7
        j_fin   = j_debut + 6
        jours   = [j for j in range(j_debut, j_fin + 1) if j in self._h2]
        if not jours:
            return

        lignes = [f"=== Semaine {s + 1} (j{j_debut + 1}–j{j_fin + 1}) ==="]

        # Transit rolling
        vals_tr = [self._h2[j]["transit_rolling"].mean for j in jours
                   if "transit_rolling" in self._h2[j] and self._h2[j]["transit_rolling"].n > 0]
        if vals_tr:
            moy = sum(vals_tr) / len(vals_tr)
            pic = max(vals_tr)
            tendance = "↗ en hausse" if vals_tr[-1] > vals_tr[0] * 1.1 else (
                       "↘ en baisse" if vals_tr[-1] < vals_tr[0] * 0.9 else "→ stable")
            lignes.append(f"  Transit moyen : {_fmt_min(moy)} — pic : {_fmt_min(pic)} — tendance : {tendance}")

        # Utilisation machines
        busy_moys: dict[str, list] = {}
        for j in jours:
            for cle, acc in self._h2[j].items():
                if cle.startswith("busy_") and acc.n > 0:
                    busy_moys.setdefault(cle[5:], []).append(acc.mean * 100)
        for nom, vals in busy_moys.items():
            moy_b = sum(vals) / len(vals)
            alerte = " ⚠SURCHARGÉ" if moy_b > 85 else (" (sous-utilisé)" if moy_b < 15 else "")
            lignes.append(f"  Utilisation {nom} : {moy_b:.0f}%{alerte}")

        # File d'entrée
        vals_entry = [self._h2[j]["entry"].mean for j in jours
                      if "entry" in self._h2[j] and self._h2[j]["entry"].n > 0]
        if vals_entry:
            lignes.append(f"  File entrée moy : {sum(vals_entry)/len(vals_entry):.1f} tubes — "
                          f"pic : {max(vals_entry):.0f} tubes")

        # Événements de la semaine
        t_debut_s = s * MINUTES_PAR_SEMAINE
        t_fin_s   = t_debut_s + MINUTES_PAR_SEMAINE
        evs = [e for e in self.events if t_debut_s <= e.get("t", 0) < t_fin_s]
        pannes  = [e for e in evs if e.get("type") == "panne"]
        arrets  = [e for e in evs if e.get("type") == "debut"]
        retours = [e for e in evs if e.get("type") == "retour"]
        if pannes:
            noms_p = list(dict.fromkeys(e["nom"] for e in pannes))
            lignes.append(f"  Pannes : {len(pannes)} — machines : {', '.join(noms_p)}")
        if arrets:
            noms_a = list(dict.fromkeys(e["nom"] for e in arrets))
            lignes.append(f"  Arrêts maladie : {len(arrets)} — {', '.join(noms_a)}")
        if retours:
            lignes.append(f"  Retours de congé maladie : {len(retours)}")

        self._n3.append((s, "\n".join(lignes)))

    # ─── Accès publics ───────────────────────────────────────────────────────

    @property
    def nb_jours(self) -> float:
        if self.t_debut is None:
            return 0.0
        return (self.t_fin - self.t_debut) / MINUTES_PAR_JOUR

    @property
    def nb_semaines_completes(self) -> int:
        return len(self._n3)

    def resumés_semaines(self) -> list[str]:
        """Texte des semaines compressées (N3)."""
        return [txt for _, txt in self._n3]

    def agrégats_jour(self, j: int) -> dict[str, dict]:
        """Agrégats N2 d'un jour donné (0-based)."""
        bucket = self._h2.get(j, {})
        return {cle: acc.to_dict() for cle, acc in bucket.items()}

    def agrégats_heure(self, h: int) -> dict[str, dict]:
        """Agrégats N1 d'une heure absolue donnée."""
        bucket = self._h1.get(h, {})
        return {cle: acc.to_dict() for cle, acc in bucket.items()}

    def ring_buffer(self) -> list[dict]:
        """Ticks bruts N0 (derniers ~2 min sim)."""
        return self._ring.all()

    def jours_disponibles(self) -> list[int]:
        return sorted(self._h2.keys())

    def heures_du_jour(self, j: int) -> list[int]:
        h_debut = j * 24
        h_fin   = h_debut + 24
        return [h for h in self._h1 if h_debut <= h < h_fin]

    def stats_raw_transit(self) -> dict:
        """Stats min/max/moy/p95 calculées via Welford sur les transits bruts."""
        return self._transit_acc.to_dict() if hasattr(self, "_transit_acc") else {}

    # ─── Métriques N2 toutes séries (pour injection contexte LLM) ────────────

    def bloc_vue_globale(self) -> str:
        """Bloc texte N2+N3 à injecter dans le prompt LLM — taille constante."""
        if not self._h2:
            return ""
        lignes = []

        nb_j = max(self._h2.keys()) + 1
        lignes.append(f"Durée totale simulée : {nb_j} jours")

        # ── Résumés N3 (semaines compressées)
        if self._n3:
            lignes.append("\n--- Historique hebdomadaire ---")
            for _, txt in self._n3:
                lignes.append(txt)

        # ── Semaine courante en détail N2
        s_cur = self._semaine_courante
        j_debut_cur = s_cur * 7
        jours_cur = [j for j in self._h2 if j >= j_debut_cur]
        if jours_cur:
            if self._n3:  # il y a déjà des semaines complètes
                lignes.append(f"\n--- Semaine courante (j{j_debut_cur + 1}–j{max(jours_cur) + 1}) ---")
            else:
                lignes.append("\n--- Données journalières ---")
            for j in sorted(jours_cur):
                ligne_j = self._résumé_jour(j)
                if ligne_j:
                    lignes.append(f"  {_fmt_jour(j)} : {ligne_j}")

        return "\n".join(lignes)

    def bloc_zoom_jour(self, j: int) -> str:
        """Bloc texte N1 pour un jour donné — injecté à la demande (zoom)."""
        heures = self.heures_du_jour(j)
        if not heures:
            return f"Aucune donnée pour {_fmt_jour(j)}."
        lignes = [f"=== Zoom {_fmt_jour(j)} — détail horaire ==="]
        for h in sorted(heures):
            heure_locale = h % 24
            acc = self._h1[h]
            parties = []
            if "transit_rolling" in acc and acc["transit_rolling"].n > 0:
                parties.append(f"transit {_fmt_min(acc['transit_rolling'].mean)}")
            if "entry" in acc and acc["entry"].n > 0:
                parties.append(f"file={acc['entry'].mean:.0f}")
            for cle, a in acc.items():
                if cle.startswith("busy_") and a.n > 0:
                    parties.append(f"{cle[5:]}={a.mean*100:.0f}%")
            lignes.append(f"  {heure_locale:02d}h : {' | '.join(parties) or '—'}")
        return "\n".join(lignes)

    def bloc_zoom_semaine(self, s: int) -> str:
        """Bloc texte N2 pour une semaine précise — injecté à la demande."""
        j_debut = s * 7
        j_fin   = j_debut + 6
        jours   = [j for j in self._h2 if j_debut <= j <= j_fin]
        if not jours:
            return f"Aucune donnée pour la semaine {s + 1}."
        lignes = [f"=== Zoom semaine {s + 1} (j{j_debut + 1}–j{j_fin + 1}) — détail journalier ==="]
        for j in sorted(jours):
            ligne_j = self._résumé_jour(j)
            lignes.append(f"  {_fmt_jour(j)} : {ligne_j or '—'}")
        return "\n".join(lignes)

    # ─── Interne ─────────────────────────────────────────────────────────────

    def _résumé_jour(self, j: int) -> str:
        acc = self._h2.get(j, {})
        if not acc:
            return ""
        parties = []
        if "transit_rolling" in acc and acc["transit_rolling"].n > 0:
            a = acc["transit_rolling"]
            parties.append(f"transit moy {_fmt_min(a.mean)} (pic {_fmt_min(a.vmax)})")
        if "transit_pending" in acc and acc["transit_pending"].n > 0:
            a = acc["transit_pending"]
            parties.append(f"retard max {_fmt_min(a.vmax)}")
        if "entry" in acc and acc["entry"].n > 0:
            a = acc["entry"]
            parties.append(f"file={a.mean:.0f} (pic {a.vmax:.0f})")
        surchargés = []
        for cle, a in acc.items():
            if cle.startswith("busy_") and a.n > 0:
                moy_pct = a.mean * 100
                if moy_pct > 85:
                    surchargés.append(f"{cle[5:]} {moy_pct:.0f}%⚠")
                elif moy_pct > 50:
                    surchargés.append(f"{cle[5:]} {moy_pct:.0f}%")
        if surchargés:
            parties.append("util:" + " ".join(surchargés))
        return " | ".join(parties)
