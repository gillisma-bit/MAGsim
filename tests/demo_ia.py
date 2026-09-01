"""Démonstration de l'impact de l'IA coordinatrice (Qwen 2.5 32B).

Lance 3 paires de simulations identiques (même graine aléatoire) :
  • Une fois SANS IA  — poids adaptatifs statiques par zone
  • Une fois AVEC IA  — Qwen ajuste dynamiquement les multiplicateurs en zone critique

Durée : 2 jours × 3 paires ≈ 2-5 min sans IA, + ~1-3 min/appel Qwen avec IA

Usage
-----
    python -m tests.demo_ia            # depuis la racine du projet
    python -m tests.demo_ia --jours 1  # plus rapide (1 jour par sim)
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


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_tab(ia_active: bool):
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
    tab.coordinateur.ia_active  = ia_active
    tab.coordinateur.cooldown_ia_min = 60.0   # 1 appel Qwen max par heure sim
    return tab


def _run(tab, duree_min: int, seed: int, timeout_s: float = 1200.0) -> dict:
    """Lance la simulation et collecte les métriques + interventions IA."""
    done = threading.Event()
    tab.lancer_simulation_headless(duree_min, on_complete=lambda: done.set(), seed=seed)
    if not done.wait(timeout=timeout_s):
        raise TimeoutError(f"Simulation seed={seed} n'a pas terminé en {timeout_s:.0f} s")

    events     = tab.stats_history.get("stress_events", [])
    tat        = tab.transit_times_raw or []
    tat_urg    = getattr(tab, "transit_times_urgents", []) or []
    n_crit     = sum(1 for e in events if e.get("zone") == "CRITIQUE")
    ia_events  = [e for e in events if "ia_reponse" in e]

    return {
        "tubes_sortis"    : tab.tubes_sortis,
        "tubes_degrades"  : tab.tubes_degrades,
        "tubes_perimes"   : tab.tubes_perimes,
        "tat_mean"        : round(statistics.mean(tat), 1)     if tat else None,
        "tat_p95"         : round(_p95(tat), 1)                if tat else None,
        "tat_urgents_mean": round(statistics.mean(tat_urg), 1) if tat_urg else None,
        "tat_urgents_p95" : round(_p95(tat_urg), 1)            if tat_urg else None,
        "n_urgents_sortis": len(tat_urg),
        "stress_critique" : n_crit,
        "appels_ia"       : len(ia_events),
        "ia_events"       : ia_events,
    }


def _p95(data):
    if not data:
        return 0.0
    s  = sorted(data)
    k  = (len(s) - 1) * 0.95
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (k - lo) * (s[hi] - s[lo])


def _delta(sans, avec, key, lower_is_better=True):
    """Calcule le delta et l'icône."""
    a = avec.get(key)
    s = sans.get(key)
    if a is None or s is None or s == 0:
        return "N/A", ""
    d = a - s
    pct = 100 * d / s
    if lower_is_better:
        icon = "✅" if d < 0 else ("⚠️ " if d > 0 else "➡️ ")
    else:
        icon = "✅" if d > 0 else ("⚠️ " if d < 0 else "➡️ ")
    signe = "+" if d >= 0 else ""
    return f"{signe}{pct:.1f}%", icon


# ─────────────────────────────────────────────────────────────────────────────
#  Affichage
# ─────────────────────────────────────────────────────────────────────────────

SEP = "─" * 72

def print_paire(seed, sans, avec):
    print(f"\n  Seed {seed}")
    print(f"  {'Métrique':<28}  {'SANS IA':>10}  {'AVEC IA':>10}  {'Δ':>10}  ")
    print(f"  {'─'*28}  {'─'*10}  {'─'*10}  {'─'*12}")

    lignes = [
        ("TAT moyen — tous (min)",      "tat_mean",         True),
        ("TAT P95  — tous (min)",        "tat_p95",          True),
        ("TAT moyen — urgents (min)",   "tat_urgents_mean", True),
        ("TAT P95  — urgents (min)",    "tat_urgents_p95",  True),
        ("Urgents sortis",              "n_urgents_sortis", False),
        ("Tubes sortis",                "tubes_sortis",     False),
        ("Tubes dégradés",              "tubes_degrades",   True),
        ("Tubes périmés",               "tubes_perimes",    True),
        ("Ticks en CRITIQUE",           "stress_critique",  True),
        ("Appels IA",                   "appels_ia",        False),
    ]
    for label, key, lib in lignes:
        sv = sans.get(key, "N/A")
        av = avec.get(key, "N/A")
        d, icon = _delta(sans, avec, key, lower_is_better=lib)
        print(f"  {label:<28}  {str(sv):>10}  {str(av):>10}  {icon} {d:>8}")

    # Afficher les recommandations IA
    ia_events = avec.get("ia_events", [])
    if ia_events:
        print(f"\n  ── Recommandations Qwen (seed {seed}) {'─'*30}")
        for ev in ia_events:
            r   = ev["ia_reponse"]
            mu  = r.get("mult_urgence", "?")
            mv  = r.get("mult_validite", "?")
            act = r.get("action", "?")
            jus = r.get("justification", "")
            h   = ev.get("facteur", 0.0)
            z   = ev.get("zone", "?")
            t_h = round(ev.get("t", 0) / 60, 1)
            print(f"    t={t_h:5.1f}h  {z:<10}  mu={mu}  mv={mv}  {act:<14}  « {jus} »")


