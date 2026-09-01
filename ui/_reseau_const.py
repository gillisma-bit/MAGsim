"""Constantes et fonctions utilitaires partagées pour TabReseau et ses mixins.

Séparé de tab_reseau.py pour éviter les imports circulaires avec les mixins.
"""
import math

# ─── Couleurs ─────────────────────────────────────────────────────────────────
FOND          = "#0d1117"
FOND_BOITE    = "#161b22"
COULEUR_TEXTE = "#e6edf3"
COULEUR_GRIS  = "#484f58"
COULEUR_SOUS  = "#8b949e"
COULEUR_LABO  = "#0f3460"
BORD_LABO     = "#1a6fa8"

# ─── Dimensions blocs ────────────────────────────────────────────────────────
BOX_W, BOX_H   = 200, 84
LABO_W, LABO_H = 210, 100

# ─── Grille ──────────────────────────────────────────────────────────────────
GRID       = 20       # pixels par case
M_PAR_CASE = 5.0      # metres par case

# ─── Vitesse navette ─────────────────────────────────────────────────────────
VITESSE_M_MIN = 80.0

# ─── Modes ───────────────────────────────────────────────────────────────────
MODE_NORMAL    = "normal"
MODE_CHEMIN    = "edit_chemin"
MODE_ZONE      = "edit_zone"
MODE_EDIT_WP   = "edit_wp"
MODE_EDIT_ZONE = "edit_zone_existing"

# ─── Paramètres snap / offset ────────────────────────────────────────────────
SNAP_MAGNET      = 30   # Rayon d'accrochage magnétique (px)
OFFSET_CHEMIN_PX = 5    # Décalage entre deux chemins partageant un segment

# ─── Palette couleurs zones ───────────────────────────────────────────────────
PALETTE_ZONES = [
    "#c0392b", "#e67e22", "#27ae60", "#2980b9",
    "#8e44ad", "#16a085", "#d35400", "#2c3e50",
]


# ─── Fonctions utilitaires ────────────────────────────────────────────────────

def _snap(v: float) -> int:
    return round(v / GRID) * GRID


def _dist_chemin(waypoints: list) -> float:
    total = 0.0
    for i in range(len(waypoints) - 1):
        dx = waypoints[i + 1][0] - waypoints[i][0]
        dy = waypoints[i + 1][1] - waypoints[i][1]
        total += math.sqrt(dx * dx + dy * dy)
    return total


def _duree_depuis_chemin(waypoints: list) -> float:
    dist_m = _dist_chemin(waypoints) / GRID * M_PAR_CASE
    return max(1.0, dist_m / VITESSE_M_MIN)
