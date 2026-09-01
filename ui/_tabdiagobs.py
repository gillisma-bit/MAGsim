"""Mixin _TabDiagObs — extrait de ui/tab_diagnostic.py.
"""
import tkinter as tk
from tkinter import ttk
import ui.theme as theme


class _TabDiagObs:
    """Mixin : ne pas instancier directement."""

    def _obs_depuis_simulation(self, hist, machines, techniciens):
        """Génère les observations basées sur stats_history après simulation."""
        times = list(hist["time"])

        t_total = times[-1]   # durée totale en minutes SimPy
        JOUR = 1440.0
        nb_jours = max(1, t_total / JOUR)

        def fmt_duree(m):
            m = int(round(m))
            if m >= 60:
                return f"{m // 60}h {m % 60:02d}min"
            return f"{m} min"

        # ── D1. Temps de transit ──────────────────────────────────────────────
        transit_roll = hist.get("transit_time_rolling", [])
        valeurs_transit = [v for v in transit_roll if v is not None]
        if valeurs_transit:
            transit_moyen = sum(valeurs_transit) / len(valeurs_transit)
            transit_fin   = valeurs_transit[-1]
            tendance = ""
            if len(valeurs_transit) > 10:
                debut = sum(valeurs_transit[:len(valeurs_transit)//4]) / max(1, len(valeurs_transit)//4)
                fin   = sum(valeurs_transit[-len(valeurs_transit)//4:]) / max(1, len(valeurs_transit)//4)
                if fin > debut * 1.20:
                    tendance = "\n⚠ Le transit s'allonge : les files s'accumulent !"
                elif fin < debut * 0.80:
                    tendance = "\n✅ Le transit s'améliore en cours de simulation."

            niveau_transit = "ok"
            if transit_fin > 240:
                niveau_transit = "error"
            elif transit_fin > 90:
                niveau_transit = "warn"

            self._obs_card(niveau_transit, "Temps de traitement des échantillons",
                           f"• Temps de transit moyen   : {fmt_duree(transit_moyen)}\n"
                           f"• Transit fin de simulation : {fmt_duree(transit_fin)}\n"
                           f"• Durée de simulation       : {fmt_duree(t_total)}"
                           + tendance)

        # ── D2. File d'entrée ─────────────────────────────────────────────────
        entry_data = hist.get("entry", [])
        if entry_data:
            max_entree = max(entry_data)
            moy_entree = sum(entry_data) / len(entry_data)
            niveau_entree = "ok"
            conseil_entree = ""
            seuil_alerte = 20
            if self.tab_live:
                personnel = self.config_manager.data.get("personnel", {})
                seuil_alerte = personnel.get("seuil_accumulation_alerte", 20)

            if max_entree > seuil_alerte * 2:
                niveau_entree = "error"
                conseil_entree = (f"\n→ La file d'entrée a atteint {max_entree} tubes !\n"
                                  f"   Ajoutez un technicien ou réduisez la fréquence\n"
                                  f"   d'arrivée des échantillons.")
            elif max_entree > seuil_alerte:
                niveau_entree = "warn"
                conseil_entree = (f"\n→ Pic à {max_entree} tubes en attente à l'entrée.\n"
                                  f"   Seuil d'alerte configuré : {seuil_alerte} tubes.")

            self._obs_card(niveau_entree, "Accumulation à l'entrée",
                           f"• Maximum observé : {max_entree} tubes\n"
                           f"• Moyenne         : {moy_entree:.1f} tubes"
                           + conseil_entree)

        # ── D3. Occupation machines ───────────────────────────────────────────
        busy_data   = hist.get("busy", {})
        queues_data = hist.get("queues", {})
        machines_surchargees = []
        machines_sous_utilisees = []
        for nom, raw in busy_data.items():
            if not raw:
                continue
            pct = sum(raw) / len(raw) * 100
            if pct > 85:
                machines_surchargees.append((nom, pct))
            elif pct < 20:
                machines_sous_utilisees.append((nom, pct))

        if machines_surchargees:
            detail = "\n".join(f"• {n} : {p:.0f}% d'occupation" for n, p in machines_surchargees)
            self._obs_card("warn", "Machines très chargées (> 85 %)",
                           detail + "\n→ Considérez une machine supplémentaire\n   ou une révision des protocoles.")

        if machines_sous_utilisees:
            detail = "\n".join(f"• {n} : {p:.0f}% d'occupation" for n, p in machines_sous_utilisees)
            self._obs_card("info", "Machines sous-utilisées (< 20 %)",
                           detail + "\n→ Ces ressources pourraient être mutualisées.")

        # ── D4. Bien-être des techniciens ─────────────────────────────────────
        bienetre_data = hist.get("bienetre", {})
        if bienetre_data:
            for nom_tech, jours_be in bienetre_data.items():
                if not jours_be:
                    continue
                jours_tri = sorted(jours_be.items())
                dernier_jour, derniere_val = jours_tri[-1]
                nb_jours_surcharge = sum(
                    1 for _, v in jours_tri if v > 0.40
                )

                # Trouver l'état emoji/label
                niveau_be, label_be = self._niveau_bienetre(derniere_val)

                conseil_be = ""
                if derniere_val > 0.60:
                    risque_approx = min(99, int(derniere_val * 35 * (1 + 0.15 * nb_jours_surcharge)))
                    conseil_be = (f"\n→ Risque d'arrêt de travail estimé : ~{risque_approx}%/jour.\n"
                                  f"   Envisagez d'ajouter un technicien\n"
                                  f"   ou de réduire la charge de travail.")
                elif derniere_val > 0.40:
                    conseil_be = "\n→ Stress naissant. Surveillez l'évolution\n   sur les prochains jours simulés."

                if len(jours_tri) > 1:
                    evolution = ""
                    val_debut = jours_tri[0][1]
                    taux_montee = (derniere_val - val_debut) / max(1, len(jours_tri) - 1)
                    if taux_montee > 0.05:
                        evolution = (f"\n   En {len(jours_tri)} jours : {val_debut:.2f} → {derniere_val:.2f} "
                                     f"(+{taux_montee*100:.1f}%/jour) !")
                    elif taux_montee > 0:
                        evolution = f"\n   Légère hausse sur {len(jours_tri)} jours."
                    else:
                        evolution = f"\n   Stable ou en amélioration sur {len(jours_tri)} jours."
                else:
                    evolution = ""

                self._obs_card(niveau_be, f"Bien-être — {nom_tech}",
                               f"• État actuel          : {label_be} ({derniere_val:.2f})\n"
                               f"• Jours de stress (>0.4) : {nb_jours_surcharge}"
                               + evolution + conseil_be)
        else:
            # Estimation statique depuis la config
            for nom_t, m_t in techniciens:
                seuil = float(m_t.get("seuil_charge_fatigue", 0.70))
                cap = int(m_t.get("capacite_max_tubes", 10))
                nom_aff = m_t.get("nom") or nom_t
                self._obs_card("info", f"Technicien — {nom_aff}",
                               f"• Seuil de surcharge configuré : {int(seuil*100)}%\n"
                               f"• Capacité max par trajet       : {cap} tubes\n"
                               "  (Lancez une simulation pour voir\n"
                               "   l'évolution du bien-être)")

        # ── D5. Erreurs ───────────────────────────────────────────────────────
        rejetes  = getattr(self.tab_live, "tubes_rejetes", 0)
        degrades = getattr(self.tab_live, "tubes_degrades", 0)
        total    = getattr(self.tab_live, "stats_tubes_total", 1) or 1

        if rejetes > 0 or degrades > 0:
            pct_err = (rejetes + degrades) / total * 100
            niveau_err = "warn" if pct_err < 5 else "error"
            conseil_err = ""
            if pct_err > 5:
                conseil_err = ("\n→ Taux d'erreur élevé. Vérifiez :\n"
                               "   - Expérience et charge des techniciens\n"
                               "   - Délai de dégradation des tubes\n"
                               "   - Pannes machines fréquentes")
            self._obs_card(niveau_err, "Qualité des analyses",
                           f"• Tubes rejetés   : {rejetes} ({rejetes/total*100:.1f}%)\n"
                           f"• Tubes dégradés  : {degrades} ({degrades/total*100:.1f}%)\n"
                           f"• Taux total      : {pct_err:.1f}%"
                           + conseil_err)
        else:
            self._obs_card("ok", "Qualité des analyses",
                           "Aucun rejet ni dégradation enregistré\npendant la simulation.")

        # ── D6. Pannes ────────────────────────────────────────────────────────
        pannes = hist.get("pannes", {})
        total_pannes = sum(len(v) for v in pannes.values())
        if total_pannes > 0:
            detail = "\n".join(f"• {n} : {len(v)} panne(s)" for n, v in pannes.items() if v)
            self._obs_card("warn", f"Pannes durant la simulation ({total_pannes} au total)",
                           detail + "\n→ Consultez les paramètres TMEP/TMR\n   pour chaque machine concernée.")

    @staticmethod
    def _niveau_bienetre(val):
        """Retourne (niveau_carte, label) selon le mécontentement."""
        if val < 0.20:
            return "ok",    "Satisfait 😊"
        if val < 0.40:
            return "info",  "Neutre 😐"
        if val < 0.60:
            return "warn",  "Stressé 😟"
        if val < 0.80:
            return "error", "Épuisé 😠"
        return "error",     "Burn-out 🤢"
