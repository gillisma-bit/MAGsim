"""Mixin _TabStatsRefresh — extrait de tab_stats.py.

Ces méthodes utilisent `self.xxx` défini dans TabStats.__init__.
"""
import tkinter as tk
from tkinter import ttk
import ui.theme as theme
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.ticker import FuncFormatter
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

class _TabStatsRefresh:
    """Mixin : ne pas instancier directement."""

    def refresh(self):
        if not HAS_MATPLOTLIB:
            return
        if not self.tab_live:
            for w in self._resume_inner.winfo_children():
                w.destroy()
            tk.Label(self._resume_inner,
                     text="Référence à la simulation\nmanquante.",
                     font=theme.FONT_NOTE + ("italic",), bg="#f8f9fa", fg="#c0392b",
                     justify="center", pady=20).pack()
            return

        hist = getattr(self.tab_live, "stats_history", None)
        if not hist or not hist.get("time"):
            for w in self._resume_inner.winfo_children():
                w.destroy()
            tk.Label(self._resume_inner,
                     text="Aucune donnée —\ndémarrez une simulation\net attendez quelques secondes.",
                     font=theme.FONT_NOTE + ("italic",), bg="#f8f9fa", fg="#999",
                     justify="center", pady=20).pack()
            return

        times = list(hist["time"])
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
        show_tat_urgents = self.show_tat_urgents.get()
        show_errors    = self.show_errors.get()
        distances      = hist.get("distances_tech", {})
        bienetre_data  = hist.get("bienetre", {})
        has_bienetre   = bool(bienetre_data and any(bool(v) for v in bienetre_data.values()))
        show_bienetre  = self.show_bienetre.get() and has_bienetre
        arrivees_data          = hist.get("arrivees_par_heure", {})
        arrivees_par_service   = hist.get("arrivees_par_heure_par_service", {})
        show_arrivees          = self.show_arrivees.get() and bool(arrivees_data)

        # Liste ordonnée des graphiques actifs → index subplot dynamique
        active = [show_queues, show_output, show_occup, show_transit, show_tat_urgents, show_errors, show_bienetre, show_arrivees]
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
            idx = _plot_counter[0]
            # Si c'est le dernier graphique ET qu'il tombe seul sur une rangée impaire
            # → le faire occuper toute la largeur (colspan=2)
            if ncols == 2 and n_plots % 2 == 1 and idx == n_plots:
                ax = self.fig.add_subplot(nrows, 1, nrows)
            else:
                ax = self.fig.add_subplot(nrows, ncols, idx)
            return ax

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

            entry_data = list(hist.get("entry", []))
            if entry_data:
                ax1.plot(times[:len(entry_data)], entry_data,
                         label="ENTRÉE (non pris)", color="#2c3e50",
                         linewidth=2, linestyle="--", alpha=0.85)
            for i, nom in enumerate(noms):
                data = list(hist["queues"].get(nom, []))
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
                data = list(hist["output"].get(nom, []))
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
                raw = list(hist["busy"].get(nom, []))
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
        transit_avg     = list(hist.get("transit_time_avg", []))
        transit_roll    = list(hist.get("transit_time_rolling", []))
        transit_pending = list(hist.get("transit_time_pending_max", []))

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
            ax4.set_ylabel("Durée réelle (min)")
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
                        label = (f"[arret] {ev['nom']}"
                                 if ev["nom"] not in techs_deja_legendes_debut else "")
                        ax4.axvline(x=ev_t, color=clr, linewidth=1.8,
                                    linestyle="--", alpha=0.80, label=label or "_nolegend_")
                        ax4.annotate(
                            f"arret:{ev['nom']}",
                            xy=(ev_t, 0), xycoords=("data", "axes fraction"),
                            xytext=(2, 4), textcoords="offset points",
                            fontsize=7.5, color=clr, rotation=90,
                            va="bottom", ha="left",
                        )
                        techs_deja_legendes_debut.add(ev["nom"])
                    else:  # retour
                        label = (f"[retour] {ev['nom']}"
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

        # ── Graphique TAT moyen normal vs urgent ───────────────────────
        tat_normal_roll = list(hist.get("tat_normal_rolling", []))
        tat_urgent_roll = list(hist.get("tat_urgent_rolling", []))

        if show_tat_urgents:
            ax_tat = _next_ax()
            ax_tat.set_facecolor("#ffffff")
            ax_tat.set_title("TAT moyen — tubes normaux vs tubes urgents (glissante 20 derniers)",
                             fontsize=11, fontweight="bold", pad=8)
            ax_tat.set_ylabel("Durée réelle (min)")
            ax_tat.set_xlabel("Temps écoulé")
            ax_tat.xaxis.set_major_formatter(x_fmt)
            ax_tat.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt_duree(v)))
            ax_tat.grid(True, alpha=0.3, linestyle="--")

            has_normal = any(v is not None for v in tat_normal_roll)
            has_urgent = any(v is not None for v in tat_urgent_roll)

            if has_normal:
                t_n, v_n = _filter_none(times[:len(tat_normal_roll)], tat_normal_roll)
                ax_tat.plot(list(t_n), list(v_n),
                            color="#3498db", linewidth=2.5, alpha=0.9,
                            label="Tubes normaux")
                last_n = next((v for v in reversed(tat_normal_roll) if v is not None), None)
                if last_n is not None:
                    ax_tat.axhline(y=last_n, color="#3498db", linestyle=":",
                                   alpha=0.4, linewidth=1.2)
                    ax_tat.text(times[-1] if times else 0, last_n,
                                f"  {_fmt_duree(last_n)}",
                                va="center", fontsize=9, color="#3498db")

            if has_urgent:
                t_u, v_u = _filter_none(times[:len(tat_urgent_roll)], tat_urgent_roll)
                ax_tat.plot(list(t_u), list(v_u),
                            color="#e74c3c", linewidth=2.5, alpha=0.9,
                            linestyle="-", label="Tubes urgents")
                last_u = next((v for v in reversed(tat_urgent_roll) if v is not None), None)
                if last_u is not None:
                    ax_tat.axhline(y=last_u, color="#e74c3c", linestyle=":",
                                   alpha=0.4, linewidth=1.2)
                    ax_tat.text(times[-1] if times else 0, last_u,
                                f"  {_fmt_duree(last_u)}",
                                va="center", fontsize=9, color="#e74c3c")

            if not has_normal and not has_urgent:
                ax_tat.text(0.5, 0.5,
                            "En attente — aucun tube n'a encore atteint la SORTIE.",
                            ha="center", va="center", transform=ax_tat.transAxes,
                            fontsize=10, color="#888", style="italic")
            ax_tat.legend(loc="upper right", fontsize=9, framealpha=0.75)

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

            rejetes_data  = list(hist.get("rejetes", []))
            degrades_data = list(hist.get("degrades", []))
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

            if arrivees_par_service:
                # Barres empilées par service
                services = sorted({svc
                                   for hd in arrivees_par_service.values()
                                   for svc in hd})
                PALETTE = [
                    "#3498db", "#e67e22", "#2ecc71", "#9b59b6",
                    "#e74c3c", "#1abc9c", "#f39c12", "#34495e",
                ]
                cumul = [0] * len(heures)
                for i, svc in enumerate(services):
                    vals = [arrivees_par_service.get(h, {}).get(svc, 0) for h in heures]
                    couleur = PALETTE[i % len(PALETTE)]
                    label = svc.replace("_", " ")
                    ax8.bar(heures, vals, bottom=cumul,
                            color=couleur, alpha=0.88,
                            edgecolor="white", width=0.7, label=label)
                    cumul = [c + v for c, v in zip(cumul, vals)]
                # Total au sommet de chaque barre
                for h, tot in zip(heures, cumul):
                    if tot > 0:
                        ax8.text(h, tot + 0.3, str(tot),
                                 ha="center", va="bottom",
                                 fontsize=8, color="#333333")
                ax8.legend(fontsize=8, loc="upper left",
                           framealpha=0.85, ncol=2)
            else:
                # Fallback : barre unique (données sans décomposition par service)
                valeurs = [arrivees_data[h] for h in heures]
                bars = ax8.bar(heures, valeurs, color="#3498db", alpha=0.85,
                               edgecolor="white", width=0.7)
                for bar, v in zip(bars, valeurs):
                    ax8.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                             str(v), ha="center", va="bottom",
                             fontsize=8, color="#333333")

            ax8.set_xticks(heures)
            ax8.set_xticklabels([f"{h:02d}h" for h in heures], rotation=45, ha="right")

        self.fig.tight_layout(pad=1.8, h_pad=2.5, w_pad=2.0)
        self.canvas_mpl.draw()

        # ── Panneau résumé (colonne droite) ────────────────────────────
        self._update_panneau_resume(hist, times, noms, machines, distances, bienetre_data, _fmt_duree)

        # ── Actualiser le contexte de l'assistant IA intégré ──────────
        self._ia_actualiser_contexte(hist)
