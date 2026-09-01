"""Onglet Réseau — éditeur de topologie avec grille, zones et chemins.

Modes
-----
NORMAL      : déplacer les blocs (snap sur la grille)
EDIT_CHEMIN : tracer un chemin waypoint entre un fournisseur et le labo
EDIT_ZONE   : dessiner une zone colorée (clic-glisser)

Données
-------
- Positions des blocs        : data/fournisseurs/<id>.json  -> position_canvas
- Waypoints des chemins      : data/fournisseurs/<id>.json  -> chemin_waypoints [[px,py],...]
- Zones/ailes                : data/zones.json              -> zones [...]
"""

from __future__ import annotations

import json
import math
import tkinter as tk
from tkinter import colorchooser, simpledialog, ttk
from typing import Optional

# Constantes visuelles
FOND          = "#0d1117"
FOND_BOITE    = "#161b22"
COULEUR_TEXTE = "#e6edf3"
COULEUR_GRIS  = "#484f58"
COULEUR_SOUS  = "#8b949e"
COULEUR_LABO  = "#0f3460"
BORD_LABO     = "#1a6fa8"

BOX_W, BOX_H   = 200, 84
LABO_W, LABO_H = 210, 100

# Grille
GRID       = 20       # pixels par case
M_PAR_CASE = 5.0      # metres par case

# Vitesse navette par defaut (m/min)
VITESSE_M_MIN = 80.0

# Modes
MODE_NORMAL = "normal"
MODE_CHEMIN = "edit_chemin"
MODE_ZONE      = "edit_zone"
MODE_EDIT_WP   = "edit_wp"
MODE_EDIT_ZONE = "edit_zone_existing"

# Rayon d'accrochage magnetique sur les points cardinaux (px)
SNAP_MAGNET = 30
# Decalage perpendiculaire (px) entre deux chemins qui partagent un segment
OFFSET_CHEMIN_PX = 5

# Palette couleurs zones
PALETTE_ZONES = ["#c0392b", "#e67e22", "#27ae60", "#2980b9",
                 "#8e44ad", "#16a085", "#d35400", "#2c3e50"]


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
from ui._tabreseaudessiner import _TabReseauDessiner
from ui._tabreseauedit import _TabReseauEdit
from ui._tabreseaupanel import _TabReseauPanel


