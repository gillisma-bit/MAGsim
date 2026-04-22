"""Benchmark : 10 × 7 jours de simulation — avec vs sans IA (Qwen 2.5 32B).

Usage
-----
    python -m tests.benchmark_ia              # depuis la racine du projet
    python -m tests.benchmark_ia --runs 5     # nombre de runs par groupe
    python -m tests.benchmark_ia --no-ia      # seulement le groupe sans IA
    python -m tests.benchmark_ia --ia-only    # seulement le groupe avec IA

Résultats affichés sur stdout + enregistrés dans tests/benchmark_ia_results.json.

Métriques comparées
-------------------
- TAT moyen (minutes) — transit time moyen par tube
- TAT P95  (minutes) — 95e percentile
- Tubes sortis      — débit total
- Tubes dégradés    — % de tubes ayant dépassé 80 % de leur durée de validité
- Tubes périmés     — tubes éjectés hors délai
- Stress CRITIQUE   — nombre de snapshots coordinateur en zone CRITIQUE
- Appels IA         — nombre de réponses IA reçues (0 si IA désactivée)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time

# ── Chemin racine du projet ──────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from unittest.mock import MagicMock, patch

# ── Paramètres ────────────────────────────────────────────────────────────────
DUREE_7J = 7 * 24 * 60   # 10 080 minutes SimPy
N_RUNS   = 10             # Peut être surchargé en ligne de commande


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_tab(ia_active: bool):
    """Crée un TabLive headless-compatible avec widgets Tkinter mockés."""
    from core.config_manager import ConfigManager
    from ui.tab_live import TabLive

    cm = ConfigManager()

    mock_widget = MagicMock()
    mock_widget.winfo_exists.return_value = False

    with (
        patch("ui.tab_live.tk.Canvas",       return_value=mock_widget),
        patch("ui.tab_live.ttk.Scrollbar",   return_value=MagicMock()),
        patch("ui.tab_live.ttk.Frame",       return_value=MagicMock()),
        patch("ui.tab_live.ttk.Button",      return_value=MagicMock()),
        patch("ui.tab_live.ttk.Label",       return_value=MagicMock()),
        patch("ui.tab_live.ttk.Checkbutton", return_value=MagicMock()),
        patch("ui.tab_live.tk.BooleanVar",   return_value=MagicMock()),
    ):
        tab = TabLive(MagicMock(), cm)

    tab.canvas = mock_widget
    tab.coordinateur.ia_active = ia_active
    return tab


def _run_one(tab, seed: int, timeout_s: float = 600.0) -> dict:
    """Lance une simulation complète de 7 jours, retourne les métriques."""
    done = threading.Event()
    tab.lancer_simulation_headless(DUREE_7J, on_complete=lambda: done.set(), seed=seed)
    ok = done.wait(timeout=timeout_s)
    if not ok:
        raise TimeoutError(f"Simulation seed={seed} n'a pas terminé en {timeout_s:.0f} s")

    tat     = tab.transit_times_raw or []
    events  = tab.stats_history.get("stress_events", [])
    n_crit  = sum(1 for e in events if e.get("zone") == "CRITIQUE")
    n_ia    = sum(1 for e in events if "ia_reponse" in e)

    return {
        "seed"         : seed,
        "tubes_sortis" : tab.tubes_sortis,
        "tubes_degrades": tab.tubes_degrades,
        "tubes_perimes" : tab.tubes_perimes,
        "tat_n"        : len(tat),
        "tat_mean"     : round(statistics.mean(tat), 2)     if tat else None,
        "tat_p95"      : round(_percentile(tat, 95), 2)     if tat else None,
        "tat_max"      : round(max(tat), 2)                  if tat else None,
        "stress_critique": n_crit,
        "appels_ia"    : n_ia,
    }


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    s  = sorted(data)
    k  = (len(s) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (k - lo) * (s[hi] - s[lo])


def _mean_or_na(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.mean(vals), 2) if vals else "N/A"


def _std_or_na(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.stdev(vals), 2) if len(vals) >= 2 else "N/A"


# ─────────────────────────────────────────────────────────────────────────────
#  Boucle principale
# ─────────────────────────────────────────────────────────────────────────────

def run_group(ia_active: bool, n_runs: int, seeds: list[int]) -> list[dict]:
    label = "AVEC IA" if ia_active else "SANS IA"
    print(f"\n{'='*60}")
    print(f"  Groupe : {label}  ({n_runs} simulations × 7 jours)")
    print(f"{'='*60}")

    resultats = []
    for i, seed in enumerate(seeds[:n_runs], 1):
        t0  = time.time()
        tab = _make_tab(ia_active)
        try:
            r = _run_one(tab, seed)
            elapsed = time.time() - t0
            status  = (
                f"  [{i:2d}/{n_runs}] seed={seed:5d}"
                f"  TAT={r['tat_mean']:7.1f} min"
                f"  P95={r['tat_p95']:7.1f}"
                f"  sortis={r['tubes_sortis']:5d}"
                f"  dégradés={r['tubes_degrades']:4d}"
                f"  crit={r['stress_critique']:3d}"
            )
            if ia_active:
                status += f"  ia_calls={r['appels_ia']:3d}"
            status += f"  ({elapsed:.0f}s)"
            print(status)
            resultats.append(r)
        except TimeoutError as e:
            print(f"  [{i:2d}/{n_runs}] TIMEOUT — {e}")
        except Exception as e:
            import traceback
            print(f"  [{i:2d}/{n_runs}] ERREUR — {e}")
            traceback.print_exc()
    return resultats


def print_comparison(sans_ia: list[dict], avec_ia: list[dict]):
    def col(data, key):
        return [r[key] for r in data if key in r]

    metrics = [
        ("TAT moyen (min)",   "tat_mean"),
        ("TAT P95   (min)",   "tat_p95"),
        ("TAT max   (min)",   "tat_max"),
        ("Tubes sortis",      "tubes_sortis"),
        ("Tubes dégradés",    "tubes_degrades"),
        ("Tubes périmés",     "tubes_perimes"),
        ("Stress CRITIQUE",   "stress_critique"),
        ("Appels IA",         "appels_ia"),
    ]

    print(f"\n{'='*70}")
    print(f"  {'Métrique':<22}  {'SANS IA':>12}  {'SANS IA σ':>10}  {'AVEC IA':>12}  {'AVEC IA σ':>10}")
    print(f"  {'-'*22}  {'-'*12}  {'-'*10}  {'-'*12}  {'-'*10}")

    for label, key in metrics:
        s_vals = col(sans_ia, key)
        a_vals = col(avec_ia, key)
        s_mean = _mean_or_na(s_vals)
        s_std  = _std_or_na(s_vals)
        a_mean = _mean_or_na(a_vals)
        a_std  = _std_or_na(a_vals)
        # Marquer la différence si la métrique est numérique
        diff = ""
        try:
            delta = float(a_mean) - float(s_mean)
            pct   = 100 * delta / float(s_mean) if float(s_mean) != 0 else 0
            sign  = "▲" if delta > 0 else "▼"
            diff  = f"  {sign}{abs(pct):.1f}%"
        except (ValueError, TypeError):
            pass
        print(f"  {label:<22}  {str(s_mean):>12}  {str(s_std):>10}  {str(a_mean):>12}  {str(a_std):>10}{diff}")

    print(f"{'='*70}")


def save_results(sans_ia: list[dict], avec_ia: list[dict], path: str):
    out = {
        "parametres": {"duree_7j_min": DUREE_7J, "n_runs": len(sans_ia) + len(avec_ia)},
        "sans_ia":    sans_ia,
        "avec_ia":    avec_ia,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n  Résultats JSON enregistrés dans : {path}")


# ─────────────────────────────────────────────────────────────────────────────
#  Point d'entrée
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Benchmark IA vs sans-IA — MAGsim")
    parser.add_argument("--runs",    type=int,  default=N_RUNS, help="Simulations par groupe")
    parser.add_argument("--no-ia",   action="store_true",       help="Seulement groupe sans IA")
    parser.add_argument("--ia-only", action="store_true",       help="Seulement groupe avec IA")
    parser.add_argument("--out",     type=str,
                        default=os.path.join(os.path.dirname(__file__), "benchmark_ia_results.json"),
                        help="Fichier JSON de sortie")
    args = parser.parse_args()

    # Graines fixes pour reproductibilité inter-groupes
    seeds = [42 + i * 17 for i in range(max(args.runs, N_RUNS))]

    sans_ia_results: list[dict] = []
    avec_ia_results: list[dict] = []

    if not args.ia_only:
        sans_ia_results = run_group(ia_active=False, n_runs=args.runs, seeds=seeds)

    if not args.no_ia:
        avec_ia_results = run_group(ia_active=True,  n_runs=args.runs, seeds=seeds)

    if sans_ia_results and avec_ia_results:
        print_comparison(sans_ia_results, avec_ia_results)

    if sans_ia_results or avec_ia_results:
        save_results(sans_ia_results, avec_ia_results, args.out)


if __name__ == "__main__":
    main()
