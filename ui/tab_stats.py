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

        self.show_bienetre = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Bien-être techniciens",
                        variable=self.show_bienetre,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_arrivees = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Arrivées / heure",
                        variable=self.show_arrivees,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        # --- Barre de simulation accélérée ---
        fast = ttk.LabelFrame(self.parent, text=" ⚡ Simulation accélérée (sans animation) ")
        fast.pack(fill="x", padx=12, pady=(2, 4))

        ttk.Label(fast, text="Durée (jours) :").pack(side=tk.LEFT, padx=(8, 2), pady=4)
        self.ent_duree = ttk.Entry(fast, width=6)
        self.ent_duree.insert(0, "2")
        self.ent_duree.pack(side=tk.LEFT, padx=2)

        ttk.Label(fast, text="  ← ex : 0.5 = demi-journée  |  1 = 1 jour (1440 min)  |  7 = semaine",
                  font=("Segoe UI", 9), foreground="#777").pack(side=tk.LEFT, padx=4)

        self.btn_fast = ttk.Button(fast, text="▶ Lancer",
                                   command=self.lancer_simulation_rapide)
        self.btn_fast.pack(side=tk.LEFT, padx=10, pady=4)

        self.progress = ttk.Progressbar(fast, mode="determinate", length=200)
        self.progress.pack(side=tk.LEFT, padx=8, pady=4)

        self.lbl_fast_status = ttk.Label(fast, text="", font=("Segoe UI", 9), foreground="#2c3e50")
        self.lbl_fast_status.pack(side=tk.LEFT, padx=4)

        # --- Zone principale : graphiques (gauche) + panneau résumé (droite) ---
        main_area = tk.Frame(self.parent)
        main_area.pack(expand=True, fill="both", padx=4, pady=4)
        main_area.columnconfigure(0, weight=1)
        main_area.columnconfigure(1, weight=0)
        main_area.rowconfigure(0, weight=1)

        # ── Colonne gauche : matplotlib ───────────────────────────────────────
        container = tk.Frame(main_area)
        container.grid(row=0, column=0, sticky="nsew")

        # La taille sera recalculée à chaque refresh() selon le nombre de graphiques actifs
        self.fig = Figure(figsize=(12, 7), dpi=96, facecolor="#f4f6f9")
        self.canvas_mpl = FigureCanvasTkAgg(self.fig, master=container)

        toolbar = NavigationToolbar2Tk(self.canvas_mpl, container)
        toolbar.update()
        self.canvas_mpl.get_tk_widget().pack(expand=True, fill="both")

        # ── Séparateur ────────────────────────────────────────────────────────
        tk.Frame(main_area, bg="#cccccc", width=1).grid(row=0, column=1, sticky="ns")

        # ── Colonne droite : panneau résumé ───────────────────────────────────
        self._resume_frame = tk.Frame(main_area, bg="#f8f9fa", width=260)
        self._resume_frame.grid(row=0, column=2, sticky="nsew")
        self._resume_frame.grid_propagate(False)   # largeur fixe
        main_area.columnconfigure(2, weight=0)

        tk.Label(self._resume_frame,
                 text="📊  Indicateurs clés",
                 font=("Segoe UI", 11, "bold"),
                 bg="#f8f9fa", fg="#2c3e50",
                 anchor="w", padx=12, pady=8).pack(fill="x")
        tk.Frame(self._resume_frame, bg="#dde1e7", height=1).pack(fill="x")

        # Canvas scrollable pour les cartes
        self._resume_canvas = tk.Canvas(self._resume_frame, bg="#f8f9fa",
                                        highlightthickness=0, width=258)
        sb_res = ttk.Scrollbar(self._resume_frame, orient="vertical",
                               command=self._resume_canvas.yview)
        self._resume_canvas.configure(yscrollcommand=sb_res.set)
        sb_res.pack(side=tk.RIGHT, fill="y")
        self._resume_canvas.pack(side=tk.LEFT, fill="both", expand=True)

        self._resume_inner = tk.Frame(self._resume_canvas, bg="#f8f9fa")
        self._resume_win = self._resume_canvas.create_window(
            (0, 0), window=self._resume_inner, anchor="nw")

        self._resume_inner.bind("<Configure>",
            lambda _: self._resume_canvas.configure(
                scrollregion=self._resume_canvas.bbox("all")))
        self._resume_canvas.bind("<Configure>",
            lambda e: self._resume_canvas.itemconfig(self._resume_win, width=e.width))
        self._resume_canvas.bind("<MouseWheel>",
            lambda e: self._resume_canvas.yview_scroll(-1*(e.delta//120), "units"))

        # Message initial
        self._resume_placeholder = tk.Label(
            self._resume_inner,
            text="Lancez une simulation\npuis cliquez sur\nActualiser.",
            font=("Segoe UI", 9, "italic"), bg="#f8f9fa", fg="#999",
            justify="center", pady=20)
        self._resume_placeholder.pack()

    # ------------------------------------------------------------------
    def refresh(self):
        if not HAS_MATPLOTLIB:
            return
        if not self.tab_live:
            for w in self._resume_inner.winfo_children():
                w.destroy()
            tk.Label(self._resume_inner,
                     text="Référence à la simulation\nmanquante.",
                     font=("Segoe UI", 9, "italic"), bg="#f8f9fa", fg="#c0392b",
                     justify="center", pady=20).pack()
            return

        hist = getattr(self.tab_live, "stats_history", None)
        if not hist or not hist.get("time"):
            for w in self._resume_inner.winfo_children():
                w.destroy()
            tk.Label(self._resume_inner,
                     text="Aucune donnée —\ndémarrez une simulation\net attendez quelques secondes.",
                     font=("Segoe UI", 9, "italic"), bg="#f8f9fa", fg="#999",
                     justify="center", pady=20).pack()
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
        bienetre_data  = hist.get("bienetre", {})
        has_bienetre   = bool(bienetre_data and any(bool(v) for v in bienetre_data.values()))
        show_bienetre  = self.show_bienetre.get() and has_bienetre
        arrivees_data  = hist.get("arrivees_par_heure", {})
        show_arrivees  = self.show_arrivees.get() and bool(arrivees_data)

        # Liste ordonnée des graphiques actifs → index subplot dynamique
        active = [show_queues, show_output, show_occup, show_transit, show_errors, show_bienetre, show_arrivees]
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
        transit_avg     = hist.get("transit_time_avg", [])
        transit_roll    = hist.get("transit_time_rolling", [])
        transit_pending = hist.get("transit_time_pending_max", [])

        def _filter_none(t_list, v_list):
            pairs = [(t, v) for t, v in zip(t_list, v_list) if v is not None]
            if not pairs:
                return [], []
            return zip(*pairs)

        if show_transit:
            ax4 = _next_ax()
            ax4.set_facecolor("#ffffff")
            ax4.set_title("Temps de transit — tubes sortis + tubes en attente + congés maladie",
                          fontsize=11, fontweight="bold", pad=8)
            ax4.set_ylabel("Durée (min)")
            ax4.set_xlabel("Temps écoulé")
            ax4.xaxis.set_major_formatter(x_fmt)
            ax4.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt_duree(v)))
            ax4.grid(True, alpha=0.3, linestyle="--")

            has_data = any(v is not None for v in transit_avg)
            has_pending = any(v is not None for v in transit_pending)
            if has_data or has_pending:
                if has_data:
                    t_avg, v_avg = _filter_none(times[:len(transit_avg)], transit_avg)
                    t_roll, v_roll = _filter_none(times[:len(transit_roll)], transit_roll)
                    ax4.plot(list(t_avg), list(v_avg),
                             color="#8e44ad", linewidth=1.5, alpha=0.5,
                             linestyle="--", label="Moyenne cumulative (sortis)")
                    ax4.plot(list(t_roll), list(v_roll),
                             color="#8e44ad", linewidth=2.5, alpha=0.95,
                             label="Glissante 20 derniers (sortis)")
                    last_roll = next((v for v in reversed(transit_roll) if v is not None), None)
                    if last_roll is not None:
                        ax4.axhline(y=last_roll, color="#8e44ad", linestyle=":",
                                    alpha=0.45, linewidth=1.2)
                        ax4.text(times[-1] if times else 0, last_roll,
                                 f"  {_fmt_duree(last_roll)}",
                                 va="center", fontsize=9, color="#8e44ad")
                if has_pending:
                    t_pend, v_pend = _filter_none(times[:len(transit_pending)], transit_pending)
                    ax4.plot(list(t_pend), list(v_pend),
                             color="#e74c3c", linewidth=2.0, alpha=0.85,
                             linestyle="-", label="Âge max tube en attente ⚠")
                    last_pend = next((v for v in reversed(transit_pending) if v is not None), None)
                    if last_pend is not None:
                        ax4.text(times[-1] if times else 0, last_pend,
                                 f"  {_fmt_duree(last_pend)}",
                                 va="center", fontsize=9, color="#e74c3c")

            # ── Marqueurs congés maladie ──────────────────────────────────────
            _PALETTE_SICK = [
                "#e67e22", "#27ae60", "#2980b9", "#8e44ad",
                "#16a085", "#d35400", "#c0392b", "#7f8c8d",
            ]
            events_maladie = hist.get("events_arret_maladie", [])
            if events_maladie:
                # Associer une couleur stable par technicien
                techs_maladie = list(dict.fromkeys(e["nom"] for e in events_maladie))
                couleur_par_tech = {
                    nom: _PALETTE_SICK[i % len(_PALETTE_SICK)]
                    for i, nom in enumerate(techs_maladie)
                }
                # Tracer une ligne verticale par événement + annotation minimale
                techs_deja_legendes_debut  = set()
                techs_deja_legendes_retour = set()
                y_top = ax4.get_ylim()[1] if ax4.get_ylim()[1] > 0 else 1
                for ev in events_maladie:
                    clr  = couleur_par_tech[ev["nom"]]
                    ev_t = ev["t"]
                    if ev["type"] == "debut":
                        label = (f"🏥 début arrêt — {ev['nom']}"
                                 if ev["nom"] not in techs_deja_legendes_debut else "")
                        ax4.axvline(x=ev_t, color=clr, linewidth=1.8,
                                    linestyle="--", alpha=0.80, label=label or "_nolegend_")
                        ax4.annotate(
                            f"🏥{ev['nom']}",
                            xy=(ev_t, 0), xycoords=("data", "axes fraction"),
                            xytext=(2, 4), textcoords="offset points",
                            fontsize=7.5, color=clr, rotation=90,
                            va="bottom", ha="left",
                        )
                        techs_deja_legendes_debut.add(ev["nom"])
                    else:  # retour
                        label = (f"✅ retour — {ev['nom']}"
                                 if ev["nom"] not in techs_deja_legendes_retour else "")
                        ax4.axvline(x=ev_t, color=clr, linewidth=1.4,
                                    linestyle=":", alpha=0.65, label=label or "_nolegend_")
                        ax4.annotate(
                            f"↩{ev['nom']}",
                            xy=(ev_t, 0.5), xycoords=("data", "axes fraction"),
                            xytext=(2, 4), textcoords="offset points",
                            fontsize=7.5, color=clr, rotation=90,
                            va="bottom", ha="left",
                        )
                        techs_deja_legendes_retour.add(ev["nom"])

            if not has_data and not has_pending and not events_maladie:
                ax4.text(0.5, 0.5,
                         "En attente — aucun tube n'a encore atteint la SORTIE.\n"
                         "La courbe apparaîtra dès que les premiers tubes completent leur parcours.",
                         ha="center", va="center", transform=ax4.transAxes,
                         fontsize=10, color="#888", style="italic")
            ax4.legend(loc="upper left", fontsize=8, framealpha=0.75)

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

        # ── Graphique arrivées par heure ───────────────────────────────
        if show_arrivees:
            ax8 = _next_ax()
            ax8.set_facecolor("#ffffff")
            ax8.set_title("Tubes reçus par créneau horaire",
                          fontsize=11, fontweight="bold", pad=8)
            ax8.set_ylabel("Nb tubes")
            ax8.set_xlabel("Heure de la journée")
            ax8.grid(True, alpha=0.3, linestyle="--", axis="y")

            heures = sorted(arrivees_data.keys())
            valeurs = [arrivees_data[h] for h in heures]
            bars = ax8.bar(heures, valeurs, color="#3498db", alpha=0.85,
                           edgecolor="white", width=0.7)
            # Annoter chaque barre
            for bar, v in zip(bars, valeurs):
                ax8.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                         str(v), ha="center", va="bottom",
                         fontsize=8, color="#333333")
            # Étiquettes h00, h01 …
            ax8.set_xticks(heures)
            ax8.set_xticklabels([f"{h:02d}h" for h in heures], rotation=45, ha="right")

        self.fig.tight_layout(pad=1.8, h_pad=2.5, w_pad=2.0)
        self.canvas_mpl.draw()

        # ── Panneau résumé (colonne droite) ────────────────────────────
        self._update_panneau_resume(hist, times, noms, machines, distances, bienetre_data, _fmt_duree)

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

        tk.Label(inner, text=titre, font=("Segoe UI", 9, "bold"),
                 bg=bg, fg=accent, anchor="w").pack(fill="x")

        for ligne in corps_lignes:
            tk.Label(inner, text=ligne, font=("Segoe UI", 9),
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
        transit_avg = hist.get("transit_time_avg", [])
        transit_roll = hist.get("transit_time_rolling", [])
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
        # Vider le panneau résumé
        for w in self._resume_inner.winfo_children():
            w.destroy()
        tk.Label(self._resume_inner,
                 text="Historique effacé.\nLancez une simulation\npuis cliquez sur Actualiser.",
                 font=("Segoe UI", 9, "italic"), bg="#f8f9fa", fg="#999",
                 justify="center", pady=20).pack()
