"""NORMAL vs IA PROSPECTIF -- MAGsim

Compare 2 conditions a graine identique (2 jours de simulation) :
  NORMAL       -- le labo reagit uniquement a l'arrivee des echantillons.
                  Aucune connaissance de ce qui est en route.
  IA PROSPECTIF -- le coordinateur Qwen voit les tubes deja en transit/queue
                   (ETA exactes) ET peut agir avant leur arrivee
                   (reequilibrage SJF + ajustement des poids via Qwen).

Usage
-----
    python -m tests.test_prospectif
    python -m tests.test_prospectif --jours 1 --seeds 42
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from unittest.mock import MagicMock, patch

SEEDS = [42, 137, 256]
SEP   = "-" * 74
SEP2  = "=" * 74


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _make_tab(ia_active: bool, anticipation_active: bool):
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

    tab.canvas                       = mock_widget
    tab.coordinateur.ia_active       = ia_active
    tab.coordinateur.cooldown_ia_min = 60.0
    tab.anticipation_active          = anticipation_active
    return tab


def _run(tab, duree_min: int, seed: int, timeout_s: float = 1200.0) -> dict:
    done = threading.Event()
    tab.lancer_simulation_headless(duree_min, on_complete=lambda: done.set(), seed=seed)
    if not done.wait(timeout=timeout_s):
        raise TimeoutError(f"Simulation seed={seed} non terminee en {timeout_s:.0f} s")

    events        = tab.stats_history.get("stress_events", [])
    anticipations = tab.stats_history.get("anticipations", [])
    tat           = tab.transit_times_raw or []
    tat_urg       = getattr(tab, "transit_times_urgents", []) or []
    n_crit        = sum(1 for e in events if e.get("zone") == "CRITIQUE")
    rush_events   = [e for e in events if e.get("prospectif", {}).get("rush_detecte")]
    ia_events     = [e for e in events if "ia_reponse" in e]

    return {
        "tubes_sortis"      : tab.tubes_sortis,
        "tubes_degrades"    : tab.tubes_degrades,
        "tubes_perimes"     : tab.tubes_perimes,
        "tat_mean"          : round(statistics.mean(tat), 1)     if tat else None,
        "tat_p95"           : round(_p95(tat), 1)                if tat else None,
        "tat_urgents_mean"  : round(statistics.mean(tat_urg), 1) if tat_urg else None,
        "tat_urgents_p95"   : round(_p95(tat_urg), 1)            if tat_urg else None,
        "n_urgents_sortis"  : len(tat_urg),
        "stress_critique"   : n_crit,
        "rush_detectes"     : len(rush_events),
        "nb_anticipations"  : len(anticipations),
        "reord_tubes_total" : sum(a.get("queue_reordonnee", 0) for a in anticipations),
        "appels_ia"         : len(ia_events),
        "_ia_events"        : ia_events,
        "_anticipations"    : anticipations,
    }


def _p95(data):
    if not data:
        return 0.0
    s  = sorted(data)
    k  = (len(s) - 1) * 0.95
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (k - lo) * (s[hi] - s[lo])


def _fmt(val):
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{val:.1f}"
    return str(val)


def _delta(base_val, cmp_val, lower_is_better=True):
    if base_val is None or cmp_val is None or base_val == 0:
        return "N/A", " "
    d    = cmp_val - base_val
    pct  = 100 * d / base_val
    good = (lower_is_better and d < 0) or (not lower_is_better and d > 0)
    icon = ("OK" if good else ("!! " if d != 0 else "->"))
    return f"{'+'if d>=0 else ''}{pct:.1f}%", icon


# ---------------------------------------------------------------------------
#  Affichage
# ---------------------------------------------------------------------------

LIGNES = [
    ("TAT moyen -- tous (min)",    "tat_mean",          True),
    ("TAT P95  -- tous (min)",     "tat_p95",           True),
    ("TAT moyen -- urgents (min)", "tat_urgents_mean",  True),
    ("TAT P95  -- urgents (min)",  "tat_urgents_p95",   True),
    ("Urgents sortis",             "n_urgents_sortis",  False),
    ("Tubes sortis",               "tubes_sortis",      False),
    ("Tubes degrades",             "tubes_degrades",    True),
    ("Tubes perimes",              "tubes_perimes",     True),
    ("Ticks en CRITIQUE",          "stress_critique",   True),
    ("Rush detectes",              "rush_detectes",     False),
    ("Reordonnements SJF",         "nb_anticipations",  False),
    ("Tubes reordonnes (cumul)",   "reord_tubes_total", False),
    ("Appels IA (Qwen)",           "appels_ia",         False),
]


def print_paire(seed, normal, ia_prosp):
    print(f"\n  Seed {seed}")
    print(f"  {'Metrique':<30}  {'NORMAL':>10}  {'IA PROSP.':>10}  {'Delta':>11}")
    print(f"  {'-'*30}  {'-'*10}  {'-'*10}  {'-'*11}")

    for label, key, lib in LIGNES:
        nv = normal.get(key)
        pv = ia_prosp.get(key)
        d, icon = _delta(nv, pv, lower_is_better=lib)
        print(f"  {label:<30}  {_fmt(nv):>10}  {_fmt(pv):>10}  {icon} {d:>8}")

    antici = ia_prosp.get("_anticipations", [])
    if antici:
        print(f"\n  Reordonnements SJF (seed {seed}) -- {len(antici)} evenements :")
        for a in antici[:4]:
            t_h  = round(a.get("t", 0) / 60, 1)
            nb_e = a.get("nb_entrants_prevus", 0)
            nb_u = a.get("nb_urgents_prevus", 0)
            nb_r = a.get("queue_reordonnee", 0)
            svcs = ", ".join(f"{k}:{v}" for k, v in a.get("par_service", {}).items())
            print(f"    t={t_h:5.1f}h  {nb_e:2} tubes attendus ({nb_u} urgents)"
                  f"  {nb_r} reordonnes  [{svcs}]")
        if len(antici) > 4:
            print(f"    ... et {len(antici)-4} autres")

    ia_ev = ia_prosp.get("_ia_events", [])
    if ia_ev:
        print(f"\n  Interventions IA (seed {seed}) -- {len(ia_ev)} appels Qwen :")
        for ev in ia_ev[:4]:
            r    = ev["ia_reponse"]
            t_h  = round(ev.get("t", 0) / 60, 1)
            zone = ev.get("zone", "?")
            act  = r.get("action", "?")
            mu   = r.get("mult_urgence", "?")
            mv   = r.get("mult_validite", "?")
            jus  = r.get("justification", "")
            pr   = ev.get("prospectif", {})
            rush = f"rush({pr.get('nb_entrants_prevus',0)})" if pr.get("rush_detecte") else ""
            print(f"    t={t_h:5.1f}h  {zone:<10}  {act:<14}  mu={mu}  mv={mv}  {rush}")
            print(f"      << {jus} >>")
        if len(ia_ev) > 4:
            print(f"    ... et {len(ia_ev)-4} autres")


def print_synthese(resultats):
    print(f"\n{SEP2}")
    print(f"  SYNTHESE -- {len(resultats)} paires  |  NORMAL vs IA PROSPECTIF")
    print(f"{SEP2}")

    for key, label, lib in LIGNES[:-3]:
        n_vals = [r["normal"].get(key)   for r in resultats if r["normal"].get(key)   is not None]
        p_vals = [r["ia_prosp"].get(key) for r in resultats if r["ia_prosp"].get(key) is not None]
        if not n_vals or not p_vals:
            continue
        n_m  = statistics.mean(n_vals)
        p_m  = statistics.mean(p_vals)
        d    = p_m - n_m
        pct  = 100 * d / n_m if n_m else 0
        good = (lib and d < 0) or (not lib and d > 0)
        icon = "[OK]" if good else "[!!]"
        print(f"  {icon} {label:<32}  normal={n_m:7.1f}  ia_prosp={p_m:7.1f}"
              f"  D={'+'if d>=0 else ''}{pct:.1f}%")

    total_antici = sum(r["ia_prosp"].get("nb_anticipations", 0) for r in resultats)
    total_reord  = sum(r["ia_prosp"].get("reord_tubes_total", 0) for r in resultats)
    total_ia     = sum(r["ia_prosp"].get("appels_ia", 0) for r in resultats)
    print(f"\n  Reordonnements SJF (toutes paires) : {total_antici} evt, {total_reord} tubes")
    print(f"  Appels Qwen total                  : {total_ia}")
    print(SEP2)


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NORMAL vs IA PROSPECTIF -- MAGsim")
    parser.add_argument("--jours",   type=float, default=2.0)
    parser.add_argument("--seeds",   type=int, nargs="+", default=SEEDS)
    parser.add_argument("--timeout", type=float, default=1200.0)
    args = parser.parse_args()

    duree = int(args.jours * 1440)

    print(f"\n{SEP2}")
    print(f"  NORMAL vs IA PROSPECTIF -- {args.jours:.1f} jour(s) x {len(args.seeds)} paires")
    print(f"  NORMAL    : labo reactif -- traite les tubes a leur arrivee")
    print(f"  IA PROSP. : Qwen + reequilibrage SJF avant l'arrivee")
    print(SEP2)

    try:
        import ollama
        models = [m.model for m in ollama.list().models]
        qwen_ok = any("qwen2.5:32b" in m for m in models)
        print(f"  Ollama : {'[OK] qwen2.5:32b disponible' if qwen_ok else '[!!] qwen2.5:32b introuvable'}")
    except Exception as e:
        print(f"  [!!] Ollama inaccessible ({e})")
    print()

    resultats = []
    for seed in args.seeds:
        print(SEP)
        print(f"  Seed={seed}  |  {args.jours:.1f} jour(s)")
        print(SEP)

        print(f"  [1/2] NORMAL         ... ", end="", flush=True)
        try:
            tab_n  = _make_tab(ia_active=False, anticipation_active=False)
            r_norm = _run(tab_n, duree, seed, timeout_s=args.timeout)
            print(f"OK  {r_norm['tubes_sortis']} tubes  TAT={r_norm['tat_mean']} min")
        except Exception as e:
            print(f"ERREUR  {e}")
            continue

        print(f"  [2/2] IA PROSPECTIF  ... ", end="", flush=True)
        try:
            tab_p   = _make_tab(ia_active=True, anticipation_active=True)
            r_prosp = _run(tab_p, duree, seed, timeout_s=args.timeout)
            print(f"OK  {r_prosp['tubes_sortis']} tubes  TAT={r_prosp['tat_mean']} min"
                  f"  appels_ia={r_prosp['appels_ia']}"
                  f"  reord.={r_prosp['nb_anticipations']}")
        except Exception as e:
            print(f"ERREUR  {e}")
            continue

        print_paire(seed, r_norm, r_prosp)
        resultats.append({"seed": seed, "normal": r_norm, "ia_prosp": r_prosp})

    if len(resultats) >= 2:
        print_synthese(resultats)
    elif len(resultats) == 1:
        print("\n  (une seule paire -- pas de synthese multi-runs)")

    print()


if __name__ == "__main__":
    main()