class TabReseau(_TabReseauDessiner, _TabReseauEdit, _TabReseauPanel):
    """Onglet réseau/topologie. Dessin/édition/panel dans des mixins.
    """

    def __init__(self, parent, config_manager, app):
        self.parent         = parent
        self.config_manager = config_manager
        self.app            = app
        self.tab_live_ref: Optional[object] = None

        self._mode           = MODE_NORMAL
        self._selected_fid: Optional[str] = None
        self._drag_data: dict = {}
        self._edit_wp: list          = []
        self._edit_fid: Optional[str] = None
        self._edit_preview_ids: list  = []
        self._zone_drag: Optional[dict] = None
        self._wp_edit_fid: Optional[str] = None
        self._wp_edit_wps: list          = []
        self._wp_drag_idx: Optional[int] = None
        # Edition de zone existante
        self._ez_zid: Optional[str]   = None   # id zone en cours d'edition
        self._ez_drag: Optional[dict] = None   # {mode:'move'|'corner', corner:int, ox,oy,ox1,oy1,ox2,oy2}
        self._ez_preview_ids: list    = []
        self._boites:   dict = {}
        self._conns:    dict = {}
        self._labo_ids: dict = {}

        self._build_ui()
        self._dessiner()
        self._planifier_refresh()

    def _build_ui(self):
        self.frame_main = ttk.Frame(self.parent)
        self.frame_main.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(
            self.frame_main, bg=FOND,
            highlightthickness=0, cursor="crosshair",
        )
        self.canvas.pack(side="left", fill="both", expand=True)

        self.frame_panel = ttk.Frame(self.frame_main, width=300)
        self.frame_panel.pack_propagate(False)

        self.canvas.bind("<Button-1>",        self._on_clic)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_clic)
        self.canvas.bind("<Motion>",          self._on_motion)
        self.canvas.bind("<Button-3>",        self._on_clic_droit)
        self.canvas.bind("<Escape>",          lambda e: self._changer_mode(MODE_NORMAL))

    def _drag_start(self, event, fid: str):
        if self._mode != MODE_NORMAL:
            return
        self._drag_data[fid] = {"x": event.x, "y": event.y}
        self._selected_fid   = fid
        self.canvas.tag_raise(f"f_{fid}")
        self._afficher_panel(fid)

    def _drag_move(self, event, fid: str):
        if self._mode != MODE_NORMAL or fid not in self._drag_data:
            return
        dx = event.x - self._drag_data[fid]["x"]
        dy = event.y - self._drag_data[fid]["y"]
        self._drag_data[fid] = {"x": event.x, "y": event.y}
        self.canvas.move(f"f_{fid}", dx, dy)

    def _drag_end(self, event, fid: str):
        if self._mode != MODE_NORMAL:
            return
        self._drag_data.pop(fid, None)
        fournisseurs = self.config_manager.get_fournisseurs()
        if fid not in fournisseurs:
            return
        fconf = fournisseurs[fid]
        ids   = self._boites.get(fid, {})
        rid   = ids.get("rect")
        if rid:
            coords  = self.canvas.coords(rid)
            new_x   = _snap(coords[0])
            new_y   = _snap(coords[1])
            self.canvas.move(f"f_{fid}", new_x - coords[0], new_y - coords[1])
            fconf["position_canvas"] = {"x": new_x, "y": new_y}
            wps = fconf.get("chemin_waypoints", [])
            if wps:
                wps[0] = [new_x + BOX_W, new_y + BOX_H // 2]
                fconf["chemin_waypoints"] = wps
            self.config_manager.sauvegarder_fournisseur(fconf)
        self._dessiner()

    def _on_clic(self, event):
        x, y = event.x, event.y
        items = self.canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2)
        for iid in items:
            tags = self.canvas.gettags(iid)
            for t in tags:
                if t.startswith("btn_"):
                    return
        if self._mode == MODE_CHEMIN:
            self._chemin_ajouter_waypoint(x, y)
        elif self._mode == MODE_ZONE:
            self._zone_debut(x, y)
        elif self._mode == MODE_EDIT_WP:
            idx = self._wp_handle_sous_curseur(x, y)
            if idx is not None:
                self._wp_drag_idx = idx
        elif self._mode == MODE_EDIT_ZONE:
            pass  # gere par _ez_clic via tag_bind
        else:
            fid = self._fid_sous_curseur(x, y)
            if fid:
                self._selected_fid = fid
                self._afficher_panel(fid)
            else:
                self._masquer_panel()

    def _on_double_clic(self, event):
        x, y = event.x, event.y
        if self._mode == MODE_CHEMIN:
            self._chemin_valider()
            return
        if self._mode == MODE_EDIT_WP:
            self._wp_valider()
            return
        items = self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3)
        for iid in items:
            if "labo" in self.canvas.gettags(iid):
                self._basculer_vers_simulation()
                return

    def _on_motion(self, event):
        if self._mode == MODE_CHEMIN and self._edit_wp:
            self._chemin_preview(event.x, event.y)
        elif self._mode == MODE_ZONE and self._zone_drag:
            self._zone_update_preview(event.x, event.y)
        elif self._mode == MODE_EDIT_ZONE:
            # Changer le curseur selon ce qui est sous la souris
            if self._ez_zid:
                zones = self.config_manager.get_zones()
                z = next((z for z in zones if z["id"] == self._ez_zid), None)
                if z:
                    for cx, cy in [
                        (z["x1"],z["y1"]),(z["x2"],z["y1"]),
                        (z["x2"],z["y2"]),(z["x1"],z["y2"])
                    ]:
                        if abs(event.x-cx) <= 12 and abs(event.y-cy) <= 12:
                            self.canvas.config(cursor="sizing")
                            return
                    self.canvas.config(cursor="fleur")
                    return
            self.canvas.config(cursor="crosshair")

    def _on_drag(self, event):
        """Glisser bouton-1 enfonce."""
        if self._mode == MODE_EDIT_WP and self._wp_drag_idx is not None:
            self.canvas.config(cursor="fleur")
            self._wp_edit_wps[self._wp_drag_idx] = [_snap(event.x), _snap(event.y)]
            self._wp_redessiner()
        elif self._mode == MODE_EDIT_ZONE and self._ez_drag:
            self._ez_appliquer_drag(event.x, event.y)
        elif self._mode == MODE_ZONE and self._zone_drag:
            self._zone_update_preview(event.x, event.y)

    def _on_release(self, event):
        """Relachement bouton-1."""
        if self._mode == MODE_EDIT_WP and self._wp_drag_idx is not None:
            self._wp_edit_wps[self._wp_drag_idx] = [_snap(event.x), _snap(event.y)]
            self._wp_drag_idx = None
            self.canvas.config(cursor="crosshair")
            self._wp_redessiner()
        elif self._mode == MODE_EDIT_ZONE and self._ez_drag:
            self._ez_valider_drag(event.x, event.y)
        elif self._mode == MODE_ZONE and self._zone_drag:
            self._zone_fin(event)

    def _on_clic_droit(self, event):
        if self._mode == MODE_CHEMIN:
            if self._edit_wp:
                self._edit_wp.pop()
                self._chemin_refresh_preview()
        elif self._mode == MODE_EDIT_WP:
            idx = self._wp_handle_sous_curseur(event.x, event.y)
            if idx is not None and len(self._wp_edit_wps) > 2:
                self._wp_edit_wps.pop(idx)
                self._wp_redessiner()
        elif self._mode == MODE_EDIT_ZONE and self._ez_zid:
            self._ez_supprimer(self._ez_zid)
        elif self._mode == MODE_ZONE and self._zone_drag:
            self.canvas.delete(self._zone_drag.get("rect_id"))
            self._zone_drag = None