def print_synthese(resultats):
    print(f"\n{'═'*72}")
    print(f"  SYNTHÈSE — {len(resultats)} paires")
    print(f"{'═'*72}")

    keys_lib = [
        ("tat_mean",         "TAT moyen — tous (min)",     True),
        ("tat_p95",          "TAT P95  — tous (min)",       True),
        ("tat_urgents_mean", "TAT moyen — urgents (min)",  True),
        ("tat_urgents_p95",  "TAT P95  — urgents (min)",   True),
        ("tubes_degrades",   "Tubes dégradés",             True),
        ("tubes_perimes",    "Tubes périmés",              True),
        ("stress_critique",  "Ticks en CRITIQUE",          True),
    ]

    for key, label, lib in keys_lib:
        sans_vals = [r["sans"].get(key) for r in resultats if r["sans"].get(key) is not None]
        avec_vals = [r["avec"].get(key) for r in resultats if r["avec"].get(key) is not None]
        if not sans_vals or not avec_vals:
            continue
        s_m = statistics.mean(sans_vals)
        a_m = statistics.mean(avec_vals)
        d   = a_m - s_m
        pct = 100 * d / s_m if s_m else 0
        icon = ("✅ " if (lib and d < 0) or (not lib and d > 0) else "⚠️  ")
        signe = "+" if d >= 0 else ""
        print(f"  {icon} {label:<28}  sans={s_m:7.1f}  avec={a_m:7.1f}  Δ={signe}{pct:.1f}%")

    total_appels = sum(r["avec"].get("appels_ia", 0) for r in resultats)
    print(f"\n  Total appels Qwen : {total_appels}")
    print(f"{'═'*72}")


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Démo IA coordinatrice — MAGsim")
    parser.add_argument("--jours",   type=float, default=2.0,
                        help="Durée de chaque simulation en jours (défaut 2)")
    parser.add_argument("--seeds",   type=int, nargs="+", default=SEEDS,
                        help="Graines aléatoires (défaut: 42 137 256)")
    parser.add_argument("--cooldown",type=float, default=60.0,
                        help="Cooldown IA en minutes sim (défaut 60)")
    parser.add_argument("--timeout", type=float, default=1200.0,
                        help="Timeout par simulation en secondes (défaut 1200)")
    args = parser.parse_args()

    duree = int(args.jours * 1440)
    print(f"\n{'═'*72}")
    print(f"  DÉMO IA COORDINATRICE — {args.jours:.1f} jour(s) × {len(args.seeds)} paires")
    print(f"  Cooldown Qwen : {args.cooldown:.0f} min sim  |  Modèle : qwen2.5:32b")
    print(f"{'═'*72}")

    # Vérification rapide Ollama
    try:
        import ollama
        models = [m.model for m in ollama.list().models]
        qwen_ok = any("qwen2.5:32b" in m for m in models)
        print(f"  Ollama : {'✅ qwen2.5:32b disponible' if qwen_ok else '⚠️  qwen2.5:32b introuvable — vérifiez ollama list'}")
    except Exception as e:
        print(f"  ⚠️  Ollama inaccessible ({e}). L'IA sera désactivée.")

    print()

    resultats = []
    for seed in args.seeds:
        print(f"{SEP}")
        print(f"  Paire seed={seed}  — {args.jours:.1f} jour(s)")
        print(f"{SEP}")

        # ── SANS IA ──
        print(f"  [1/2] SANS IA … ", end="", flush=True)
        tab_sans = _make_tab(ia_active=False)
        try:
            r_sans = _run(tab_sans, duree, seed, timeout_s=args.timeout)
            print(f"✅  {r_sans['tubes_sortis']} tubes sortis  TAT={r_sans['tat_mean']} min")
        except Exception as e:
            print(f"❌  {e}")
            continue

        # ── AVEC IA ──
        print(f"  [2/2] AVEC IA  … ", end="", flush=True)
        tab_avec = _make_tab(ia_active=True)
        tab_avec.coordinateur.cooldown_ia_min = args.cooldown
        try:
            r_avec = _run(tab_avec, duree, seed, timeout_s=args.timeout)
            print(f"✅  {r_avec['tubes_sortis']} tubes sortis  TAT={r_avec['tat_mean']} min  appels_ia={r_avec['appels_ia']}")
        except Exception as e:
            print(f"❌  {e}")
            continue

        print_paire(seed, r_sans, r_avec)
        resultats.append({"seed": seed, "sans": r_sans, "avec": r_avec})

    if len(resultats) >= 2:
        print_synthese(resultats)
    elif len(resultats) == 1:
        print("\n  (une seule paire — pas de synthèse multi-runs)")

    print()


if __name__ == "__main__":
    main()
