"""Mixin _TabReseauDessiner — extrait de tab_reseau.py.

Ces méthodes utilisent `self.xxx` défini dans TabReseau.__init__.
"""
import math
import tkinter as tk
from typing import Optional
from ui._reseau_const import (
    FOND, FOND_BOITE, COULEUR_TEXTE, COULEUR_GRIS, COULEUR_SOUS,
    COULEUR_LABO, BORD_LABO, BOX_W, BOX_H, LABO_W, LABO_H,
    GRID, M_PAR_CASE, VITESSE_M_MIN,
    MODE_NORMAL, MODE_CHEMIN, MODE_ZONE, MODE_EDIT_WP, MODE_EDIT_ZONE,
    SNAP_MAGNET, OFFSET_CHEMIN_PX, PALETTE_ZONES,
    _snap, _dist_chemin, _duree_depuis_chemin,
)

class _TabReseauDessiner:
    """Mixin : ne pas instancier directement."""

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

    def _dessiner_grille(self):
        w = max(1400, self.canvas.winfo_width()  or 1400)
        h = max(900,  self.canvas.winfo_height() or 900)
        for gx in range(0, w, GRID):
            col = "#1e2530" if gx % (GRID * 5) == 0 else "#161b22"
            self.canvas.create_line(gx, 0, gx, h, fill=col, width=1, tags="grille")
        for gy in range(0, h, GRID):
            col = "#1e2530" if gy % (GRID * 5) == 0 else "#161b22"
            self.canvas.create_line(0, gy, w, gy, fill=col, width=1, tags="grille")

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

    def _segment_key(self, a: list, b: list) -> tuple:
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
