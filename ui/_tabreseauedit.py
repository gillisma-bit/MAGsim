"""Mixin _TabReseauEdit — extrait de tab_reseau.py.

Ces méthodes utilisent `self.xxx` défini dans TabReseau.__init__.
"""
import tkinter as tk
from tkinter import simpledialog
from typing import Optional
from ui._reseau_const import (
    GRID, M_PAR_CASE, VITESSE_M_MIN,
    MODE_NORMAL, MODE_CHEMIN, MODE_ZONE, MODE_EDIT_WP, MODE_EDIT_ZONE,
    SNAP_MAGNET, PALETTE_ZONES,
    _snap, _dist_chemin, _duree_depuis_chemin,
)

class _TabReseauEdit:
    """Mixin : ne pas instancier directement."""

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
