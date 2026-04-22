"""Onglet Réseau — topologie des blocs fournisseurs connectés au laboratoire.

Architecture
------------
Vue niveau 0 (macro) : blocs fournisseurs + navettes + laboratoire.

Interactions
------------
- Glisser un bloc fournisseur → ajuste la durée de trajet (longueur du connecteur)
- Largeur du connecteur ∝ débit estimé (tubes/heure)
- Clic sur un fournisseur → panneau de configuration latéral
- Double-clic sur le Laboratoire → bascule vers l'onglet Simulation Live
- Métriques temps réel rafraîchies toutes les 2 secondes depuis tab_live
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Optional

# ── Constantes visuelles ───────────────────────────────────────────────────────
FOND           = "#0d1117"
FOND_BOITE     = "#1e2a38"
COULEUR_TEXTE  = "#ecf0f1"
COULEUR_GRIS   = "#566573"
COULEUR_SOUS   = "#7f8c8d"
COULEUR_LABO   = "#1b4f72"
BORD_LABO      = "#2e86c1"

BOX_W, BOX_H   = 178, 78    # boîte fournisseur
LABO_W, LABO_H = 190, 95    # boîte laboratoire

ECHELLE_PPM    = 40.0        # pixels par minute de transit (valeur par défaut)


class TabReseau:
    """Onglet topologie réseau (niveau 0)."""

    def __init__(self, parent, config_manager, app):
        self.parent           = parent
        self.config_manager   = config_manager
        self.app              = app
        self.tab_live_ref: Optional[object] = None   # injecté depuis main.py

        # État de l'interface
        self._selected_fid: Optional[str] = None
        self._drag_data: dict  = {}    # {fid: {x, y}}
        self._boites:    dict  = {}    # {fid: {rect, bande, title, m1, m2, status}}
        self._conns:     dict  = {}    # {fid: {line, nav, lab, transit}}
        self._labo_ids:  dict  = {}    # ids canvas de la boîte labo

        self._build_ui()
        self._dessiner()
        self._planifier_refresh()

    # ── Construction de l'interface ───────────────────────────────────────────

    def _build_ui(self):
        self.frame_main = ttk.Frame(self.parent)
        self.frame_main.pack(fill="both", expand=True)

        # Canvas principal (occupe toute la largeur sauf le panneau latéral)
        self.canvas = tk.Canvas(
            self.frame_main,
            bg=FOND,
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(side="left", fill="both", expand=True)

        # Panneau latéral de configuration (affiché au clic sur un fournisseur)
        self.frame_panel = ttk.Frame(self.frame_main, width=295)
        self.frame_panel.pack_propagate(False)
        # Non affiché initialement

        self.canvas.bind("<Button-1>",        self._on_canvas_clic)
        self.canvas.bind("<Double-Button-1>", self._on_double_clic)

    # ── Dessin complet ────────────────────────────────────────────────────────

    def _dessiner(self):
        """Reconstruit toute la vue depuis la config."""
        self.canvas.delete("all")
        self._boites.clear()
        self._conns.clear()
        self._labo_ids.clear()

        fournisseurs = self.config_manager.get_fournisseurs()
        navette      = self.config_manager.get_navette_principale()
        labo_pos     = navette.get("position_labo_canvas", {"x": 710, "y": 390})

        # En-tête
        self.canvas.create_text(
            14, 12, anchor="nw",
            text="🔗  Topologie Réseau — Niveau 0",
            fill=COULEUR_TEXTE, font=("Segoe UI", 13, "bold"),
        )
        self.canvas.create_text(
            14, 34, anchor="nw",
            text="Glissez les blocs pour ajuster le délai de transit  ·  "
                 "Double-clic sur le Laboratoire pour entrer en simulation",
            fill=COULEUR_SOUS, font=("Segoe UI", 9),
        )

        # Connecteurs (sous les boîtes)
        for fid, fconf in fournisseurs.items():
            self._dessiner_connecteur(fid, fconf, labo_pos, navette)

        # Boîte Laboratoire (fixe)
        self._dessiner_labo(labo_pos)

        # Boîtes fournisseurs (draggables)
        for fid, fconf in fournisseurs.items():
            pos = fconf.get("position_canvas", {"x": 150, "y": 300})
            self._dessiner_fournisseur(fid, fconf, pos)

        # Légende
        self._dessiner_legende()

    # ── Connecteur ───────────────────────────────────────────────────────────

    def _dessiner_connecteur(self, fid, fconf, labo_pos, navette):
        pos = fconf.get("position_canvas", {"x": 150, "y": 300})
        x1  = pos["x"] + BOX_W
        y1  = pos["y"] + BOX_H // 2
        x2  = labo_pos["x"]
        y2  = labo_pos["y"] + LABO_H // 2

        # Épaisseur ∝ débit estimé (tubes/heure à facteur=1)
        freq   = float(fconf.get("frequence_base", 30))
        debit  = 60.0 / max(1.0, freq)
        width  = max(2, min(10, int(debit * 2)))

        couleur = fconf.get("couleur", COULEUR_GRIS)
        if not fconf.get("actif", True):
            couleur = COULEUR_GRIS
            width   = 1

        tag_c  = f"conn_{fid}"

        # Ligne principale (courbe lisse)
        mx = (x1 + x2) / 2
        line_id = self.canvas.create_line(
            x1, y1, mx, y1, mx, y2, x2, y2,
            fill=couleur, width=width,
            smooth=True, splinesteps=24,
            arrow=tk.LAST, arrowshape=(14, 18, 6),
            capstyle=tk.ROUND,
            tags=(tag_c, "connector"),
        )

        # Icône navette au milieu
        ny    = (y1 + y2) / 2
        nav_id = self.canvas.create_text(
            mx, ny - 18,
            text="🚐",
            font=("Segoe UI", 13),
            tags=(tag_c, "navette_icon"),
        )

        # Label durée de trajet
        ppm    = navette.get("pixels_par_minute", ECHELLE_PPM)
        trajet = fconf.get("duree_trajet_min",
                           self._duree_trajet(pos, labo_pos, ppm))
        lab_id = self.canvas.create_text(
            mx, ny,
            text=f"{trajet:.0f} min",
            fill=COULEUR_SOUS, font=("Segoe UI", 8),
            tags=(tag_c, "trajet_label"),
        )

        # Label tubes en transit (live)
        transit_id = self.canvas.create_text(
            mx, ny + 16,
            text="",
            fill=couleur, font=("Segoe UI", 8, "bold"),
            tags=(tag_c, f"transit_live_{fid}"),
        )

        self._conns[fid] = {
            "line": line_id, "nav": nav_id,
            "lab": lab_id,   "transit": transit_id,
        }

    # ── Boîte Laboratoire ─────────────────────────────────────────────────────

    def _dessiner_labo(self, labo_pos):
        x, y = labo_pos["x"], labo_pos["y"]

        # Ombre
        self.canvas.create_rectangle(
            x+4, y+4, x+LABO_W+4, y+LABO_H+4,
            fill="#000000", outline="", tags="labo",
        )
        # Corps
        rect_id = self.canvas.create_rectangle(
            x, y, x+LABO_W, y+LABO_H,
            fill=COULEUR_LABO, outline=BORD_LABO, width=2, tags="labo",
        )
        icon_id = self.canvas.create_text(
            x + LABO_W // 2, y + 22,
            text="🔬  Laboratoire d'Analyses",
            fill=COULEUR_TEXTE, font=("Segoe UI", 11, "bold"),
            tags="labo",
        )
        met_id = self.canvas.create_text(
            x + LABO_W // 2, y + 45,
            text="—",
            fill="#27ae60", font=("Segoe UI", 8, "bold"),
            tags=("labo", "labo_metrics"),
        )
        hint_id = self.canvas.create_text(
            x + LABO_W // 2, y + 68,
            text="⬆ Double-clic pour entrer en simulation",
            fill=COULEUR_SOUS, font=("Segoe UI", 8, "italic"),
            tags="labo",
        )

        self._labo_ids = {
            "rect": rect_id, "icon": icon_id,
            "metrics": met_id, "hint": hint_id,
        }

        for iid in self._labo_ids.values():
            self.canvas.tag_bind(iid, "<Enter>",
                                 lambda e: self.canvas.config(cursor="hand2"))
            self.canvas.tag_bind(iid, "<Leave>",
                                 lambda e: self.canvas.config(cursor="crosshair"))
            self.canvas.tag_bind(iid, "<Double-Button-1>",
                                 self._basculer_vers_simulation)

    # ── Boîte Fournisseur ─────────────────────────────────────────────────────

    def _dessiner_fournisseur(self, fid, fconf, pos):
        x, y    = pos["x"], pos["y"]
        couleur = fconf.get("couleur", COULEUR_GRIS)
        nom     = fconf.get("nom", fid)
        icone   = fconf.get("icone", "📦")
        actif   = fconf.get("actif", True)
        c       = couleur if actif else COULEUR_GRIS

        tag = f"f_{fid}"

        # Ombre
        self.canvas.create_rectangle(
            x+3, y+3, x+BOX_W+3, y+BOX_H+3,
            fill="#000000", outline="", tags=(tag, "ombre"),
        )
        # Corps
        rect_id = self.canvas.create_rectangle(
            x, y, x+BOX_W, y+BOX_H,
            fill=FOND_BOITE, outline=c, width=2,
            tags=(tag, "boite"),
        )
        # Bande de couleur gauche
        bande_id = self.canvas.create_rectangle(
            x, y, x+6, y+BOX_H,
            fill=c, outline="", tags=(tag, "bande"),
        )
        # Nom (tronqué)
        nom_c = nom if len(nom) <= 24 else nom[:22] + "…"
        title_id = self.canvas.create_text(
            x + BOX_W // 2 + 3, y + 20,
            text=f"{icone}  {nom_c}",
            fill=COULEUR_TEXTE if actif else COULEUR_SOUS,
            font=("Segoe UI", 9, "bold"),
            tags=(tag, "titre"),
        )
        # Ligne débit/urgents
        freq = float(fconf.get("frequence_base", 30))
        purg = int(fconf.get("pct_urgent", 0) * 100)
        m1_id = self.canvas.create_text(
            x + BOX_W // 2 + 3, y + 39,
            text=f"≈ {60/freq:.1f} tubes/h   {purg}% urgents",
            fill=COULEUR_SOUS, font=("Segoe UI", 8),
            tags=(tag, "m1"),
        )
        # Ligne live (mise à jour par refresh)
        m2_id = self.canvas.create_text(
            x + BOX_W // 2 + 3, y + 57,
            text="En transit : —",
            fill=c, font=("Segoe UI", 8, "bold"),
            tags=(tag, f"live_{fid}", "live_metric"),
        )
        # Voyant actif/inactif
        status_id = self.canvas.create_oval(
            x + BOX_W - 14, y + 6, x + BOX_W - 6, y + 14,
            fill="#27ae60" if actif else "#7f8c8d",
            outline="", tags=(tag, "status"),
        )

        self._boites[fid] = {
            "rect": rect_id, "bande": bande_id, "title": title_id,
            "m1": m1_id, "m2": m2_id, "status": status_id,
        }

        # Bindings drag + curseur
        for iid in [rect_id, bande_id, title_id, m1_id, m2_id, status_id]:
            self.canvas.tag_bind(iid, "<ButtonPress-1>",
                                 lambda e, f=fid: self._drag_start(e, f))
            self.canvas.tag_bind(iid, "<B1-Motion>",
                                 lambda e, f=fid: self._drag_move(e, f))
            self.canvas.tag_bind(iid, "<ButtonRelease-1>",
                                 lambda e, f=fid: self._drag_end(e, f))
            self.canvas.tag_bind(iid, "<Enter>",
                                 lambda e: self.canvas.config(cursor="fleur"))
            self.canvas.tag_bind(iid, "<Leave>",
                                 lambda e: self.canvas.config(cursor="crosshair"))

    # ── Légende ───────────────────────────────────────────────────────────────

    def _dessiner_legende(self):
        self.canvas.create_text(
            14, 760, anchor="sw",
            text="Épaisseur du connecteur ∝ débit (tubes/h)   ·   "
                 "Longueur du connecteur ∝ délai de transit navette",
            fill=COULEUR_SOUS, font=("Segoe UI", 8, "italic"),
            tags="legende",
        )

    # ── Drag & Drop ───────────────────────────────────────────────────────────

    def _drag_start(self, event, fid):
        self._drag_data[fid] = {"x": event.x, "y": event.y}
        self._selected_fid   = fid
        self.canvas.tag_raise(f"f_{fid}")
        self._afficher_panel(fid)

    def _drag_move(self, event, fid):
        if fid not in self._drag_data:
            return
        dx = event.x - self._drag_data[fid]["x"]
        dy = event.y - self._drag_data[fid]["y"]
        self._drag_data[fid] = {"x": event.x, "y": event.y}

        self.canvas.move(f"f_{fid}", dx, dy)

        # Mettre à jour position dans la config
        fournisseurs = self.config_manager.get_fournisseurs()
        if fid not in fournisseurs:
            return
        fconf = fournisseurs[fid]
        pos   = fconf.get("position_canvas", {"x": 150, "y": 300})
        pos["x"] += dx
        pos["y"] += dy
        fconf["position_canvas"] = pos

        # Recalculer durée de trajet depuis la nouvelle distance
        navette  = self.config_manager.get_navette_principale()
        labo_pos = navette.get("position_labo_canvas", {"x": 710, "y": 390})
        ppm      = navette.get("pixels_par_minute", ECHELLE_PPM)
        trajet   = self._duree_trajet(pos, labo_pos, ppm)
        fconf["duree_trajet_min"] = round(trajet, 1)

        # Redessiner uniquement le connecteur
        for iid in self._conns.get(fid, {}).values():
            self.canvas.delete(iid)
        self._dessiner_connecteur(fid, fconf, labo_pos, navette)

        # Mettre à jour le label dans le panneau latéral
        if hasattr(self, "_vars_panel") and "duree_trajet_min" in self._vars_panel:
            self._vars_panel["duree_trajet_min"][0].set(f"{trajet:.1f}")

    def _drag_end(self, event, fid):
        self._drag_data.pop(fid, None)
        fournisseurs = self.config_manager.get_fournisseurs()
        if fid in fournisseurs:
            self.config_manager.sauvegarder_fournisseur(fournisseurs[fid])

    # ── Clics canvas ─────────────────────────────────────────────────────────

    def _on_canvas_clic(self, event):
        items = self.canvas.find_overlapping(
            event.x - 3, event.y - 3, event.x + 3, event.y + 3)
        fid_trouve = None
        for iid in items:
            for tag in self.canvas.gettags(iid):
                if tag.startswith("f_"):
                    fid_trouve = tag[2:]
                    break
            if fid_trouve:
                break

        if fid_trouve:
            self._selected_fid = fid_trouve
            self._afficher_panel(fid_trouve)
        else:
            self._masquer_panel()

    def _on_double_clic(self, event):
        items = self.canvas.find_overlapping(
            event.x - 3, event.y - 3, event.x + 3, event.y + 3)
        for iid in items:
            if "labo" in self.canvas.gettags(iid):
                self._basculer_vers_simulation(event)
                return

    def _basculer_vers_simulation(self, event=None):
        try:
            nb = self.app.notebook.index("end")
            for i in range(nb):
                if "SIMULATION" in self.app.notebook.tab(i, "text").upper():
                    self.app.notebook.select(i)
                    return
        except Exception:
            pass

    # ── Panneau latéral ───────────────────────────────────────────────────────

    def _afficher_panel(self, fid):
        fournisseurs = self.config_manager.get_fournisseurs()
        fconf        = fournisseurs.get(fid, {})

        for w in self.frame_panel.winfo_children():
            w.destroy()

        if not self.frame_panel.winfo_ismapped():
            self.frame_panel.pack(side="right", fill="y")

        # En-tête
        ttk.Label(
            self.frame_panel,
            text=f"{fconf.get('icone','📦')}  {fconf.get('nom', fid)}",
            font=("Segoe UI", 11, "bold"),
        ).pack(pady=(15, 4), padx=12)
        ttk.Separator(self.frame_panel).pack(fill="x", padx=10)

        # Champs éditables
        fr = ttk.Frame(self.frame_panel)
        fr.pack(fill="x", padx=14, pady=8)

        champs = [
            ("Fréquence base (min/tube)", "frequence_base"),
            ("Gamma k (régularité)",      "gamma_k"),
            ("% Urgents (0.0 – 1.0)",     "pct_urgent"),
            ("Délai trajet navette (min)", "duree_trajet_min"),
        ]
        self._vars_panel = {}
        for label, cle in champs:
            ttk.Label(fr, text=label).pack(anchor="w", pady=(5, 0))
            var = tk.StringVar(value=str(fconf.get(cle, "")))
            self._vars_panel[cle] = (var, fid)
            ttk.Entry(fr, textvariable=var, width=22).pack(fill="x")

        ttk.Separator(self.frame_panel).pack(fill="x", padx=10, pady=6)

        # Actif / Inactif
        self._var_actif = tk.BooleanVar(value=fconf.get("actif", True))
        ttk.Checkbutton(
            self.frame_panel,
            text="Fournisseur actif",
            variable=self._var_actif,
        ).pack(padx=14, anchor="w")

        ttk.Button(
            self.frame_panel,
            text="💾  Sauvegarder",
            command=lambda: self._sauvegarder_panel(fid),
        ).pack(padx=14, pady=10, fill="x")

        # Métriques live
        ttk.Separator(self.frame_panel).pack(fill="x", padx=10)
        ttk.Label(
            self.frame_panel,
            text="Métriques live",
            font=("Segoe UI", 9, "bold"),
        ).pack(pady=(10, 0), padx=14, anchor="w")
        self.lbl_panel_metrics = ttk.Label(
            self.frame_panel,
            text="—\n—\n—",
            foreground="#27ae60",
            justify="left",
        )
        self.lbl_panel_metrics.pack(padx=14, pady=4, anchor="w")

    def _masquer_panel(self):
        self._selected_fid = None
        self.frame_panel.pack_forget()

    def _sauvegarder_panel(self, fid):
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

    # ── Rafraîchissement temps réel ───────────────────────────────────────────

    def _planifier_refresh(self):
        self._refresh()
        self.parent.after(2000, self._planifier_refresh)

    def _refresh(self):
        tlive = self.tab_live_ref
        if tlive is None or not getattr(tlive, "running", False):
            return

        # Métriques labo
        try:
            en_file = len(tlive.entry_queue)
            sortis  = tlive.tubes_sortis
            self.canvas.itemconfig(
                self._labo_ids.get("metrics", -1),
                text=f"File: {en_file}  ·  Sortis: {sortis}",
            )
        except Exception:
            pass

        # Métriques navette par fournisseur
        navette_stats = getattr(tlive, "navette_stats", {})
        for fid, stats in navette_stats.items():
            en_transit = stats.get("en_transit", 0)
            total_env  = stats.get("total_envoye", 0)

            # Label sur le connecteur
            try:
                tid = self._conns.get(fid, {}).get("transit")
                if tid:
                    txt = f"🚐 {en_transit} en vol" if en_transit > 0 else ""
                    self.canvas.itemconfig(tid, text=txt)
            except Exception:
                pass

            # Label dans la boîte fournisseur
            try:
                m2 = self._boites.get(fid, {}).get("m2")
                if m2:
                    self.canvas.itemconfig(
                        m2,
                        text=f"En transit : {en_transit}  ·  Envoyés : {total_env}",
                    )
            except Exception:
                pass

        # Panneau latéral si un fournisseur est sélectionné
        if self._selected_fid and hasattr(self, "lbl_panel_metrics"):
            stats = navette_stats.get(self._selected_fid, {})
            try:
                self.lbl_panel_metrics.config(
                    text=f"En transit       : {stats.get('en_transit', 0)}\n"
                         f"Total envoyés    : {stats.get('total_envoye', 0)}\n"
                         f"Tubes en queue   : {stats.get('en_queue', 0)}"
                )
            except Exception:
                pass

    # ── Utilitaires ───────────────────────────────────────────────────────────

    @staticmethod
    def _duree_trajet(pos_f: dict, pos_labo: dict, ppm: float) -> float:
        """Durée de trajet (min) = distance canvas / pixels_par_minute."""
        dx   = (pos_f.get("x", 150) + BOX_W) - pos_labo.get("x", 710)
        dy   = (pos_f.get("y", 300) + BOX_H // 2) - (pos_labo.get("y", 390) + LABO_H // 2)
        dist = math.sqrt(dx * dx + dy * dy)
        return max(1.0, dist / max(1.0, ppm))
