import tkinter as tk
from tkinter import ttk

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.ticker import FuncFormatter
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


class TabStats:
    def __init__(self, parent, config_manager, tab_live_ref=None):
        self.parent = parent
        self.config_manager = config_manager
        self.tab_live = tab_live_ref
        self._build_ui()

    def set_tab_live(self, tab_live):
        self.tab_live = tab_live

    def _build_ui(self):
        if not HAS_MATPLOTLIB:
            ttk.Label(
                self.parent,
                text="⚠️  matplotlib requis pour cet onglet.\n\nInstallez-le avec : pip install matplotlib",
                font=("Segoe UI", 13), foreground="#c0392b", justify="center"
            ).pack(expand=True)
            return

        # --- Barre de contrôle LIVE ---
        ctrl = ttk.Frame(self.parent)
        ctrl.pack(fill="x", padx=12, pady=(6, 2))

        ttk.Button(ctrl, text="🔄  Actualiser les graphiques",
                   command=self.refresh).pack(side=tk.LEFT, padx=5)

        ttk.Button(ctrl, text="🗑  Effacer l'historique",
                   command=self.clear_history).pack(side=tk.LEFT, padx=5)

        # ── Cases à cocher par graphique ──────────────────────────────────
        checks = ttk.Frame(self.parent)
        checks.pack(fill="x", padx=12, pady=(0, 2))

        ttk.Label(checks, text="Graphiques affichés :",
                  font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(4, 8))

        self.show_queues = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Files d'attente",
                        variable=self.show_queues,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_output_queues = tk.BooleanVar(value=False)
        ttk.Checkbutton(checks, text="Files de sortie",
                        variable=self.show_output_queues,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_occupation = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Occupation machines",
                        variable=self.show_occupation,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_transit = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Temps de transit",
                        variable=self.show_transit,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_errors = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Erreurs cumulées",
                        variable=self.show_errors,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_distances = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Distances techniciens",
                        variable=self.show_distances,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_bienetre = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Bien-être techniciens",
                        variable=self.show_bienetre,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.lbl_info = ttk.Label(
            ctrl,
            text="Lancez une simulation dans l'onglet LIVE puis cliquez sur Actualiser.",
            font=("Segoe UI", 10), foreground="#555"
        )
        self.lbl_info.pack(side=tk.LEFT, padx=18)

        # --- Barre de simulation accélérée ---
        fast = ttk.LabelFrame(self.parent, text=" ⚡ Simulation accélérée (sans animation) ")
        fast.pack(fill="x", padx=12, pady=(2, 4))

        ttk.Label(fast, text="Durée (unités de simulation) :").pack(side=tk.LEFT, padx=(8, 2), pady=4)
        self.ent_duree = ttk.Entry(fast, width=8)
        self.ent_duree.insert(0, "2880")
        self.ent_duree.pack(side=tk.LEFT, padx=2)

        ttk.Label(fast, text="  ← ex : 480 = 8h de labo  |  2880 = 2 journées  |  1 unité = 1 min",
                  font=("Segoe UI", 9), foreground="#777").pack(side=tk.LEFT, padx=4)

        self.btn_fast = ttk.Button(fast, text="▶ Lancer",
                                   command=self.lancer_simulation_rapide)
        self.btn_fast.pack(side=tk.LEFT, padx=10, pady=4)

        self.progress = ttk.Progressbar(fast, mode="determinate", length=200)
        self.progress.pack(side=tk.LEFT, padx=8, pady=4)

        self.lbl_fast_status = ttk.Label(fast, text="", font=("Segoe UI", 9), foreground="#2c3e50")
        self.lbl_fast_status.pack(side=tk.LEFT, padx=4)

        # --- Zone matplotlib ---
        container = ttk.Frame(self.parent)
        container.pack(expand=True, fill="both", padx=4, pady=4)

        # La taille sera recalculée à chaque refresh() selon le nombre de graphiques actifs
        self.fig = Figure(figsize=(15, 7), dpi=96, facecolor="#f4f6f9")
        self.canvas_mpl = FigureCanvasTkAgg(self.fig, master=container)

        toolbar = NavigationToolbar2Tk(self.canvas_mpl, container)
        toolbar.update()

        self.canvas_mpl.get_tk_widget().pack(expand=True, fill="both")

    # ------------------------------------------------------------------
    def refresh(self):
        if not HAS_MATPLOTLIB:
            return
        if not self.tab_live:
            self.lbl_info.config(text="Référence à la simulation manquante.")
            return

        hist = getattr(self.tab_live, "stats_history", None)
        if not hist or not hist.get("time"):
            self.lbl_info.config(
                text="Aucune donnée — démarrez une simulation et attendez quelques secondes.")
            return

        times = hist["time"]
        machines = self.config_manager.get_machines()
        noms = [n for n, m in machines.items()
                if m["type"] not in ("ENTREE", "SORTIE", "TECH_OFFICE")]

        # ── Helpers de conversion temps ───────────────────────────────
        entree_cfg = next((v for v in machines.values() if v["type"] == "ENTREE"), {})
        heure_debut = entree_cfg.get("heure_debut", 7.0)

        def _fmt_elapsed(t_simpy, pos=None):
            """Temps écoulé depuis le début (1 unité SimPy = 1 min)."""
            h_total = t_simpy / 60.0
            h = int(h_total)
            m = int((h_total % 1) * 60)
            if m:
                return f"{h}h{m:02d}"
            return f"{h}h"

        def _fmt_duree(minutes):
            """Formate une durée en minutes → '1h 05min' ou '42 min'."""
            minutes = int(round(minutes))
            if minutes >= 60:
                return f"{minutes // 60}h {minutes % 60:02d}min"
            return f"{minutes} min"

        x_fmt = FuncFormatter(_fmt_elapsed)

        show_queues    = self.show_queues.get()
        show_output    = self.show_output_queues.get()
        show_occup     = self.show_occupation.get()
        show_transit   = self.show_transit.get()
        show_errors    = self.show_errors.get()
        distances      = hist.get("distances_tech", {})
        has_distances  = bool(distances and any(bool(v) for v in distances.values()))
        show_dist      = self.show_distances.get() and has_distances
        bienetre_data  = hist.get("bienetre", {})
        has_bienetre   = bool(bienetre_data and any(bool(v) for v in bienetre_data.values()))
        show_bienetre  = self.show_bienetre.get() and has_bienetre

        # Liste ordonnée des graphiques actifs → index subplot dynamique
        active = [show_queues, show_output, show_occup, show_transit, show_errors, show_dist, show_bienetre]
        n_plots = sum(active)
        if n_plots == 0:
            self.fig.clear()
            self.canvas_mpl.draw()
            return

        # Grille 2 colonnes — chaque rangée a ~3.8 pouces de haut minimum
        ncols = 2 if n_plots > 1 else 1
        nrows = (n_plots + ncols - 1) // ncols   # division plafond
        fig_h = max(7, nrows * 3.8)
        self.fig.set_size_inches(15, fig_h)

        # Compteur d'index courant (subplot 1-based, remplit gauche→droite, haut→bas)
        _plot_counter = [0]
        def _next_ax():
            _plot_counter[0] += 1
            return self.fig.add_subplot(nrows, ncols, _plot_counter[0])

        self.fig.clear()

        COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12",
                  "#9b59b6", "#1abc9c", "#e67e22", "#34495e",
                  "#c0392b", "#2980b9"]

        # ── Graphique 1 : files d'attente ──────────────────────────────
        if show_queues:
            ax1 = _next_ax()
            ax1.set_facecolor("#ffffff")
            ax1.set_title("Files d'attente — tubes en attente de traitement",
                          fontsize=11, fontweight="bold", pad=8)
            ax1.set_ylabel("Nombre de tubes")
            ax1.xaxis.set_major_formatter(x_fmt)
            ax1.grid(True, alpha=0.3, linestyle="--")

            entry_data = hist.get("entry", [])
            if entry_data:
                ax1.plot(times[:len(entry_data)], entry_data,
                         label="ENTRÉE (non pris)", color="#2c3e50",
                         linewidth=2, linestyle="--", alpha=0.85)
            for i, nom in enumerate(noms):
                data = hist["queues"].get(nom, [])
                color = COLORS[i % len(COLORS)]
                if data:
                    ax1.plot(times[:len(data)], data,
                             label=nom, color=color, linewidth=2, alpha=0.9)
                fm = machines[nom].get("file_max", machines[nom].get("capacite", 4))
                ax1.axhline(y=fm, color=color, linestyle=":", alpha=0.45, linewidth=1.2)
            ax1.legend(loc="upper left", fontsize=9, framealpha=0.75)

        # ── Graphique 2 : files de sortie (optionnel) ──────────────────
        if show_output:
            ax2 = _next_ax()
            ax2.set_facecolor("#ffffff")
            ax2.set_title("Files de sortie — tubes traités en attente de récupération",
                          fontsize=11, fontweight="bold", pad=8)
            ax2.set_ylabel("Nombre de tubes")
            ax2.xaxis.set_major_formatter(x_fmt)
            ax2.grid(True, alpha=0.3, linestyle="--")
            for i, nom in enumerate(noms):
                data = hist["output"].get(nom, [])
                if data:
                    ax2.plot(times[:len(data)], data,
                             label=nom, color=COLORS[i % len(COLORS)],
                             linewidth=2, alpha=0.9)
            ax2.legend(loc="upper left", fontsize=9, framealpha=0.75)

        # ── Graphique taux d'occupation ────────────────────────────────
        if show_occup:
            ax3 = _next_ax()
            ax3.set_facecolor("#ffffff")
            ax3.set_title("Taux d'occupation des machines — fenêtre glissante 10 %",
                          fontsize=11, fontweight="bold", pad=8)
            ax3.set_ylabel("Occupation (%)")
            ax3.set_ylim(0, 108)
            ax3.xaxis.set_major_formatter(x_fmt)
            ax3.grid(True, alpha=0.3, linestyle="--")

            window = max(1, len(times) // 10)
            for i, nom in enumerate(noms):
                raw = hist["busy"].get(nom, [])
                if not raw:
                    continue
                smoothed = []
                for j in range(len(raw)):
                    start_w = max(0, j - window + 1)
                    chunk = raw[start_w: j + 1]
                    smoothed.append(sum(chunk) / len(chunk) * 100)
                ax3.plot(times[:len(smoothed)], smoothed,
                         label=nom, color=COLORS[i % len(COLORS)],
                         linewidth=2, alpha=0.9)
            ax3.legend(loc="upper left", fontsize=9, framealpha=0.75)

        # ── Graphique temps moyen de transit ───────────────────────────
        transit_avg  = hist.get("transit_time_avg", [])
        transit_roll = hist.get("transit_time_rolling", [])

        def _filter_none(t_list, v_list):
            pairs = [(t, v) for t, v in zip(t_list, v_list) if v is not None]
            if not pairs:
                return [], []
            return zip(*pairs)

        if show_transit:
            ax4 = _next_ax()
            ax4.set_facecolor("#ffffff")
            ax4.set_title("Temps de transit — de l'arrivée à la sortie",
                          fontsize=11, fontweight="bold", pad=8)
            ax4.set_ylabel("Durée (min)")
            ax4.set_xlabel("Temps écoulé")
            ax4.xaxis.set_major_formatter(x_fmt)
            ax4.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt_duree(v)))
            ax4.grid(True, alpha=0.3, linestyle="--")

            has_data = any(v is not None for v in transit_avg)
            if has_data:
                t_avg, v_avg = _filter_none(times[:len(transit_avg)], transit_avg)
                t_roll, v_roll = _filter_none(times[:len(transit_roll)], transit_roll)
                ax4.plot(list(t_avg), list(v_avg),
                         color="#8e44ad", linewidth=1.5, alpha=0.5,
                         linestyle="--", label="Moyenne cumulative")
                ax4.plot(list(t_roll), list(v_roll),
                         color="#8e44ad", linewidth=2.5, alpha=0.95,
                         label="Glissante (20 derniers)")
                last_roll = next((v for v in reversed(transit_roll) if v is not None), None)
                if last_roll is not None:
                    ax4.axhline(y=last_roll, color="#8e44ad", linestyle=":",
                                alpha=0.45, linewidth=1.2)
                    ax4.text(times[-1] if times else 0, last_roll,
                             f"  {_fmt_duree(last_roll)}",
                             va="center", fontsize=9, color="#8e44ad")
            else:
                ax4.text(0.5, 0.5,
                         "En attente — aucun tube n'a encore atteint la SORTIE.\n"
                         "La courbe apparaîtra dès que les premiers tubes completent leur parcours.",
                         ha="center", va="center", transform=ax4.transAxes,
                         fontsize=10, color="#888", style="italic")
            ax4.legend(loc="upper left", fontsize=9, framealpha=0.75)

        # ── Graphique erreurs cumulées ─────────────────────────────────
        if show_errors:
            ax5 = _next_ax()
            ax5.set_facecolor("#ffffff")
            ax5.set_title("Erreurs cumulées — rejets et dégradations",
                          fontsize=11, fontweight="bold", pad=8)
            ax5.set_ylabel("Nombre de tubes")
            ax5.set_xlabel("Temps écoulé")
            ax5.xaxis.set_major_formatter(x_fmt)
            ax5.grid(True, alpha=0.3, linestyle="--")

            rejetes_data  = hist.get("rejetes", [])
            degrades_data = hist.get("degrades", [])
            if rejetes_data:
                ax5.plot(times[:len(rejetes_data)], rejetes_data,
                         color="#e74c3c", linewidth=2, label="Rejets (mauvais prélèv. + erreur tech)")
            if degrades_data:
                ax5.plot(times[:len(degrades_data)], degrades_data,
                         color="#e67e22", linewidth=2, linestyle="--", label="Dégradés (délai / panne)")
            pannes = hist.get("pannes", {})
            for i_p, (nom_p, ts_pannes) in enumerate(pannes.items()):
                color_p = COLORS[i_p % len(COLORS)]
                for tp in ts_pannes:
                    ax5.axvline(x=tp, color=color_p, linestyle=":", alpha=0.6, linewidth=1.2)
                if ts_pannes:
                    ax5.axvline(x=ts_pannes[0], color=color_p, linestyle=":", alpha=0.6,
                                linewidth=1.2, label=f"Panne {nom_p}")
            if not rejetes_data and not degrades_data:
                ax5.text(0.5, 0.5, "Aucune erreur enregistrée.",
                         ha="center", va="center", transform=ax5.transAxes,
                         fontsize=10, color="#888", style="italic")
            ax5.legend(loc="upper left", fontsize=9, framealpha=0.75)

        # ── Graphique distance marchée par technicien par jour simulé ──
        if show_dist:
            from core.technician import TechnicianState
            ax6 = _next_ax()
            ax6.set_facecolor("#ffffff")
            ax6.set_title("Distance marchée par technicien par jour simulé  (1 case = 50 cm)",
                          fontsize=11, fontweight="bold", pad=8)
            ax6.set_ylabel("Distance (m)")
            ax6.set_xlabel("Jour simulé")
            ax6.grid(True, alpha=0.3, linestyle="--", axis="y")

            TECH_COLORS = TechnicianState.COLORS
            all_jours = sorted({j for d in distances.values() for j in d.keys()})
            n_techs = len(distances)
            width = 0.8 / max(1, n_techs)
            for i, (nom, jours_dist) in enumerate(distances.items()):
                offsets = [j - 0.4 + i * width + width / 2
                           for j in range(len(all_jours))]
                vals = [jours_dist.get(j, 0.0) for j in all_jours]
                color = TECH_COLORS[i % len(TECH_COLORS)]
                bars = ax6.bar(offsets, vals, width=width * 0.9,
                               color=color, alpha=0.85, label=nom, edgecolor="white")
                for bar, v in zip(bars, vals):
                    if v > 0:
                        ax6.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                                 f"{v:.1f} m", ha="center", va="bottom",
                                 fontsize=8, color="#333333")
            ax6.set_xticks(range(len(all_jours)))
            ax6.set_xticklabels([f"Jour {j + 1}" for j in all_jours])
            ax6.legend(loc="upper right", fontsize=9, framealpha=0.75)

        # ── Graphique bien-être des techniciens ────────────────────────
        if show_bienetre:
            from core.technician import TechnicianState
            ax7 = _next_ax()
            ax7.set_facecolor("#ffffff")
            ax7.set_title("Bien-être des techniciens — mécontentement cumulatif par jour simulé",
                          fontsize=11, fontweight="bold", pad=8)
            ax7.set_ylabel("Mécontentement [0–1]")
            ax7.set_xlabel("Jour simulé")
            ax7.set_ylim(0, 1.05)
            ax7.grid(True, alpha=0.3, linestyle="--", axis="y")

            # Zones de couleur de fond selon les seuils
            ax7.axhspan(0,    0.20, facecolor="#2ecc71", alpha=0.07)
            ax7.axhspan(0.20, 0.40, facecolor="#f1c40f", alpha=0.07)
            ax7.axhspan(0.40, 0.60, facecolor="#e67e22", alpha=0.07)
            ax7.axhspan(0.60, 0.80, facecolor="#e74c3c", alpha=0.07)
            ax7.axhspan(0.80, 1.05, facecolor="#8e44ad", alpha=0.07)

            # Annotations des zones
            for y_pos, label_be, color_be in [
                (0.10, "Satisfait 😊", "#2ecc71"),
                (0.30, "Neutre 😐", "#d4ac0d"),
                (0.50, "Stressé 😟", "#e67e22"),
                (0.70, "Épuisé 😠", "#e74c3c"),
                (0.90, "Burn-out 🤢", "#8e44ad"),
            ]:
                ax7.axhline(y=y_pos, color=color_be, linestyle=":", alpha=0.30, linewidth=1)

            TECH_COLORS = TechnicianState.COLORS
            all_jours_be = sorted({j for d in bienetre_data.values() for j in d.keys()})
            for i, (nom, jours_be) in enumerate(bienetre_data.items()):
                xs = all_jours_be
                ys = [jours_be.get(j, 0.0) for j in xs]
                color = TECH_COLORS[i % len(TECH_COLORS)]
                ax7.plot(xs, ys, color=color, linewidth=2.5, marker="o",
                         markersize=6, label=nom, alpha=0.9)
                # Annoter la dernière valeur
                if xs and ys:
                    ax7.annotate(f"{ys[-1]:.2f}", xy=(xs[-1], ys[-1]),
                                 xytext=(4, 4), textcoords="offset points",
                                 fontsize=9, color=color)
            ax7.set_xticks(all_jours_be)
            ax7.set_xticklabels([f"Jour {j + 1}" for j in all_jours_be])
            ax7.legend(loc="upper left", fontsize=9, framealpha=0.75)

        self.fig.tight_layout(pad=1.8, h_pad=2.5, w_pad=2.0)
        self.canvas_mpl.draw()

        # ── Résumé dans la barre ───────────────────────────────────────
        t_total = times[-1] if times else 0
        total_tubes = getattr(self.tab_live, "stats_tubes_total", 0)

        # Goulot : machine avec la plus grande longueur de file moyenne
        goulot_nom = "—"
        goulot_val = -1
        for nom in noms:
            data = hist["queues"].get(nom, [])
            if data:
                avg = sum(data) / len(data)
                if avg > goulot_val:
                    goulot_val = avg
                    goulot_nom = nom

        # Machine la plus occupée
        busiest_nom = "—"
        busiest_val = -1
        for nom in noms:
            raw = hist["busy"].get(nom, [])
            if raw:
                pct = sum(raw) / len(raw) * 100
                if pct > busiest_val:
                    busiest_val = pct
                    busiest_nom = nom

        transit_roll = hist.get("transit_time_rolling", [])
        last_roll = next((v for v in reversed(transit_roll) if v is not None), None)
        transit_txt = f"  |  Transit (glissant) : {_fmt_duree(last_roll)}" if last_roll else ""
        nb_rejetes  = getattr(self.tab_live, "tubes_rejetes", 0)
        nb_degrades = getattr(self.tab_live, "tubes_degrades", 0)
        nb_pannes   = sum(len(v) for v in hist.get("pannes", {}).values())

        # Disponibilité théorique par machine (TMEP / (TMEP + TMR))
        dispos = []
        for nom in noms:
            m = machines[nom]
            tmep_m = m.get("tmep", 0) or 0
            tmr_m  = m.get("tmr",  0) or 0
            if tmep_m > 0 and tmr_m > 0:
                dispos.append(f"{nom}={tmep_m/(tmep_m+tmr_m)*100:.0f}%")
        dispo_txt = ("  |  Dispo théorique : " + "  ".join(dispos)) if dispos else ""
        # Distances cumulées session (sur tous les jours)
        dist_session_txt = ""
        if has_distances:
            parts = []
            for nom, jours_dist in distances.items():
                total_m = sum(jours_dist.values())
                parts.append(f"{nom} = {total_m:.0f} m")
            dist_session_txt = "  |  🚶 Dist. session : " + "  /  ".join(parts)

        # Bien-être : état actuel de chaque tech (dernière valeur connue)
        bienetre_txt = ""
        if bienetre_data:
            from core.technician import TechnicianState
            _tmp = TechnicianState(0, 0)
            parts_be = []
            for nom, jours_be in bienetre_data.items():
                if jours_be:
                    last_val = jours_be[max(jours_be.keys())]
                    _tmp.mecontentement = last_val
                    emoji_be, _, label_be = _tmp.etat_bien_etre()
                    parts_be.append(f"{nom}: {emoji_be} {label_be} ({last_val:.2f})")
            if parts_be:
                bienetre_txt = "  |  🫀 " + "  /  ".join(parts_be)

        self.lbl_info.config(
            text=(f"Durée sim : {_fmt_duree(t_total)}  |  "
                  f"Tubes générés : {total_tubes}  |  "
                  f"File la plus longue : {goulot_nom} (moy {goulot_val:.1f})  |  "
                  f"Machine la plus occupée : {busiest_nom} ({busiest_val:.0f} %)"
                  f"{transit_txt}  |  "
                  f"⚠ Rejets: {nb_rejetes}  Dégradés: {nb_degrades}  Pannes: {nb_pannes}"
                  f"{dispo_txt}"
                  f"{dist_session_txt}"
                  f"{bienetre_txt}")
        )

    # ------------------------------------------------------------------
    def lancer_simulation_rapide(self):
        """Déclenche une simulation headless et affiche les graphiques à la fin."""
        if not self.tab_live:
            self.lbl_fast_status.config(text="Référence simulation manquante.")
            return
        if getattr(self.tab_live, "running", False):
            self.lbl_fast_status.config(text="⚠ Simulation LIVE déjà en cours — arrêtez-la d'abord.")
            return

        try:
            duree = float(self.ent_duree.get())
        except ValueError:
            self.lbl_fast_status.config(text="Durée invalide.")
            return

        self.btn_fast.config(state="disabled")
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
        self.lbl_fast_status.config(text="✅ Terminé — graphiques mis à jour")
        self.btn_fast.config(state="normal")
        self.refresh()

    # ------------------------------------------------------------------
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
        self.lbl_info.config(text="Historique effacé.")
