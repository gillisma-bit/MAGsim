import tkinter as tk
from tkinter import ttk, messagebox
import threading
import ui.theme as theme

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.ticker import FuncFormatter
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

from ui._tabstatsia import _TabStatsIA
from ui._tabstatsrefresh import _TabStatsRefresh
from ui._tabstatsui import _TabStatsUI


class TabStats(_TabStatsIA, _TabStatsRefresh, _TabStatsUI):
    def __init__(self, parent, config_manager, tab_live_ref=None):
        self.parent = parent
        self.config_manager = config_manager
        self.tab_live = tab_live_ref
        self._assistant_window = None   # fenêtre flottante Assistant IA
        # ── Assistant IA intégré ──
        self._ia_conversation  = None
        self._ia_en_cours      = False
        self._ia_model         = "llama3"
        self._ia_backend       = "ollama"   # "ollama" | "github"
        self._ia_token_start   = None
        self._ia_stop_event    = None
        self._build_ui()
        threading.Thread(target=self._ia_charger_modeles, daemon=True).start()

    def set_tab_live(self, tab_live):
        self.tab_live = tab_live

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def _stats_card(self, parent, niveau, titre, corps_lignes):
        """Carte visuellement stylisée dans le panneau résumé."""
        COULEURS = {
            "ok":      ("#27ae60", "#eafaf1"),
            "info":    ("#2980b9", "#eaf3fb"),
            "warning": ("#e67e22", "#fef9ec"),
            "error":   ("#c0392b", "#fdf2f2"),
            "neutre":  ("#7f8c8d", "#f5f5f5"),
        }
        accent, bg = COULEURS.get(niveau, COULEURS["neutre"])

        outer = tk.Frame(parent, bg=accent, padx=1, pady=1)
        outer.pack(fill="x", padx=8, pady=4)

        inner = tk.Frame(outer, bg=bg, padx=8, pady=5)
        inner.pack(fill="x")

        tk.Label(inner, text=titre, font=theme.FONT_LABEL,
                 bg=bg, fg=accent, anchor="w").pack(fill="x")

        for ligne in corps_lignes:
            tk.Label(inner, text=ligne, font=theme.FONT_BODY,
                     bg=bg, fg="#2c3e50", anchor="w", wraplength=220,
                     justify="left").pack(fill="x")

    def _update_panneau_resume(self, hist, times, noms, machines,
                               distances, bienetre_data, fmt_duree):
        """Met à jour le panneau résumé à droite des graphiques."""
        # Vider les cartes précédentes
        for w in self._resume_inner.winfo_children():
            w.destroy()

        if hasattr(self, "_resume_placeholder"):
            self._resume_placeholder = None

        t_total = times[-1] if times else 0
        total_tubes = getattr(self.tab_live, "stats_tubes_total", 0)

        # ─ Durée + volume ──────────────────────────────────────────
        self._stats_card(self._resume_inner, "info",
                         "🕐  Durée & volume",
                         [f"Durée simulée : {fmt_duree(t_total)}",
                          f"Tubes générés : {total_tubes}"])

        # ─ Goulot + machine la plus occupée ────────────────────────
        goulot_nom = "—"  ;  goulot_val = -1.0
        busiest_nom = "—"  ;  busiest_val = -1.0
        for nom in noms:
            q = hist["queues"].get(nom, [])
            if q:
                avg = sum(q) / len(q)
                if avg > goulot_val:
                    goulot_val = avg  ;  goulot_nom = nom
            b = hist["busy"].get(nom, [])
            if b:
                pct = sum(b) / len(b) * 100
                if pct > busiest_val:
                    busiest_val = pct  ;  busiest_nom = nom

        fk_niv = "warning" if goulot_val > 3 else "ok"
        self._stats_card(self._resume_inner, fk_niv,
                         "🎀  Goulot étranglement",
                         [f"File la plus longue : {goulot_nom}",
                          f"Longueur moy. : {goulot_val:.1f} tube(s)",
                          f"Machine la plus occupée : {busiest_nom}",
                          f"Occupation : {busiest_val:.0f} %"])

        # ─ Transit ────────────────────────────────────────────────
        transit_avg = list(hist.get("transit_time_avg", []))
        transit_roll = list(hist.get("transit_time_rolling", []))
        avg_val   = next((v for v in reversed(transit_avg)  if v is not None), None)
        roll_val  = next((v for v in reversed(transit_roll) if v is not None), None)
        tr_niv = "warning" if (avg_val and avg_val > 30) else "ok"
        self._stats_card(self._resume_inner, tr_niv,
                         "⏱  Temps de transit",
                         [f"Moyen   : {fmt_duree(avg_val)}",
                          f"Glissant: {fmt_duree(roll_val)}"])

        # ─ Rejets / dégradés / pannes ────────────────────────────
        nb_rejetes  = getattr(self.tab_live, "tubes_rejetes",  0)
        nb_degrades = getattr(self.tab_live, "tubes_degrades", 0)
        nb_pannes   = sum(len(v) for v in hist.get("pannes", {}).values())
        err_niv = "error" if (nb_rejetes + nb_degrades + nb_pannes > 0) else "ok"
        self._stats_card(self._resume_inner, err_niv,
                         "⚠  Incidents",
                         [f"Rejets      : {nb_rejetes}",
                          f"Dégradés   : {nb_degrades}",
                          f"Pannes mach.: {nb_pannes}"])

        # ─ Disponibilité théorique ────────────────────────────────
        lignes_dispo = []
        for nom in noms:
            m = machines[nom]
            tmep_m = m.get("tmep", 0) or 0
            tmr_m  = m.get("tmr",  0) or 0
            if tmep_m > 0 and tmr_m > 0:
                dispo = tmep_m / (tmep_m + tmr_m) * 100
                niv_d = "ok" if dispo >= 90 else ("warning" if dispo >= 70 else "error")
                lignes_dispo.append(f"{nom} : {dispo:.0f} %")
        if lignes_dispo:
            self._stats_card(self._resume_inner, "info",
                             "📦  Disponibilité théorique",
                             lignes_dispo)

        # ─ Distance marchée (texte) ───────────────────────────────
        if distances and any(bool(v) for v in distances.values()):
            lignes_dist = []
            for nom, jours_dist in distances.items():
                if jours_dist:
                    total_dist = sum(jours_dist.values())
                    nb_jours = len(jours_dist)
                    moy_dist = total_dist / nb_jours if nb_jours else 0
                    lignes_dist.append(f"{nom} :")
                    lignes_dist.append(f"  moy/jour : {moy_dist:.0f} m")
                    lignes_dist.append(f"  total    : {total_dist:.0f} m")
            if lignes_dist:
                self._stats_card(self._resume_inner, "neutre",
                                 "🚶  Distance marchée / tech",
                                 lignes_dist)

        # ─ Bien-être techniciens ─────────────────────────────────
        if bienetre_data:
            from core.technician import TechnicianState
            _tmp = TechnicianState(0, 0)
            lignes_be = []
            pire_niv = "ok"
            for nom, jours_be in bienetre_data.items():
                if jours_be:
                    last_val = jours_be[max(jours_be.keys())]
                    _tmp.mecontentement = last_val
                    emoji_be, _, label_be = _tmp.etat_bien_etre()
                    risque = _tmp.calculer_risque_arret_maladie()
                    lignes_be.append(f"{emoji_be} {nom} : {label_be}")
                    if risque > 0.5:
                        lignes_be.append(f"   ⚠ Risque arrêt : {risque*100:.0f} %")
                        pire_niv = "warning"
                    if risque > 0.8:
                        pire_niv = "error"
            if lignes_be:
                self._stats_card(self._resume_inner, pire_niv,
                                 "🫀  Bien-être techniciens",
                                 lignes_be)

        # Forcer le recalcul de la zone de défilement
        self._resume_inner.update_idletasks()
        self._resume_canvas.configure(
            scrollregion=self._resume_canvas.bbox("all"))

    # ------------------------------------------------------------------
    def forcer_arret_sim(self):
        """Délègue le reset brutal à tab_live puis remet l'UI de cet onglet au repos."""
        if self.tab_live:
            self.tab_live.forcer_arret()
        self.btn_fast.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.lbl_fast_status.config(text="⏹ Arrêt forcé.")
        self.progress["value"] = 0

    def lancer_debug_rapide(self):
        """Délègue au mode DEBUG de tab_live (simulation headless instrumentée)."""
        if not self.tab_live:
            self.lbl_fast_status.config(text="Référence simulation manquante.")
            return
        if getattr(self.tab_live, "running", False):
            self.lbl_fast_status.config(text="⚠ Simulation déjà en cours — arrêtez-la d'abord.")
            return
        self.btn_stop.config(state="normal")
        self.btn_fast.config(state="disabled")
        self.lbl_fast_status.config(text="🐛 DEBUG en cours…")
        self.tab_live.lancer_debug(on_fin=self._on_debug_termine)

    def _on_debug_termine(self):
        """Appelé depuis le thread debug quand la session debug se termine."""
        self.parent.after(0, lambda: (
            self.btn_stop.config(state="disabled"),
            self.btn_fast.config(state="normal"),
            self.lbl_fast_status.config(text="🐛 DEBUG terminé"),
        ))

    def lancer_simulation_rapide(self):
        """Déclenche une simulation headless et affiche les graphiques à la fin."""
        if not self.tab_live:
            self.lbl_fast_status.config(text="Référence simulation manquante.")
            return
        if getattr(self.tab_live, "running", False):
            self.lbl_fast_status.config(text="⚠ Simulation LIVE déjà en cours — arrêtez-la d'abord.")
            return

        try:
            duree_jours = float(self.ent_duree.get())
            if duree_jours <= 0:
                raise ValueError
            duree = duree_jours * 1440  # conversion jours → minutes SimPy
        except ValueError:
            self.lbl_fast_status.config(text="Durée invalide (ex : 1, 2, 0.5).")
            return

        # IA désactivée en mode headless — Qwen 32B est synchrone et bloquerait
        # le thread pour chaque appel (potentiellement des centaines sur 10 jours).
        self.tab_live.coordinateur.ia_active = False

        self.btn_fast.config(state="disabled")
        self.btn_stop.config(state="normal")
        if hasattr(self.tab_live, 'btn_reset'):
            self.tab_live.btn_reset.config(state="normal")
        self.progress["value"] = 0
        self.lbl_fast_status.config(text="⏳ Calcul en cours…")

        def on_progress(t, total):
            pct = t / total * 100
            # Mise à jour UI depuis le thread via after()
            self.parent.after(0, lambda p=pct, tt=t: (
                self.progress.configure(value=p),
                self.lbl_fast_status.config(text=f"{p:.0f} %  (t={tt:.0f})")
            ))

        def on_complete():
            self.parent.after(0, self._on_simulation_rapide_terminee)

        self.tab_live.lancer_simulation_headless(duree,
                                                  on_progress=on_progress,
                                                  on_complete=on_complete)

    def _on_simulation_rapide_terminee(self):
        """Appelé sur le thread principal quand la simulation rapide est finie."""
        self.progress["value"] = 100
        self.lbl_fast_status.config(text="✅ Terminé")
        self.btn_fast.config(state="normal")
        self.btn_stop.config(state="disabled")
        if hasattr(self.tab_live, 'btn_reset'):
            self.tab_live.btn_reset.config(state="disabled")
        self.refresh()
        # Initialiser la conversation si elle n'existe pas encore (race condition au démarrage)
        if self._ia_conversation is None:
            self._ia_init_conversation()
        self._ia_compte_rendu_auto()

    # ------------------------------------------------------------------
    # ─────────────────────────────────────────────────────────────────────────
    #  Assistant IA intégré (panneau central)
    # ─────────────────────────────────────────────────────────────────────────

    def clear_history(self):
        if self.tab_live:
            self.tab_live.stats_history = {"time": [], "queues": {}, "output": {}, "busy": {}, "entry": [],
                                           "transit_time_avg": [], "transit_time_rolling": [],
                                           "rejetes": [], "degrades": [], "pannes": {}}
            self.tab_live.stats_tubes_total = 0
            self.tab_live.tubes_rejetes = 0
            self.tab_live.tubes_degrades = 0
        if HAS_MATPLOTLIB:
            self.fig.clear()
            self.canvas_mpl.draw()
        # Vider le panneau résumé
        for w in self._resume_inner.winfo_children():
            w.destroy()
        tk.Label(self._resume_inner,
                 text="Historique effacé.\nLancez une simulation\npuis cliquez sur Actualiser.",
                 font=("Segoe UI", 9, "italic"), bg="#f8f9fa", fg="#999",
                 justify="center", pady=20).pack()
