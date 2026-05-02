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


class TabReseau:
    """Onglet topologie reseau avec editeur de plan."""

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

    # Build UI

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

    # Dessin complet

    def _dessiner(self):
        self.canvas.delete("all")
        self._boites.clear()
        self._conns.clear()
        self._labo_ids.clear()

        fournisseurs = self.config_manager.get_fournisseurs()
        navette      = self.config_manager.get_navette_principale()
        labo_pos     = navette.get("position_labo_canvas", {"x": 590, "y": 272})
        central_pos  = {"x": labo_pos["x"], "y": labo_pos["y"] + LABO_H + 70}

        self._dessiner_grille()
        self._dessiner_zones()

        seg_offsets = self._calculer_offsets_chemins(fournisseurs)
        for fid, fconf in fournisseurs.items():
            self._dessiner_chemin(fid, fconf, labo_pos, seg_offsets.get(fid, {}))

        self._dessiner_echelle()
        self._dessiner_labo(labo_pos)
        self._dessiner_labo_central(central_pos)

        for fid, fconf in fournisseurs.items():
            pos = fconf.get("position_canvas", {"x": 50, "y": 300})
            self._dessiner_fournisseur(fid, fconf, pos)

        self._dessiner_entete()

    # Grille

    def _dessiner_grille(self):
        w = max(1400, self.canvas.winfo_width()  or 1400)
        h = max(900,  self.canvas.winfo_height() or 900)
        for gx in range(0, w, GRID):
            col = "#1e2530" if gx % (GRID * 5) == 0 else "#161b22"
            self.canvas.create_line(gx, 0, gx, h, fill=col, width=1, tags="grille")
        for gy in range(0, h, GRID):
            col = "#1e2530" if gy % (GRID * 5) == 0 else "#161b22"
            self.canvas.create_line(0, gy, w, gy, fill=col, width=1, tags="grille")

    # Regle echelle

    def _dessiner_echelle(self):
        ex, ey = 20, 850
        n_cases    = 5
        total_px   = n_cases * GRID
        self.canvas.create_rectangle(
            ex, ey - 4, ex + total_px, ey + 4,
            fill="#30363d", outline="#484f58", tags="echelle",
        )
        for i in range(n_cases + 1):
            xg = ex + i * GRID
            self.canvas.create_line(xg, ey - 7, xg, ey + 7, fill="#8b949e", tags="echelle")
        self.canvas.create_text(ex, ey - 14, anchor="w", text="0",
            fill="#8b949e", font=("Segoe UI", 7), tags="echelle")
        self.canvas.create_text(ex + total_px, ey - 14, anchor="e",
            text=f"{n_cases * int(M_PAR_CASE)} m",
            fill="#8b949e", font=("Segoe UI", 7), tags="echelle")
        self.canvas.create_text(ex + total_px // 2, ey + 14, anchor="center",
            text=f"1 case = {int(M_PAR_CASE)} m",
            fill="#484f58", font=("Segoe UI", 7, "italic"), tags="echelle")

    # Zones

    def _dessiner_zones(self):
        zones   = self.config_manager.get_zones()
        editing = (self._mode == MODE_EDIT_ZONE)
        for z in zones:
            x1, y1 = z.get("x1", 0), z.get("y1", 0)
            x2, y2 = z.get("x2", 100), z.get("y2", 100)
            col    = z.get("couleur", "#2c3e50")
            nom    = z.get("nom", "Zone")
            zid    = z.get("id", "")
            selected = editing and (zid == self._ez_zid)
            bord_w   = 3 if selected else 2
            self.canvas.create_rectangle(
                x1, y1, x2, y2,
                fill=col, outline=col,
                stipple="gray12",
                tags=("zone", f"zone_{zid}"),
            )
            self.canvas.create_rectangle(
                x1, y1, x2, y2,
                fill="", outline=col, width=bord_w,
                tags=("zone", f"zone_{zid}"),
            )
            self.canvas.create_text(
                x1 + 8, y1 + 8, anchor="nw",
                text=nom.upper(),
                fill=col, font=("Segoe UI", 7, "bold"),
                tags=("zone", f"zone_{zid}"),
            )
            # Poignees d'angle si zone selectionnee
            if selected:
                for hx, hy, corner in [
                    (x1, y1, 0), (x2, y1, 1), (x2, y2, 2), (x1, y2, 3),
                ]:
                    r = 7
                    self.canvas.create_rectangle(
                        hx - r, hy - r, hx + r, hy + r,
                        fill="#010409", outline=col, width=2,
                        tags=("zone", f"zone_{zid}", f"ez_corner_{corner}"),
                    )
            # Bind pour selectionner la zone en MODE_EDIT_ZONE
            for iid in self.canvas.find_withtag(f"zone_{zid}"):
                self.canvas.tag_bind(
                    iid, "<Button-1>",
                    lambda e, z2=zid: self._ez_clic(e, z2),
                )

    # Chemins waypoints

    @staticmethod
    def _segment_key(a: list, b: list) -> tuple:
        """Cle normalisee d'un segment A->B, independante de la direction."""
        pa = (int(round(a[0])), int(round(a[1])))
        pb = (int(round(b[0])), int(round(b[1])))
        return (min(pa, pb), max(pa, pb))

    def _calculer_offsets_chemins(self, fournisseurs: dict) -> dict:
        """Detecte les segments partages entre plusieurs chemins et calcule
        un decalage perpendiculaire pour chacun.
        Retourne : {fid: {seg_idx: (ox, oy)}}"""
        # Inventaire : cle_segment -> [(fid, idx_segment), ...]
        seg_map: dict = {}
        for fid, fconf in fournisseurs.items():
            wps = fconf.get("chemin_waypoints", [])
            for i in range(len(wps) - 1):
                key = self._segment_key(wps[i], wps[i + 1])
                seg_map.setdefault(key, []).append((fid, i))

        offsets: dict = {}  # {fid: {seg_idx: (ox, oy)}}
        for key, paths in seg_map.items():
            if len(paths) <= 1:
                continue
            (x1, y1), (x2, y2) = key
            dx, dy = x2 - x1, y2 - y1
            length = math.sqrt(dx * dx + dy * dy) or 1
            px, py = -dy / length, dx / length  # vecteur perpendiculaire
            n = len(paths)
            for rank, (fid, seg_idx) in enumerate(paths):
                shift = (rank - (n - 1) / 2) * OFFSET_CHEMIN_PX
                offsets.setdefault(fid, {})[seg_idx] = (px * shift, py * shift)

        return offsets

    def _dessiner_chemin(self, fid: str, fconf: dict, labo_pos: dict,
                         seg_offsets: Optional[dict] = None):
        editing   = (self._mode == MODE_EDIT_WP and fid == self._wp_edit_fid)
        waypoints = self._wp_edit_wps if editing else fconf.get("chemin_waypoints", [])
        if len(waypoints) < 2:
            return

        couleur = fconf.get("couleur", "#484f58")
        actif   = fconf.get("actif", True)
        if not actif:
            couleur = "#2d333b"
        if seg_offsets is None:
            seg_offsets = {}

        # Dessiner chaque segment individuellement pour appliquer le decalage
        for i in range(len(waypoints) - 1):
            ox, oy  = seg_offsets.get(i, (0, 0))
            x1 = waypoints[i][0]     + ox
            y1 = waypoints[i][1]     + oy
            x2 = waypoints[i + 1][0] + ox
            y2 = waypoints[i + 1][1] + oy
            is_last = (i == len(waypoints) - 2)
            kw = dict(
                fill=couleur, width=3, capstyle=tk.ROUND,
                tags=(f"chemin_{fid}", "chemin"),
            )
            if is_last:
                kw["arrow"]      = tk.LAST
                kw["arrowshape"] = (12, 16, 5)
            self.canvas.create_line(x1, y1, x2, y2, **kw)

        # Waypoints (points) : positions originales sans decalage
        for i, wp in enumerate(waypoints):
            is_endpoint = (i == 0 or i == len(waypoints) - 1)
            r    = 8 if (editing and not is_endpoint) else 4
            fill = "#010409" if is_endpoint else couleur
            iid  = self.canvas.create_oval(
                wp[0] - r, wp[1] - r, wp[0] + r, wp[1] + r,
                fill=fill, outline=couleur, width=2,
                tags=(f"chemin_{fid}", "chemin", "waypoint"),
            )
            if editing and not is_endpoint:
                self.canvas.tag_bind(iid, "<Enter>",
                    lambda e: self.canvas.config(cursor="fleur"))
                self.canvas.tag_bind(iid, "<Leave>",
                    lambda e: self.canvas.config(cursor="crosshair"))

        n      = len(waypoints)
        mid    = waypoints[n // 2]
        duree  = _duree_depuis_chemin(waypoints)
        dist_m = _dist_chemin(waypoints) / GRID * M_PAR_CASE
        self.canvas.create_rectangle(
            mid[0] - 28, mid[1] - 12,
            mid[0] + 28, mid[1] + 12,
            fill="#010409", outline="#21262d", tags=(f"chemin_{fid}",),
        )
        self.canvas.create_text(
            mid[0], mid[1],
            text=f"{dist_m:.0f} m  {duree:.0f} min",
            fill=couleur, font=("Segoe UI", 7, "bold"),
            tags=(f"chemin_{fid}", "chemin_label"),
        )

    # En-tete toolbar

    def _dessiner_entete(self):
        w = max(1400, self.canvas.winfo_width() or 1400)
        self.canvas.create_rectangle(
            0, 0, w, 62, fill="#010409", outline="", tags="entete",
        )
        self.canvas.create_line(
            0, 62, w, 62, fill="#21262d", width=1, tags="entete",
        )
        self.canvas.create_text(
            18, 16, anchor="nw",
            text="Editeur de Topologie",
            fill=COULEUR_TEXTE, font=("Segoe UI", 13, "bold"), tags="entete",
        )
        self.canvas.create_text(
            18, 38, anchor="nw",
            text="Grille 1 case = 5 m  |  Clic droit = annuler  |  Double-clic = confirmer",
            fill=COULEUR_SOUS, font=("Segoe UI", 8), tags="entete",
        )

        modes = [
            (MODE_NORMAL,     "Normal",           "#21262d", "#30363d"),
            (MODE_CHEMIN,     "Editer chemin",    "#0d2c4a", "#1a6fa8"),
            (MODE_EDIT_WP,    "Modif. waypoints", "#1a1200", "#b8860b"),
            (MODE_ZONE,       "+ Zone",           "#1a2e0a", "#2ea04f"),
            (MODE_EDIT_ZONE,  "Editer zone",      "#1a2a0a", "#3ea04f"),
        ]
        btn_w, btn_h = 140, 30
        btn_y = 16
        btn_x_start = w - len(modes) * (btn_w + 8) - 14
        self._btn_rects = {}
        for i, (mode, label, fill_idle, fill_act) in enumerate(modes):
            bx   = btn_x_start + i * (btn_w + 8)
            fill = fill_act if self._mode == mode else fill_idle
            r = self.canvas.create_rectangle(
                bx, btn_y, bx + btn_w, btn_y + btn_h,
                fill=fill, outline=fill_act, width=1,
                tags=("entete", f"btn_{mode}"),
            )
            t = self.canvas.create_text(
                bx + btn_w // 2, btn_y + btn_h // 2,
                text=label,
                fill=COULEUR_TEXTE if self._mode == mode else COULEUR_SOUS,
                font=("Segoe UI", 8, "bold"),
                tags=("entete", f"btn_{mode}"),
            )
            for iid in (r, t):
                self.canvas.tag_bind(
                    iid, "<Button-1>",
                    lambda e, m=mode: self._changer_mode(m),
                )

    # Boite labo analyse specialisee

    def _dessiner_labo(self, labo_pos: dict):
        x, y = labo_pos["x"], labo_pos["y"]
        for i, alpha in [(8, "#071f33"), (4, "#0d3558"), (1, "#1a6fa8")]:
            self.canvas.create_rectangle(
                x - i, y - i, x + LABO_W + i, y + LABO_H + i,
                fill="", outline=alpha, width=1, tags="labo",
            )
        self.canvas.create_rectangle(
            x, y, x + LABO_W, y + LABO_H,
            fill=COULEUR_LABO, outline=BORD_LABO, width=2, tags="labo",
        )
        self.canvas.create_rectangle(x, y, x + LABO_W, y + 5,
            fill=BORD_LABO, outline="", tags="labo")
        self.canvas.create_rectangle(x, y, x + 5, y + LABO_H,
            fill=BORD_LABO, outline="", tags="labo")
        self.canvas.create_text(
            x + LABO_W // 2 + 2, y + 28,
            text="Analyse Specialisee",
            fill=COULEUR_TEXTE, font=("Segoe UI", 11, "bold"), tags="labo",
        )
        met_id = self.canvas.create_text(
            x + LABO_W // 2 + 2, y + 54,
            text="—",
            fill="#2ea04f", font=("Segoe UI", 8, "bold"),
            tags=("labo", "labo_metrics"),
        )
        self.canvas.create_text(
            x + LABO_W // 2 + 2, y + 76,
            text="Double-clic pour simulation",
            fill=COULEUR_SOUS, font=("Segoe UI", 7, "italic"), tags="labo",
        )
        self._labo_ids = {"metrics": met_id}
        for iid in self.canvas.find_withtag("labo"):
            self.canvas.tag_bind(iid, "<Enter>",
                lambda e: self.canvas.config(cursor="hand2"))
            self.canvas.tag_bind(iid, "<Leave>",
                lambda e: self.canvas.config(cursor="crosshair"))
            self.canvas.tag_bind(iid, "<Double-Button-1>",
                self._basculer_vers_simulation)

    # Boite Labo Central

    def _dessiner_labo_central(self, hub_pos: dict):
        x, y = hub_pos["x"], hub_pos["y"]
        COULEUR_HUB = "#0d2137"
        BORD_HUB    = "#1a5276"
        for i, alpha in [(6, "#081524"), (2, "#1a5276")]:
            self.canvas.create_rectangle(
                x - i, y - i, x + LABO_W + i, y + LABO_H + i,
                fill="", outline=alpha, width=1, tags="hub",
            )
        self.canvas.create_rectangle(
            x, y, x + LABO_W, y + LABO_H,
            fill=COULEUR_HUB, outline=BORD_HUB, width=2, tags="hub",
        )
        self.canvas.create_rectangle(x, y, x + LABO_W, y + 5,
            fill=BORD_HUB, outline="", tags="hub")
        self.canvas.create_rectangle(x, y, x + 5, y + LABO_H,
            fill=BORD_HUB, outline="", tags="hub")
        self.canvas.create_text(
            x + LABO_W // 2 + 2, y + 28,
            text="Laboratoire Central",
            fill="#8b949e", font=("Segoe UI", 11, "bold"), tags="hub",
        )
        self.canvas.create_text(
            x + LABO_W // 2 + 2, y + 54,
            text="Reception  Tri  Distribution",
            fill="#484f58", font=("Segoe UI", 8), tags="hub",
        )
        self.canvas.create_text(
            x + LABO_W // 2 + 2, y + 76,
            text="Branche parallele",
            fill="#484f58", font=("Segoe UI", 7), tags="hub",
        )

    # Boite Fournisseur

    def _dessiner_fournisseur(self, fid: str, fconf: dict, pos: dict):
        x, y    = _snap(pos["x"]), _snap(pos["y"])
        couleur = fconf.get("couleur", COULEUR_GRIS)
        nom     = fconf.get("nom", fid)
        icone   = fconf.get("icone", "")
        actif   = fconf.get("actif", True)
        c       = couleur if actif else COULEUR_GRIS
        tag     = f"f_{fid}"

        rect_id = self.canvas.create_rectangle(
            x, y, x + BOX_W, y + BOX_H,
            fill=FOND_BOITE, outline=c, width=2 if actif else 1,
            tags=(tag, "boite"),
        )
        bande_top = self.canvas.create_rectangle(
            x, y, x + BOX_W, y + 4,
            fill=c, outline="", tags=(tag, "bande_top"),
        )
        bande_id = self.canvas.create_rectangle(
            x, y, x + 5, y + BOX_H,
            fill=c, outline="", tags=(tag, "bande"),
        )
        nom_c    = nom if len(nom) <= 22 else nom[:20] + "..."
        title_id = self.canvas.create_text(
            x + BOX_W // 2 + 3, y + 22,
            text=f"{icone}  {nom_c}" if icone else nom_c,
            fill=COULEUR_TEXTE if actif else COULEUR_GRIS,
            font=("Segoe UI", 9, "bold"), tags=(tag, "titre"),
        )
        freq = float(fconf.get("frequence_base", 30))
        purg = int(fconf.get("pct_urgent", 0) * 100)

        wps = fconf.get("chemin_waypoints", [])
        if len(wps) >= 2:
            duree    = _duree_depuis_chemin(wps)
            dist_m   = _dist_chemin(wps) / GRID * M_PAR_CASE
            trajet   = f"{dist_m:.0f} m  {duree:.0f} min"
        else:
            trajet = f"{fconf.get('duree_trajet_min', '?')} min"

        m1_id = self.canvas.create_text(
            x + BOX_W // 2 + 3, y + 44,
            text=f"{60/freq:.1f} t/h  {purg}% urg.  {trajet}",
            fill=COULEUR_SOUS if actif else COULEUR_GRIS,
            font=("Segoe UI", 7), tags=(tag, "m1"),
        )
        m2_id = self.canvas.create_text(
            x + BOX_W // 2 + 3, y + 64,
            text="En transit : —",
            fill=c, font=("Segoe UI", 8, "bold"),
            tags=(tag, f"live_{fid}", "live_metric"),
        )
        self.canvas.create_oval(
            x + BOX_W - 14, y + 10, x + BOX_W - 6, y + 18,
            fill="#2ea04f" if actif else COULEUR_GRIS,
            outline="", tags=(tag, "status"),
        )

        self._boites[fid] = {
            "rect": rect_id, "bande": bande_id, "title": title_id,
            "m1": m1_id, "m2": m2_id,
        }

        for iid in [rect_id, bande_id, bande_top, title_id, m1_id, m2_id]:
            self.canvas.tag_bind(iid, "<ButtonPress-1>",
                lambda e, f=fid: self._drag_start(e, f))
            self.canvas.tag_bind(iid, "<B1-Motion>",
                lambda e, f=fid: self._drag_move(e, f))
            self.canvas.tag_bind(iid, "<ButtonRelease-1>",
                lambda e, f=fid: self._drag_end(e, f))
            self.canvas.tag_bind(iid, "<Enter>",
                lambda e: self.canvas.config(
                    cursor="fleur" if self._mode == MODE_NORMAL else "crosshair"))
            self.canvas.tag_bind(iid, "<Leave>",
                lambda e: self.canvas.config(cursor="crosshair"))

    # Drag Drop (mode NORMAL)

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

    # Clics canvas

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

    # Mode CHEMIN

    # helpers : points cardinaux d'un bloc fournisseur
    @staticmethod
    def _cardinaux_fournisseur(pos: dict) -> list:
        """Retourne les 4 points cardinaux [N,S,E,O] du bloc fournisseur."""
        x, y = _snap(pos["x"]), _snap(pos["y"])
        return [
            [x + BOX_W // 2, y],            # N
            [x + BOX_W // 2, y + BOX_H],    # S
            [x + BOX_W,      y + BOX_H // 2],  # E
            [x,              y + BOX_H // 2],  # O
        ]

    def _snapper_cardinal(self, x: int, y: int) -> Optional[list]:
        """Retourne [x,y] snappé sur le point cardinal le plus proche
        parmi tous les fournisseurs, dans le rayon SNAP_MAGNET.
        Retourne None si aucun cardinal dans le rayon."""
        fournisseurs = self.config_manager.get_fournisseurs()
        best, best_d = None, float(SNAP_MAGNET)
        for fid, fconf in fournisseurs.items():
            pos = fconf.get("position_canvas", {"x": 50, "y": 300})
            for pt in self._cardinaux_fournisseur(pos):
                d = math.sqrt((pt[0] - x) ** 2 + (pt[1] - y) ** 2)
                if d < best_d:
                    best_d, best = d, pt
        return best

    def _snapper_waypoint_existant(self, x: int, y: int) -> Optional[list]:
        """Retourne le waypoint existant d'un autre chemin le plus proche
        dans le rayon SNAP_MAGNET. Permet de faire converger des chemins."""
        fournisseurs = self.config_manager.get_fournisseurs()
        best, best_d = None, float(SNAP_MAGNET)
        for fid, fconf in fournisseurs.items():
            if fid == self._edit_fid:
                continue
            for wp in fconf.get("chemin_waypoints", []):
                d = math.sqrt((wp[0] - x) ** 2 + (wp[1] - y) ** 2)
                if d < best_d:
                    best_d, best = d, list(wp)
        return best

    def _dessiner_cardinaux(self, fid: str):
        """Dessine les 4 points cardinaux du bloc fournisseur (pendant tracé)."""
        fournisseurs = self.config_manager.get_fournisseurs()
        fconf = fournisseurs.get(fid, {})
        pos   = fconf.get("position_canvas", {"x": 50, "y": 300})
        col   = fconf.get("couleur", "#ffffff")
        labels = ["N", "S", "E", "O"]
        for pt, lbl in zip(self._cardinaux_fournisseur(pos), labels):
            r = 7
            iid = self.canvas.create_oval(
                pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r,
                fill="#010409", outline=col, width=2,
                tags=("cardinal", f"f_{fid}"),
            )
            self.canvas.create_text(
                pt[0], pt[1], text=lbl,
                fill=col, font=("Segoe UI", 6, "bold"),
                tags=("cardinal", f"f_{fid}"),
            )

    def _changer_mode(self, mode: str):
        # Auto-sauvegarder les waypoints quand on quitte MODE_EDIT_WP
        if mode != MODE_EDIT_WP and self._wp_edit_fid and len(self._wp_edit_wps) >= 2:
            fournisseurs = self.config_manager.get_fournisseurs()
            fconf = fournisseurs.get(self._wp_edit_fid, {})
            fconf["chemin_waypoints"] = [list(wp) for wp in self._wp_edit_wps]
            fconf["duree_trajet_min"] = round(_duree_depuis_chemin(self._wp_edit_wps), 1)
            self.config_manager.sauvegarder_fournisseur(fconf)
        if mode != MODE_EDIT_WP:
            self._wp_edit_fid = None
            self._wp_edit_wps = []
            self._wp_drag_idx = None
        if mode != MODE_EDIT_ZONE:
            self._ez_zid  = None
            self._ez_drag = None
        if mode == MODE_CHEMIN:
            if not self._selected_fid:
                self._flash_message("Selectionnez d'abord un fournisseur (clic simple)")
                return
            self._edit_fid = self._selected_fid
            self._edit_wp  = []
            fournisseurs = self.config_manager.get_fournisseurs()
            fconf = fournisseurs.get(self._edit_fid, {})
            pos   = fconf.get("position_canvas", {"x": 50, "y": 300})
            sx    = _snap(pos["x"]) + BOX_W
            sy    = _snap(pos["y"]) + BOX_H // 2
            self._edit_wp = [[sx, sy]]
            self._flash_message(
                f"Chemin pour {fconf.get('nom', self._edit_fid)}"
                " — clic = waypoint (snap cardinal N/S/E/O) — double-clic = valider"
            )
        elif mode == MODE_EDIT_ZONE:
            self._ez_zid  = None
            self._ez_drag = None
            self._flash_message(
                "Cliquez sur une zone pour la selectionner"
                " — glisser = deplacer — poignee d'angle = redimensionner"
                " — clic droit = supprimer — Echap = quitter"
            )
        elif mode == MODE_EDIT_WP:
            if not self._selected_fid:
                self._flash_message("Selectionnez d'abord un fournisseur (clic simple)")
                return
            fournisseurs = self.config_manager.get_fournisseurs()
            fconf = fournisseurs.get(self._selected_fid, {})
            wps   = fconf.get("chemin_waypoints", [])
            if len(wps) < 2:
                self._flash_message("Ce fournisseur n'a pas encore de chemin trace.")
                return
            self._wp_edit_fid = self._selected_fid
            self._wp_edit_wps = [list(wp) for wp in wps]
            self._wp_drag_idx = None
            self._flash_message(
                "Glissez un waypoint pour le deplacer"
                " — double-clic = sauvegarder — clic-droit = supprimer"
            )
        elif mode == MODE_NORMAL:
            self._edit_wp  = []
            self._edit_fid = None
            for iid in self._edit_preview_ids:
                self.canvas.delete(iid)
            self._edit_preview_ids = []
        self._mode = mode
        self._dessiner()

    def _chemin_ajouter_waypoint(self, x: int, y: int):
        """Ajoute un waypoint avec snap : cardinal (1er clic) > waypoint existant > grille."""
        pt = None
        if len(self._edit_wp) == 1:
            # Premier clic interactif : snap cardinal prioritaire
            pt = self._snapper_cardinal(x, y)
        if pt is None:
            # Pour tous les clics : snap sur waypoint existant d'un autre chemin
            pt = self._snapper_waypoint_existant(x, y)
        if pt is None:
            # Fallback : snap grille
            pt = [_snap(x), _snap(y)]
        self._edit_wp.append(pt)
        self._chemin_refresh_preview()

    def _chemin_preview(self, mx: int, my: int):
        for iid in self._edit_preview_ids:
            self.canvas.delete(iid)
        self._edit_preview_ids = []
        if not self._edit_wp:
            return
        last = self._edit_wp[-1]
        # Detecter le point de snap potentiel
        snap_pt = None
        if len(self._edit_wp) == 1:
            snap_pt = self._snapper_cardinal(mx, my)
        if snap_pt is None:
            snap_pt = self._snapper_waypoint_existant(mx, my)
        tx, ty = (snap_pt[0], snap_pt[1]) if snap_pt else (_snap(mx), _snap(my))
        iid = self.canvas.create_line(
            last[0], last[1], tx, ty,
            fill="#30363d", width=2, dash=(6, 4), tags="preview",
        )
        self._edit_preview_ids.append(iid)
        # Indicateur visuel si snap actif
        if snap_pt:
            r = 9
            iid2 = self.canvas.create_oval(
                tx - r, ty - r, tx + r, ty + r,
                fill="", outline="#f0e68c", width=2, dash=(3, 3), tags="preview",
            )
            self._edit_preview_ids.append(iid2)

    def _chemin_refresh_preview(self):
        for iid in self._edit_preview_ids:
            self.canvas.delete(iid)
        self._edit_preview_ids = []
        if not self._edit_wp:
            return
        fournisseurs = self.config_manager.get_fournisseurs()
        fconf = fournisseurs.get(self._edit_fid, {})
        col   = fconf.get("couleur", "#1a6fa8")
        # Afficher les 4 points cardinaux du fournisseur
        self._dessiner_cardinaux(self._edit_fid)

        for i in range(len(self._edit_wp) - 1):
            wp1, wp2 = self._edit_wp[i], self._edit_wp[i + 1]
            iid = self.canvas.create_line(
                wp1[0], wp1[1], wp2[0], wp2[1],
                fill=col, width=3, capstyle=tk.ROUND, tags="preview",
            )
            self._edit_preview_ids.append(iid)

        for wp in self._edit_wp:
            r   = 5
            iid = self.canvas.create_oval(
                wp[0] - r, wp[1] - r, wp[0] + r, wp[1] + r,
                fill=col, outline=COULEUR_TEXTE, width=1, tags="preview",
            )
            self._edit_preview_ids.append(iid)

        if len(self._edit_wp) >= 2:
            dist_m = _dist_chemin(self._edit_wp) / GRID * M_PAR_CASE
            duree  = _duree_depuis_chemin(self._edit_wp)
            mid    = self._edit_wp[len(self._edit_wp) // 2]
            iid = self.canvas.create_text(
                mid[0], mid[1] - 16,
                text=f"{dist_m:.0f} m  {duree:.0f} min",
                fill=col, font=("Segoe UI", 8, "bold"), tags="preview",
            )
            self._edit_preview_ids.append(iid)

        self.canvas.tag_raise("cardinal")
        self.canvas.tag_raise("preview")
        self.canvas.tag_raise("entete")

    def _chemin_valider(self):
        if not self._edit_fid or len(self._edit_wp) < 2:
            self._flash_message("Tracez au moins 2 points avant de valider.")
            return
        fournisseurs = self.config_manager.get_fournisseurs()
        fconf        = fournisseurs.get(self._edit_fid, {})
        navette      = self.config_manager.get_navette_principale()
        labo_pos     = navette.get("position_labo_canvas", {"x": 590, "y": 272})
        end_x        = _snap(labo_pos["x"])
        end_y        = _snap(labo_pos["y"] + LABO_H // 2)
        self._edit_wp.append([end_x, end_y])
        fconf["chemin_waypoints"] = self._edit_wp
        fconf["duree_trajet_min"] = round(_duree_depuis_chemin(self._edit_wp), 1)
        self.config_manager.sauvegarder_fournisseur(fconf)
        self._edit_wp  = []
        self._edit_fid = None
        self._mode     = MODE_NORMAL
        self._dessiner()

    # Mode EDIT_WP (edition de waypoints existants)

    def _wp_valider(self):
        """Sauvegarde et retour en mode normal (la sauvegarde se fait dans _changer_mode)."""
        if not self._wp_edit_fid or len(self._wp_edit_wps) < 2:
            return
        self._changer_mode(MODE_NORMAL)

    def _wp_redessiner(self):
        """Redessine uniquement le chemin en cours d'edition (sans tout redessiner)."""
        fid = self._wp_edit_fid
        if not fid:
            return
        self.canvas.delete(f"chemin_{fid}")
        fournisseurs = self.config_manager.get_fournisseurs()
        fconf        = fournisseurs.get(fid, {})
        navette      = self.config_manager.get_navette_principale()
        labo_pos     = navette.get("position_labo_canvas", {"x": 590, "y": 272})
        self._dessiner_chemin(fid, fconf, labo_pos)
        self.canvas.tag_raise("entete")
        self.canvas.tag_raise(f"f_{fid}")

    def _wp_handle_sous_curseur(self, x: int, y: int) -> Optional[int]:
        """Retourne l'index du waypoint intermediaire le plus proche du curseur."""
        RAYON = 20
        best_idx, best_d = None, float(RAYON)
        for i, wp in enumerate(self._wp_edit_wps):
            if i == 0 or i == len(self._wp_edit_wps) - 1:
                continue  # endpoints fixes
            d = math.sqrt((wp[0] - x) ** 2 + (wp[1] - y) ** 2)
            if d < best_d:
                best_d, best_idx = d, i
        return best_idx

    # Mode EDIT_ZONE (edition de zones existantes)

    def _ez_clic(self, event, zid: str):
        """Clic sur une zone en mode EDIT_ZONE : selectionner et préparer drag."""
        if self._mode != MODE_EDIT_ZONE:
            return
        x, y = event.x, event.y
        zones = self.config_manager.get_zones()
        z     = next((z for z in zones if z["id"] == zid), None)
        if not z:
            return
        self._ez_zid = zid
        x1, y1, x2, y2 = z["x1"], z["y1"], z["x2"], z["y2"]

        # Verifier si clic sur un coin (poignee)
        corner = None
        for i, (cx, cy) in enumerate([(x1,y1),(x2,y1),(x2,y2),(x1,y2)]):
            if abs(x - cx) <= 12 and abs(y - cy) <= 12:
                corner = i
                break

        if corner is not None:
            self._ez_drag = {
                "mode": "corner", "corner": corner,
                "ox": x, "oy": y,
                "ox1": x1, "oy1": y1, "ox2": x2, "oy2": y2,
            }
        else:
            self._ez_drag = {
                "mode": "move",
                "ox": x, "oy": y,
                "ox1": x1, "oy1": y1, "ox2": x2, "oy2": y2,
            }
        self._dessiner()

    def _ez_appliquer_drag(self, mx: int, my: int):
        """Mise a jour visuelle pendant le drag (live, sans sauvegarder)."""
        if not self._ez_drag or not self._ez_zid:
            return
        ox, oy = self._ez_drag["ox"], self._ez_drag["oy"]
        dx, dy = _snap(mx - ox), _snap(my - oy)
        ox1, oy1 = self._ez_drag["ox1"], self._ez_drag["oy1"]
        ox2, oy2 = self._ez_drag["ox2"], self._ez_drag["oy2"]
        m = self._ez_drag["mode"]

        if m == "move":
            nx1, ny1 = ox1 + dx, oy1 + dy
            nx2, ny2 = ox2 + dx, oy2 + dy
        else:
            c = self._ez_drag["corner"]
            nx1, ny1, nx2, ny2 = ox1, oy1, ox2, oy2
            if c == 0:   nx1, ny1 = ox1 + dx, oy1 + dy
            elif c == 1: nx2, ny1 = ox2 + dx, oy1 + dy
            elif c == 2: nx2, ny2 = ox2 + dx, oy2 + dy
            elif c == 3: nx1, ny2 = ox1 + dx, oy2 + dy

        # Mise a jour visuelle du rectangle de la zone
        self.canvas.delete(f"zone_{self._ez_zid}")
        col = next(
            (z["couleur"] for z in self.config_manager.get_zones() if z["id"] == self._ez_zid),
            "#2c3e50"
        )
        nom = next(
            (z["nom"] for z in self.config_manager.get_zones() if z["id"] == self._ez_zid),
            ""
        )
        x1r, y1r = min(nx1, nx2), min(ny1, ny2)
        x2r, y2r = max(nx1, nx2), max(ny1, ny2)
        self.canvas.create_rectangle(
            x1r, y1r, x2r, y2r,
            fill=col, outline=col, stipple="gray12",
            tags=("zone", f"zone_{self._ez_zid}"),
        )
        self.canvas.create_rectangle(
            x1r, y1r, x2r, y2r,
            fill="", outline=col, width=3,
            tags=("zone", f"zone_{self._ez_zid}"),
        )
        self.canvas.create_text(
            x1r + 8, y1r + 8, anchor="nw", text=nom.upper(),
            fill=col, font=("Segoe UI", 7, "bold"),
            tags=("zone", f"zone_{self._ez_zid}"),
        )
        self.canvas.tag_lower(f"zone_{self._ez_zid}", "chemin")

    def _ez_valider_drag(self, mx: int, my: int):
        """Sauvegarde la nouvelle position/taille de la zone."""
        if not self._ez_drag or not self._ez_zid:
            self._ez_drag = None
            return
        ox, oy = self._ez_drag["ox"], self._ez_drag["oy"]
        dx, dy = _snap(mx - ox), _snap(my - oy)
        ox1, oy1 = self._ez_drag["ox1"], self._ez_drag["oy1"]
        ox2, oy2 = self._ez_drag["ox2"], self._ez_drag["oy2"]
        m = self._ez_drag["mode"]

        if m == "move":
            nx1, ny1 = ox1 + dx, oy1 + dy
            nx2, ny2 = ox2 + dx, oy2 + dy
        else:
            c = self._ez_drag["corner"]
            nx1, ny1, nx2, ny2 = ox1, oy1, ox2, oy2
            if c == 0:   nx1, ny1 = ox1 + dx, oy1 + dy
            elif c == 1: nx2, ny1 = ox2 + dx, oy1 + dy
            elif c == 2: nx2, ny2 = ox2 + dx, oy2 + dy
            elif c == 3: nx1, ny2 = ox1 + dx, oy2 + dy

        x1r, y1r = min(nx1, nx2), min(ny1, ny2)
        x2r, y2r = max(nx1, nx2), max(ny1, ny2)
        zones = self.config_manager.get_zones()
        for z in zones:
            if z["id"] == self._ez_zid:
                z["x1"], z["y1"], z["x2"], z["y2"] = x1r, y1r, x2r, y2r
                break
        self.config_manager.sauvegarder_zones(zones)
        self._ez_drag = None
        self._dessiner()

    def _ez_supprimer(self, zid: str):
        """Supprime la zone apres confirmation."""
        zones = self.config_manager.get_zones()
        nom   = next((z["nom"] for z in zones if z["id"] == zid), zid)
        ok = simpledialog.askstring(
            "Supprimer la zone",
            f"Supprimer {nom} ? Tapez son nom pour confirmer.",
            parent=self.parent,
        )
        if ok and ok.strip() == nom:
            zones = [z for z in zones if z["id"] != zid]
            self.config_manager.sauvegarder_zones(zones)
            self._ez_zid  = None
            self._ez_drag = None
            self._dessiner()

    # Mode ZONE

    def _zone_debut(self, x: int, y: int):
        if self._zone_drag:
            return
        sx, sy = _snap(x), _snap(y)
        rid = self.canvas.create_rectangle(
            sx, sy, sx + GRID, sy + GRID,
            fill="", outline="#2ea04f", width=2,
            dash=(6, 3), tags="zone_preview",
        )
        self._zone_drag = {"x0": sx, "y0": sy, "rect_id": rid}
        # Le relachement est gere par _on_release (binding permanent)

    def _zone_update_preview(self, mx: int, my: int):
        if not self._zone_drag:
            return
        sx, sy = _snap(mx), _snap(my)
        self.canvas.coords(
            self._zone_drag["rect_id"],
            self._zone_drag["x0"], self._zone_drag["y0"], sx, sy,
        )

    def _zone_fin(self, event):
        if not self._zone_drag:
            return
        x0, y0 = self._zone_drag["x0"], self._zone_drag["y0"]
        x1, y1 = _snap(event.x), _snap(event.y)
        if abs(x1 - x0) < GRID * 2 or abs(y1 - y0) < GRID * 2:
            self.canvas.delete(self._zone_drag["rect_id"])
            self._zone_drag = None
            return
        nom = simpledialog.askstring(
            "Nouvelle zone", "Nom de la zone / aile :",
            parent=self.parent,
        )
        if not nom:
            self.canvas.delete(self._zone_drag["rect_id"])
            self._zone_drag = None
            return
        col = colorchooser.askcolor(
            title="Couleur de la zone",
            initialcolor=PALETTE_ZONES[0],
            parent=self.parent,
        )
        couleur = col[1] if col and col[1] else PALETTE_ZONES[0]
        zones = self.config_manager.get_zones()
        zid   = f"z{len(zones) + 1}"
        zones.append({
            "id": zid, "nom": nom, "couleur": couleur,
            "x1": min(x0, x1), "y1": min(y0, y1),
            "x2": max(x0, x1), "y2": max(y0, y1),
        })
        self.config_manager.sauvegarder_zones(zones)
        self._zone_drag = None
        self._mode = MODE_NORMAL
        self._dessiner()

    # Utilitaires

    def _fid_sous_curseur(self, x: int, y: int) -> Optional[str]:
        items = self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3)
        for iid in reversed(items):
            for tag in self.canvas.gettags(iid):
                if tag.startswith("f_"):
                    return tag[2:]
        return None

    def _basculer_vers_simulation(self, event=None):
        try:
            nb = self.app.notebook.index("end")
            for i in range(nb):
                if "SIMULATION" in self.app.notebook.tab(i, "text").upper():
                    self.app.notebook.select(i)
                    return
        except Exception:
            pass

    def _flash_message(self, msg: str):
        w = max(1400, self.canvas.winfo_width() or 1400)
        h = max(900,  self.canvas.winfo_height() or 900)
        iid_bg = self.canvas.create_rectangle(
            0, h - 30, w, h,
            fill="#1c2128", outline="", tags="flash",
        )
        iid_t = self.canvas.create_text(
            w // 2, h - 15,
            text=msg,
            fill="#e6edf3", font=("Segoe UI", 9),
            tags="flash",
        )
        self.parent.after(4000, lambda: (
            self.canvas.delete(iid_bg),
            self.canvas.delete(iid_t),
        ))

    # Panneau lateral

    def _afficher_panel(self, fid: str):
        fournisseurs = self.config_manager.get_fournisseurs()
        fconf        = fournisseurs.get(fid, {})

        for w in self.frame_panel.winfo_children():
            w.destroy()
        if not self.frame_panel.winfo_ismapped():
            self.frame_panel.pack(side="right", fill="y")

        icone = fconf.get("icone", "")
        nom   = fconf.get("nom", fid)
        ttk.Label(
            self.frame_panel,
            text=f"{icone}  {nom}" if icone else nom,
            font=("Segoe UI", 11, "bold"),
        ).pack(pady=(15, 4), padx=12)
        ttk.Separator(self.frame_panel).pack(fill="x", padx=10)

        fr = ttk.Frame(self.frame_panel)
        fr.pack(fill="x", padx=14, pady=8)

        champs = [
            ("Frequence base (min/tube)", "frequence_base"),
            ("Gamma k",                   "gamma_k"),
            ("% Urgents (0.0-1.0)",       "pct_urgent"),
            ("Delai trajet (min)",         "duree_trajet_min"),
        ]
        self._vars_panel = {}
        for label, cle in champs:
            ttk.Label(fr, text=label).pack(anchor="w", pady=(5, 0))
            var = tk.StringVar(value=str(fconf.get(cle, "")))
            self._vars_panel[cle] = (var, fid)
            ttk.Entry(fr, textvariable=var, width=22).pack(fill="x")

        ttk.Separator(self.frame_panel).pack(fill="x", padx=10, pady=6)

        self._var_actif = tk.BooleanVar(value=fconf.get("actif", True))
        ttk.Checkbutton(
            self.frame_panel, text="Fournisseur actif",
            variable=self._var_actif,
        ).pack(padx=14, anchor="w")

        wps = fconf.get("chemin_waypoints", [])
        if len(wps) >= 2:
            dist_m = _dist_chemin(wps) / GRID * M_PAR_CASE
            duree  = _duree_depuis_chemin(wps)
            ttk.Label(
                self.frame_panel,
                text=f"Chemin : {len(wps)} pts  {dist_m:.0f} m  {duree:.0f} min",
                foreground="#2ea04f",
            ).pack(padx=14, pady=(4, 0), anchor="w")
            ttk.Button(
                self.frame_panel,
                text="Modifier waypoints",
                command=lambda: self._changer_mode(MODE_EDIT_WP),
            ).pack(padx=14, pady=(2, 0), fill="x")
            ttk.Button(
                self.frame_panel,
                text="Effacer le chemin",
                command=lambda: self._effacer_chemin(fid),
            ).pack(padx=14, pady=(4, 0), fill="x")
        else:
            ttk.Label(
                self.frame_panel,
                text="Aucun chemin trace",
                foreground="#8b949e",
            ).pack(padx=14, pady=(4, 0), anchor="w")

        ttk.Button(
            self.frame_panel,
            text="Tracer le chemin",
            command=lambda: self._changer_mode(MODE_CHEMIN),
        ).pack(padx=14, pady=(4, 0), fill="x")

        ttk.Button(
            self.frame_panel,
            text="Sauvegarder",
            command=lambda: self._sauvegarder_panel(fid),
        ).pack(padx=14, pady=10, fill="x")

        ttk.Separator(self.frame_panel).pack(fill="x", padx=10)
        ttk.Label(self.frame_panel, text="Metriques live",
                  font=("Segoe UI", 9, "bold")).pack(pady=(10, 0), padx=14, anchor="w")
        self.lbl_panel_metrics = ttk.Label(
            self.frame_panel, text="—\n—\n—",
            foreground="#27ae60", justify="left",
        )
        self.lbl_panel_metrics.pack(padx=14, pady=4, anchor="w")

    def _masquer_panel(self):
        self._selected_fid = None
        self.frame_panel.pack_forget()

    def _sauvegarder_panel(self, fid: str):
        fournisseurs = self.config_manager.get_fournisseurs()
        fconf        = fournisseurs.get(fid, {})
        for cle, (var, _) in self._vars_panel.items():
            try:
                fconf[cle] = float(var.get())
            except ValueError:
                pass
        if hasattr(self, "_var_actif"):
            fconf["actif"] = self._var_actif.get()
        self.config_manager.sauvegarder_fournisseur(fconf)
        self._dessiner()

    def _effacer_chemin(self, fid: str):
        fournisseurs = self.config_manager.get_fournisseurs()
        fconf = fournisseurs.get(fid, {})
        fconf.pop("chemin_waypoints", None)
        self.config_manager.sauvegarder_fournisseur(fconf)
        self._dessiner()
        self._afficher_panel(fid)

    # Refresh temps reel

    def _planifier_refresh(self):
        self._refresh()
        self.parent.after(2000, self._planifier_refresh)

    def _refresh(self):
        tlive = self.tab_live_ref
        if tlive is None or not getattr(tlive, "running", False):
            return
        try:
            self.canvas.itemconfig(
                self._labo_ids.get("metrics", -1),
                text=f"File: {len(tlive.entry_queue)}  Sortis: {tlive.tubes_sortis}",
            )
        except Exception:
            pass
        navette_stats = getattr(tlive, "navette_stats", {})
        for fid, stats in navette_stats.items():
            en_transit = stats.get("en_transit", 0)
            total_env  = stats.get("total_envoye", 0)
            try:
                m2 = self._boites.get(fid, {}).get("m2")
                if m2:
                    self.canvas.itemconfig(
                        m2,
                        text=f"En transit : {en_transit}  Envoyes : {total_env}",
                    )
            except Exception:
                pass
        if self._selected_fid and hasattr(self, "lbl_panel_metrics"):
            stats = navette_stats.get(self._selected_fid, {})
            try:
                self.lbl_panel_metrics.config(
                    text=f"En transit  : {stats.get('en_transit', 0)}\n"
                         f"Total envoyes : {stats.get('total_envoye', 0)}\n"
                         f"En queue    : {stats.get('en_queue', 0)}"
                )
            except Exception:
                pass

    @staticmethod
    def _duree_trajet(pos_f: dict, pos_labo: dict, ppm: float) -> float:
        dx   = (pos_f.get("x", 50) + BOX_W) - pos_labo.get("x", 590)
        dy   = (pos_f.get("y", 300) + BOX_H // 2) - (pos_labo.get("y", 272) + LABO_H // 2)
        dist = math.sqrt(dx * dx + dy * dy)
        return max(1.0, dist / max(1.0, ppm))
