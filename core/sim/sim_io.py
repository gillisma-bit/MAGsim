"""Utilitaires d'entrée/sortie pour les résultats de simulation.

Extrait de ui/tab_live.py pour éviter les imports circulaires entre
les mixins et le fichier principal.
"""
import json
import os

_LAST_SIM_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "data", "last_sim.json"
)


def _deep_to_list(obj):
    """Convertit récursivement deques et sets en listes pour la sérialisation JSON."""
    from collections import deque
    if isinstance(obj, dict):
        return {k: _deep_to_list(v) for k, v in obj.items()}
    if isinstance(obj, (deque, list, tuple, set)):
        return [_deep_to_list(v) for v in obj]
    return obj


def sauver_stats_sim(stats_history, transit_times_raw):
    """Écrit data/last_sim.json — lu automatiquement par gradio_app au prochain chat."""
    try:
        data = _deep_to_list(dict(stats_history))
        data["transit_times_raw"] = list(transit_times_raw)
        with open(_LAST_SIM_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        jours = data["time"][-1] / 1440.0 if data.get("time") else 0
        print(f"[INFO] Stats simulation sauvées → last_sim.json ({jours:.1f} j simulés)")
    except Exception as exc:
        print(f"[WARN] Impossible de sauvegarder last_sim.json : {exc}")
