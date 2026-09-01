"""Mixin _TabReseauPanel — extrait de tab_reseau.py.

Ces méthodes utilisent `self.xxx` défini dans TabReseau.__init__.
"""
import tkinter as tk
from tkinter import ttk
from typing import Optional
from ui._reseau_const import (
    GRID, M_PAR_CASE, VITESSE_M_MIN,
    MODE_NORMAL, SNAP_MAGNET,
    _dist_chemin, _duree_depuis_chemin,
)

class _TabReseauPanel:
    """Mixin : ne pas instancier directement."""

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

    def _duree_trajet(pos_f: dict, pos_labo: dict, ppm: float) -> float:
        dx   = (pos_f.get("x", 50) + BOX_W) - pos_labo.get("x", 590)
        dy   = (pos_f.get("y", 300) + BOX_H // 2) - (pos_labo.get("y", 272) + LABO_H // 2)
        dist = math.sqrt(dx * dx + dy * dy)
        return max(1.0, dist / max(1.0, ppm))
