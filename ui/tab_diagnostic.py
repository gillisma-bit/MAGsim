"""Onglet Diagnostic — validation de la configuration et détection de problèmes.

Vérifie en temps réel :
  • Cohérence des workflows : chaque étape a une machine capable
  • Machines inutilisées : aucun type de tube ne les visite
  • Goulots d'étranglement : file_max potentiellement insuffisante
  • Présence d'une ENTREE et d'une SORTIE
  • Fréquence d'arrivée vs débit des machines

Interface :
  • Colonne gauche  : rapport technique détaillé (texte avec tags couleur)
  • Colonne droite  : observations synthétiques et recommandations issues
                      des données de simulation (stats_history) + config
"""

import tkinter as tk
from tkinter import ttk
import ui.theme as theme


# ── Niveaux de sévérité ──────────────────────────────────────────────────────
INFO    = "info"
WARN    = "warn"
ERROR   = "error"
OK      = "ok"

_ICONS = {OK: "✅", INFO: "ℹ️", WARN: "⚠️", ERROR: "❌"}
_TAGS  = {OK: "ok", INFO: "info", WARN: "warn", ERROR: "error"}


class TabDiagnostic:
    def __init__(self, parent, config_manager, tab_live_ref=None):
        self.parent = parent
        self.config_manager = config_manager
        self.tab_live = tab_live_ref   # référence à TabLive pour lire stats_history
        self._build_ui()

    def set_tab_live(self, tab_live):
        self.tab_live = tab_live

    # ── Construction de l'interface ──────────────────────────────────────────

    def _build_ui(self):
        # ── Barre supérieure ──────────────────────────────────────────────────
        top = ttk.Frame(self.parent, padding=(12, 8))
        top.pack(fill="x")

        ttk.Label(top, text="🔍 Diagnostic de configuration",
                  font=theme.FONT_TITLE).pack(side=tk.LEFT)

        ttk.Button(top, text="↻  Actualiser", command=self.lancer_diagnostic,
                   padding=(10, 4)).pack(side=tk.RIGHT)

        # ── Zone principale : 2 colonnes (grid, sans PanedWindow) ────────────
        cols = tk.Frame(self.parent, bg="#1e1e2e")
        cols.pack(fill="both", expand=True, padx=6, pady=(0, 2))
        cols.columnconfigure(0, weight=3)   # rapport : ~60 %
        cols.columnconfigure(1, weight=0)   # séparateur
        cols.columnconfigure(2, weight=2)   # observations : ~40 %
        cols.rowconfigure(0, weight=1)

        # ── Colonne gauche : rapport technique ───────────────────────────────
        frame_rapport = tk.Frame(cols, bg="#1e1e2e")
        frame_rapport.grid(row=0, column=0, sticky="nsew")
        frame_rapport.rowconfigure(0, weight=1)
        frame_rapport.columnconfigure(0, weight=1)

        self.text = tk.Text(
            frame_rapport,
            font=theme.FONT_MONO_S,
            bg="#1e1e2e", fg="#cdd6f4",
            relief="flat", bd=0,
            wrap="word",
            state="disabled",
            padx=10, pady=10,
        )
        sb_l = ttk.Scrollbar(frame_rapport, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb_l.set)
        sb_l.grid(row=0, column=1, sticky="ns")
        self.text.grid(row=0, column=0, sticky="nsew")

        self.text.tag_config("ok",      foreground="#a6e3a1")
        self.text.tag_config("info",    foreground="#89b4fa")
        self.text.tag_config("warn",    foreground="#f9e2af")
        self.text.tag_config("error",   foreground="#f38ba8")
        self.text.tag_config("section", foreground="#cba6f7", font=theme.FONT_MONO_S + ("bold",))
        self.text.tag_config("dim",     foreground="#585b70")

        # Séparateur vertical
        tk.Frame(cols, bg="#313145", width=2).grid(row=0, column=1, sticky="ns", padx=2)

        # ── Colonne droite : observations synthétiques ───────────────────────
        frame_obs = tk.Frame(cols, bg="#13131f")
        frame_obs.grid(row=0, column=2, sticky="nsew")
        frame_obs.rowconfigure(1, weight=1)
        frame_obs.columnconfigure(0, weight=1)

        obs_title = tk.Label(
            frame_obs,
            text="📋  Observations & recommandations",
            font=theme.FONT_SECTION,
            bg="#13131f", fg="#cba6f7",
            anchor="w", padx=14, pady=10
        )
        obs_title.grid(row=0, column=0, sticky="ew")

        tk.Frame(frame_obs, bg="#313145", height=1).grid(row=0, column=0,
                                                          sticky="ews", pady=(40, 0))

        # Scrollable canvas pour les cartes d'observations
        obs_scroll_outer = tk.Frame(frame_obs, bg="#13131f")
        obs_scroll_outer.grid(row=1, column=0, sticky="nsew")
        obs_scroll_outer.rowconfigure(0, weight=1)
        obs_scroll_outer.columnconfigure(0, weight=1)

        self._obs_canvas = tk.Canvas(obs_scroll_outer, bg="#13131f",
                                     highlightthickness=0)
        sb_r = ttk.Scrollbar(obs_scroll_outer, orient="vertical",
                              command=self._obs_canvas.yview)
        self._obs_canvas.configure(yscrollcommand=sb_r.set)
        sb_r.grid(row=0, column=1, sticky="ns")
        self._obs_canvas.grid(row=0, column=0, sticky="nsew")

        self._obs_inner = tk.Frame(self._obs_canvas, bg="#13131f")
        self._obs_window = self._obs_canvas.create_window(
            (0, 0), window=self._obs_inner, anchor="nw")

        self._obs_inner.bind("<Configure>", self._on_obs_resize)
        self._obs_canvas.bind("<Configure>", self._on_canvas_resize)

        # Scroll molette
        self._obs_canvas.bind("<MouseWheel>",
            lambda e: self._obs_canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # ── Barre de résumé ───────────────────────────────────────────────────
        self.lbl_resume = ttk.Label(self.parent, text="", font=("Segoe UI", 10),
                                    anchor="w", padding=(14, 4))
        self.lbl_resume.pack(fill="x")

        # Premier lancement
        self.lancer_diagnostic()

    def _on_obs_resize(self, _event=None):
        self._obs_canvas.configure(
            scrollregion=self._obs_canvas.bbox("all"))

    def _on_canvas_resize(self, event):
        self._obs_canvas.itemconfig(self._obs_window, width=event.width)

    # ── Cartes d'observations ────────────────────────────────────────────────

    def _clear_obs(self):
        for w in self._obs_inner.winfo_children():
            w.destroy()

    _CARD_COLORS = {
        "ok":    ("#1a3a2a", "#2ecc71", "✅"),
        "info":  ("#1a1f3a", "#89b4fa", "ℹ️"),
        "warn":  ("#3a2a00", "#f9e2af", "⚠️"),
        "error": ("#3a1010", "#f38ba8", "❌"),
        "tip":   ("#1e2a3a", "#74c7ec", "💡"),
    }

    def _obs_card(self, niveau, titre, corps):
        """Ajoute une carte dans le panneau d'observations."""
        bg, accent, icon = self._CARD_COLORS.get(niveau, self._CARD_COLORS["info"])

        card = tk.Frame(self._obs_inner, bg=bg,
                        highlightbackground=accent, highlightthickness=1)
        card.pack(fill="x", padx=10, pady=5, ipady=6)

        header = tk.Frame(card, bg=bg)
        header.pack(fill="x", padx=10, pady=(6, 2))

        tk.Label(header, text=f"{icon}  {titre}",
                 font=theme.FONT_LABEL,
                 bg=bg, fg=accent, anchor="w").pack(side=tk.LEFT)

        tk.Label(card, text=corps,
                 font=theme.FONT_BODY,
                 bg=bg, fg="#cdd6f4",
                 anchor="nw", justify="left",
                 wraplength=260, padx=10, pady=(0, 6)).pack(fill="x")

    # ── Écriture dans le widget texte ────────────────────────────────────────

    def _clear(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")

    def _write(self, line, tag="dim"):
        self.text.insert("end", line + "\n", tag)

    def _section(self, title):
        self.text.insert("end", f"\n{'─'*60}\n", "dim")
        self.text.insert("end", f"  {title}\n", "section")
        self.text.insert("end", f"{'─'*60}\n", "dim")

    def _result(self, level, msg):
        icon = _ICONS[level]
        self.text.insert("end", f"  {icon}  {msg}\n", _TAGS[level])

    def _freeze(self):
        self.text.config(state="disabled")

    # ── Diagnostic principal ─────────────────────────────────────────────────

    def lancer_diagnostic(self):
        self._clear()
        self._clear_obs()

        machines     = self.config_manager.get_machines()
        types_tubes  = self.config_manager.get_types_tubes()

        compteurs = {OK: 0, WARN: 0, ERROR: 0, INFO: 0}

        def log(level, msg):
            compteurs[level] += 1
            self._result(level, msg)

        # ── 1. Infrastructure ─────────────────────────────────────────────────
        self._section("1 · Infrastructure (ENTREE / SORTIE)")

        entrees = [(n, m) for n, m in machines.items() if m.get("type") == "ENTREE"]
        sorties = [(n, m) for n, m in machines.items() if m.get("type") == "SORTIE"]

        if not entrees:
            log(ERROR, "Aucun point ENTREE défini — les tubes ne peuvent pas arriver")
        elif len(entrees) > 1:
            log(WARN,  f"{len(entrees)} points ENTREE ({', '.join(n for n,_ in entrees)}) — seul le premier sera utilisé")
        else:
            log(OK, f"Point ENTREE : {entrees[0][0]}")

        if not sorties:
            log(ERROR, "Aucun point SORTIE défini — les tubes traités ne peuvent pas partir")
        else:
            log(OK, f"Point SORTIE : {sorties[0][0]}")

        techniciens = [(n, m) for n, m in machines.items() if m.get("type") == "TECH_OFFICE"]
        if not techniciens:
            log(WARN, "Aucun technicien configuré — la simulation ne démarrera pas")
        else:
            log(OK, f"{len(techniciens)} technicien(s) : {', '.join(n for n,_ in techniciens)}")

        # ── 2. Workflows des types de tubes ───────────────────────────────────
        self._section("2 · Workflows des types de tubes")

        if not types_tubes:
            log(WARN, "Aucun type de tube défini")
        else:
            etapes_disponibles = set()
            for m in machines.values():
                etapes_disponibles.update(m.get("protocoles", {}).keys())

            for nom_tube, conf in types_tubes.items():
                wf = conf.get("workflow", [])
                if not wf:
                    log(WARN, f"[{nom_tube}] workflow vide — les tubes iront directement en sortie")
                    continue
                etapes_orphelines = [e for e in wf if e not in etapes_disponibles]
                if etapes_orphelines:
                    for e in etapes_orphelines:
                        log(ERROR, f"[{nom_tube}] étape « {e} » sans machine capable — elle sera IGNORÉE")
                else:
                    log(OK, f"[{nom_tube}] workflow OK : {' → '.join(wf)}")

                seen = set()
                for e in wf:
                    if e in seen:
                        log(WARN, f"[{nom_tube}] étape « {e} » présente plusieurs fois dans le workflow")
                    seen.add(e)

        # ── 3. Machines inutilisées ────────────────────────────────────────────
        self._section("3 · Machines inutilisées")

        types_fonctionnels = {"ENTREE", "SORTIE", "TECH_OFFICE"}
        etapes_requises = set()
        for conf in types_tubes.values():
            etapes_requises.update(conf.get("workflow", []))

        for nom_m, m in machines.items():
            if m.get("type") in types_fonctionnels:
                continue
            protocoles_m = set(m.get("protocoles", {}).keys())
            if not protocoles_m:
                log(INFO, f"[{nom_m}] aucun protocole — machine inutilisée")
            elif not protocoles_m & etapes_requises:
                log(WARN, f"[{nom_m}] protocoles ({', '.join(protocoles_m)}) jamais demandés par aucun type de tube")
            else:
                log(OK, f"[{nom_m}] utilisée pour : {', '.join(protocoles_m & etapes_requises)}")

        # ── 4. Goulots d'étranglement ──────────────────────────────────────────
        self._section("4 · Goulots d'étranglement potentiels")

        freq_base = 5.0
        taux_arrivee = 0.0
        lot_moyen = 1.0
        if entrees:
            entree_conf = entrees[0][1]
            freq_base = entree_conf.get("frequence", 5.0)
            if types_tubes:
                tailles = [(c.get("taille_lot_min", 1) + c.get("taille_lot_max", 1)) / 2
                           for c in types_tubes.values()]
                lot_moyen = sum(tailles) / len(tailles)
            taux_arrivee = lot_moyen / freq_base

            self._write(f"  Fréquence d'arrivée configurée : 1 lot toutes les {freq_base} min"
                        f"  (lot moyen ≈ {lot_moyen:.1f} tube(s) → ~{taux_arrivee:.2f} tube/min)", "dim")

        etape_debit = {}
        for nom_m, m in machines.items():
            if m.get("type") in types_fonctionnels:
                continue
            cap = m.get("capacite", 4)
            for etape, proto in m.get("protocoles", {}).items():
                temps = proto.get("temps", 60)
                if temps > 0:
                    debit = cap / temps
                    etape_debit[etape] = etape_debit.get(etape, 0.0) + debit

        goulots_detectes = []
        for etape, debit in etape_debit.items():
            nb_tubes_with_etape = sum(
                1 for c in types_tubes.values() if etape in c.get("workflow", [])
            )
            total_types = max(1, len(types_tubes))
            pct_tubes = nb_tubes_with_etape / total_types
            demande_estimee = taux_arrivee * pct_tubes if entrees else 0.0

            if demande_estimee > 0 and debit < demande_estimee * 0.8:
                log(ERROR, f"Étape « {etape} » : débit max ≈ {debit:.3f} tube/min"
                           f" < demande estimée ≈ {demande_estimee:.3f} tube/min — GOULOT PROBABLE")
                goulots_detectes.append((etape, debit, demande_estimee))
            elif demande_estimee > 0 and debit < demande_estimee * 1.2:
                log(WARN,  f"Étape « {etape} » : marge faible (débit {debit:.3f} vs demande {demande_estimee:.3f} tube/min)")
            elif etape in etapes_requises:
                log(OK,    f"Étape « {etape} » : débit suffisant ({debit:.3f} tube/min)")

        # ── 5. Cohérence des paramètres de chaque machine ─────────────────────
        self._section("5 · Paramètres des machines")

        for nom_m, m in machines.items():
            if m.get("type") in types_fonctionnels:
                continue
            cap = m.get("capacite", 4)
            fm  = m.get("file_max", cap)
            seuil = m.get("seuil", 1)

            if fm < cap:
                log(WARN, f"[{nom_m}] file_max ({fm}) < capacite ({cap}) — un batch complet ne peut jamais se former")
            if seuil > cap:
                log(WARN, f"[{nom_m}] seuil ({seuil}) > capacite ({cap}) — le déclenchement urgent n'aura jamais lieu")
            if cap <= 0:
                log(ERROR, f"[{nom_m}] capacite = {cap} invalide")
            if fm <= 0:
                log(ERROR, f"[{nom_m}] file_max = {fm} invalide")

            tmep = m.get("tmep", 0)
            tmr  = m.get("tmr", 0)
            if tmep and tmr:
                dispo = tmep / (tmep + tmr) * 100
                if dispo < 80:
                    log(WARN, f"[{nom_m}] disponibilité estimée faible : {dispo:.1f}% (TMEP={tmep}min, TMR={tmr}min)")
                else:
                    log(OK,   f"[{nom_m}] disponibilité : {dispo:.1f}%")

        # ── Résumé rapport ────────────────────────────────────────────────────
        self._section("Résumé")
        self._write(
            f"  {compteurs[OK]} ✅  ok   "
            f"| {compteurs[INFO]} ℹ️  info  "
            f"| {compteurs[WARN]} ⚠️  avertissements  "
            f"| {compteurs[ERROR]} ❌  erreurs",
            "dim"
        )
        self._freeze()

        # Barre de résumé colorée
        if compteurs[ERROR]:
            couleur_resume, icone = "#f38ba8", "❌"
        elif compteurs[WARN]:
            couleur_resume, icone = "#f9e2af", "⚠️"
        else:
            couleur_resume, icone = "#a6e3a1", "✅"

        self.lbl_resume.configure(
            text=f"{icone}  {compteurs[ERROR]} erreur(s)   {compteurs[WARN]} avertissement(s)   "
                 f"{compteurs[OK]} contrôle(s) OK   — config : {self.config_manager.data.get('nom_projet', '?')}",
            foreground=couleur_resume,
        )

        # ── Observations synthétiques (colonne droite) ────────────────────────
        self._generer_observations(
            machines, types_tubes, techniciens, entrees, goulots_detectes, compteurs
        )

    # ── Moteur d'observations ────────────────────────────────────────────────

    def _generer_observations(self, machines, types_tubes, techniciens,
                               entrees, goulots_detectes, compteurs):
        """Génère les cartes d'observations à partir de la config et de stats_history."""

        hist = getattr(self.tab_live, "stats_history", None) if self.tab_live else None
        has_sim = bool(hist and hist.get("time"))

        # ── A. Synthèse configuration ─────────────────────────────────────────
        nb_machines_actives = sum(
            1 for m in machines.values()
            if m.get("type") not in {"ENTREE", "SORTIE", "TECH_OFFICE"}
               and any(m.get("protocoles", {}))
        )
        nb_types = len(types_tubes)
        nb_techs = len(techniciens)

        self._obs_card("info", "Configuration générale",
                       f"• {nb_machines_actives} machine(s) active(s)\n"
                       f"• {nb_types} type(s) de tube(s) configuré(s)\n"
                       f"• {nb_techs} technicien(s) dans le labo")

        # ── B. Goulots détectés statiquement ─────────────────────────────────
        if goulots_detectes:
            detail = "\n".join(
                f"• Étape « {e} » : débit {d:.3f} vs demande {dem:.3f} tube/min"
                for e, d, dem in goulots_detectes
            )
            self._obs_card("error", "Goulots d'étranglement critiques",
                           detail + "\n→ Augmentez la capacité ou ajoutez une machine pour ces étapes.")
        elif not goulots_detectes and nb_machines_actives > 0:
            self._obs_card("ok", "Aucun goulot critique détecté",
                           "Le débit théorique des machines est suffisant\npour la fréquence d'arrivée configurée.")

        # ── C. Disponibilité machines ─────────────────────────────────────────
        dispos_faibles = []
        for nom_m, m in machines.items():
            t, r = m.get("tmep", 0), m.get("tmr", 0)
            if t and r:
                d = t / (t + r) * 100
                if d < 80:
                    dispos_faibles.append((nom_m, d))
        if dispos_faibles:
            detail = "\n".join(f"• {n} : {d:.1f}% de disponibilité" for n, d in dispos_faibles)
            self._obs_card("warn", "Machines à faible disponibilité",
                           detail + "\n→ Ces machines tombent souvent en panne. Vérifiez\nla maintenance préventive.")

        # ── D. Observations issues de la simulation ───────────────────────────
        if not has_sim:
            self._obs_card("tip", "Données de simulation",
                           "Lancez une simulation depuis l'onglet LIVE ou\nStats → Simulation accélérée, puis actualisez\npour obtenir des observations dynamiques.")
        else:
            self._obs_depuis_simulation(hist, machines, techniciens)

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

    # ── Construction de l'interface ──────────────────────────────────────────

    def _build_ui(self):
        top = ttk.Frame(self.parent, padding=(12, 8))
        top.pack(fill="x")

        ttk.Label(top, text="🔍 Diagnostic de configuration",
                  font=theme.FONT_TITLE).pack(side=tk.LEFT)

        ttk.Button(top, text="↻  Actualiser", command=self.lancer_diagnostic,
                   padding=(10, 4)).pack(side=tk.RIGHT)

        # Zone de résultats avec scrollbar
        frame_res = ttk.Frame(self.parent, padding=(12, 4))
        frame_res.pack(fill="both", expand=True)

        self.text = tk.Text(
            frame_res,
            font=theme.FONT_MONO_S,
            bg="#1e1e2e", fg="#cdd6f4",
            relief="flat", bd=0,
            wrap="word",
            state="disabled",
            padx=10, pady=10,
        )
        sb = ttk.Scrollbar(frame_res, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill="y")
        self.text.pack(fill="both", expand=True)

        # Couleurs par tag
        self.text.tag_config("ok",      foreground="#a6e3a1")
        self.text.tag_config("info",    foreground="#89b4fa")
        self.text.tag_config("warn",    foreground="#f9e2af")
        self.text.tag_config("error",   foreground="#f38ba8")
        self.text.tag_config("section", foreground="#cba6f7", font=theme.FONT_MONO_S + ("bold",))
        self.text.tag_config("dim",     foreground="#585b70")

        # Barre de résumé en bas
        self.lbl_resume = ttk.Label(self.parent, text="", font=theme.FONT_BODY,
                                    anchor="w", padding=(14, 4))
        self.lbl_resume.pack(fill="x")

        # Premier lancement automatique
        self.lancer_diagnostic()

    # ── Écriture dans le widget texte ────────────────────────────────────────

    def _clear(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")

    def _write(self, line, tag="dim"):
        self.text.insert("end", line + "\n", tag)

    def _section(self, title):
        self.text.insert("end", f"\n{'─'*60}\n", "dim")
        self.text.insert("end", f"  {title}\n", "section")
        self.text.insert("end", f"{'─'*60}\n", "dim")

    def _result(self, level, msg):
        icon = _ICONS[level]
        self.text.insert("end", f"  {icon}  {msg}\n", _TAGS[level])

    def _freeze(self):
        self.text.config(state="disabled")

    # ── Diagnostic principal ─────────────────────────────────────────────────

    def lancer_diagnostic(self):
        self._clear()

        machines     = self.config_manager.get_machines()
        types_tubes  = self.config_manager.get_types_tubes()

        compteurs = {OK: 0, WARN: 0, ERROR: 0, INFO: 0}

        def log(level, msg):
            compteurs[level] += 1
            self._result(level, msg)

        # ── 1. Infrastructure ─────────────────────────────────────────────────
        self._section("1 · Infrastructure (ENTREE / SORTIE)")

        entrees = [(n, m) for n, m in machines.items() if m.get("type") == "ENTREE"]
        sorties = [(n, m) for n, m in machines.items() if m.get("type") == "SORTIE"]

        if not entrees:
            log(ERROR, "Aucun point ENTREE défini — les tubes ne peuvent pas arriver")
        elif len(entrees) > 1:
            log(WARN,  f"{len(entrees)} points ENTREE ({', '.join(n for n,_ in entrees)}) — seul le premier sera utilisé")
        else:
            log(OK, f"Point ENTREE : {entrees[0][0]}")

        if not sorties:
            log(ERROR, "Aucun point SORTIE défini — les tubes traités ne peuvent pas partir")
        else:
            log(OK, f"Point SORTIE : {sorties[0][0]}")

        techniciens = [(n, m) for n, m in machines.items() if m.get("type") == "TECH_OFFICE"]
        if not techniciens:
            log(WARN, "Aucun technicien configuré — la simulation ne démarrera pas")
        else:
            log(OK, f"{len(techniciens)} technicien(s) : {', '.join(n for n,_ in techniciens)}")

        # ── 2. Workflows des types de tubes ───────────────────────────────────
        self._section("2 · Workflows des types de tubes")

        if not types_tubes:
            log(WARN, "Aucun type de tube défini")
        else:
            # Toutes les étapes connues par les machines
            etapes_disponibles = set()
            for m in machines.values():
                etapes_disponibles.update(m.get("protocoles", {}).keys())

            for nom_tube, conf in types_tubes.items():
                wf = conf.get("workflow", [])
                couleur = conf.get("couleur", "#888")
                if not wf:
                    log(WARN, f"[{nom_tube}] workflow vide — les tubes iront directement en sortie")
                    continue
                etapes_orphelines = [e for e in wf if e not in etapes_disponibles]
                if etapes_orphelines:
                    for e in etapes_orphelines:
                        log(ERROR, f"[{nom_tube}] étape « {e} » sans machine capable — elle sera IGNORÉE")
                else:
                    log(OK, f"[{nom_tube}] workflow OK : {' → '.join(wf)}")

                # Détecter les doublons dans le workflow
                seen = set()
                for e in wf:
                    if e in seen:
                        log(WARN, f"[{nom_tube}] étape « {e} » présente plusieurs fois dans le workflow")
                    seen.add(e)

        # ── 3. Machines inutilisées ────────────────────────────────────────────
        self._section("3 · Machines inutilisées")

        types_fonctionnels = {"ENTREE", "SORTIE", "TECH_OFFICE"}
        # Toutes les étapes référencées par n'importe quel type de tube
        etapes_requises = set()
        for conf in types_tubes.values():
            etapes_requises.update(conf.get("workflow", []))

        for nom_m, m in machines.items():
            if m.get("type") in types_fonctionnels:
                continue
            protocoles_m = set(m.get("protocoles", {}).keys())
            if not protocoles_m:
                log(INFO, f"[{nom_m}] aucun protocole — machine inutilisée")
            elif not protocoles_m & etapes_requises:
                log(WARN, f"[{nom_m}] protocoles ({', '.join(protocoles_m)}) jamais demandés par aucun type de tube")
            else:
                log(OK, f"[{nom_m}] utilisée pour : {', '.join(protocoles_m & etapes_requises)}")

        # ── 4. Goulots d'étranglement ──────────────────────────────────────────
        self._section("4 · Goulots d'étranglement potentiels")

        # Taux d'arrivée moyen (tubes/min) estimé depuis ENTREE
        freq_base = 5.0   # défaut si non configuré
        if entrees:
            entree_conf = entrees[0][1]
            freq_base = entrees[0][1].get("frequence", 5.0)
            # Facteur horaire moyen ≈ 1.0 à la louche
            lot_moyen = 1.0
            if types_tubes:
                tailles = [(c.get("taille_lot_min", 1) + c.get("taille_lot_max", 1)) / 2
                           for c in types_tubes.values()]
                lot_moyen = sum(tailles) / len(tailles)
            taux_arrivee = lot_moyen / freq_base  # tubes par minute

            self._write(f"  Fréquence d'arrivée configurée : 1 lot toutes les {freq_base} min"
                        f"  (lot moyen ≈ {lot_moyen:.1f} tube(s) → ~{taux_arrivee:.2f} tube/min)", "dim")

        # Pour chaque étape, estimer combien de tubes/min une machine peut traiter
        etape_debit = {}   # etape → debit_total (tubes/min de toutes les machines capables)
        for nom_m, m in machines.items():
            if m.get("type") in types_fonctionnels:
                continue
            cap = m.get("capacite", 4)
            for etape, proto in m.get("protocoles", {}).items():
                temps = proto.get("temps", 60)      # minutes SimPy
                if temps > 0:
                    # Un batch de `cap` tubes traités en `temps` min
                    debit = cap / temps
                    etape_debit[etape] = etape_debit.get(etape, 0.0) + debit

        # Proportion de tubes nécessitant chaque étape
        for etape, debit in etape_debit.items():
            nb_tubes_with_etape = sum(
                1 for c in types_tubes.values() if etape in c.get("workflow", [])
            )
            total_types = max(1, len(types_tubes))
            pct_tubes = nb_tubes_with_etape / total_types
            demande_estimee = taux_arrivee * pct_tubes if entrees else 0.0

            if demande_estimee > 0 and debit < demande_estimee * 0.8:
                log(ERROR, f"Étape « {etape} » : débit max ≈ {debit:.3f} tube/min"
                           f" < demande estimée ≈ {demande_estimee:.3f} tube/min — GOULOT PROBABLE")
            elif demande_estimee > 0 and debit < demande_estimee * 1.2:
                log(WARN,  f"Étape « {etape} » : marge faible (débit {debit:.3f} vs demande {demande_estimee:.3f} tube/min)")
            elif etape in etapes_requises:
                log(OK,    f"Étape « {etape} » : débit suffisant ({debit:.3f} tube/min)")

        # ── 5. Cohérence des paramètres de chaque machine ─────────────────────
        self._section("5 · Paramètres des machines")

        for nom_m, m in machines.items():
            if m.get("type") in types_fonctionnels:
                continue
            cap = m.get("capacite", 4)
            fm  = m.get("file_max", cap)
            seuil = m.get("seuil", 1)

            if fm < cap:
                log(WARN, f"[{nom_m}] file_max ({fm}) < capacite ({cap}) — un batch complet ne peut jamais se former")
            if seuil > cap:
                log(WARN, f"[{nom_m}] seuil ({seuil}) > capacite ({cap}) — le déclenchement urgent n'aura jamais lieu")
            if cap <= 0:
                log(ERROR, f"[{nom_m}] capacite = {cap} invalide")
            if fm <= 0:
                log(ERROR, f"[{nom_m}] file_max = {fm} invalide")

            # TMEP/TMR → disponibilité
            tmep = m.get("tmep", 0)
            tmr  = m.get("tmr", 0)
            if tmep and tmr:
                dispo = tmep / (tmep + tmr) * 100
                if dispo < 80:
                    log(WARN, f"[{nom_m}] disponibilité estimée faible : {dispo:.1f}% (TMEP={tmep}min, TMR={tmr}min)")
                else:
                    log(OK,   f"[{nom_m}] disponibilité : {dispo:.1f}%")

        # ── Résumé ────────────────────────────────────────────────────────────
        self._section("Résumé")
        total = sum(compteurs.values())
        self._write(
            f"  {compteurs[OK]} ✅  ok   "
            f"| {compteurs[INFO]} ℹ️  info  "
            f"| {compteurs[WARN]} ⚠️  avertissements  "
            f"| {compteurs[ERROR]} ❌  erreurs",
            "dim"
        )

        # ── Conseiller — observations basées sur les faits ────────────────────
        self._section_advisor()

        self._freeze()

        # Barre de résumé colorée
        if compteurs[ERROR]:
            couleur_resume, icone = "#f38ba8", "❌"
        elif compteurs[WARN]:
            couleur_resume, icone = "#f9e2af", "⚠️"
        else:
            couleur_resume, icone = "#a6e3a1", "✅"

        self.lbl_resume.configure(
            text=f"{icone}  {compteurs[ERROR]} erreur(s)   {compteurs[WARN]} avertissement(s)   "
                 f"{compteurs[OK]} contrôle(s) OK   — config : {self.config_manager.data.get('nom_projet', '?')}",
            foreground=couleur_resume,
        )

    # ── Conseiller de simulation ─────────────────────────────────────────────

    def _section_advisor(self):
        """Ajoute la section conseiller au rapport de diagnostic."""
        try:
            from core.sim_advisor import analyser as _analyser
        except ImportError:
            return

        hist     = getattr(self.tab_live, "stats_history", None) if self.tab_live else None
        config   = self.config_manager.data
        insights = _analyser(hist or {}, config)

        _ICONES_ADV = {"ok": "✅", "info": "ℹ️", "tip": "💡", "warn": "⚠️", "error": "❌"}
        _TAGS_ADV   = {"ok": "ok", "info": "info", "tip": "info", "warn": "warn", "error": "error"}

        self._section("6 · Conseiller — patterns & recommandations")

        if not insights:
            if not hist or not hist.get("time"):
                self.text.insert("end",
                    "  💡  Lancez une simulation (onglet Live ou Stats → Simulation accélérée),\n"
                    "      puis actualisez pour obtenir des conseils basés sur les données réelles.\n",
                    "info")
            else:
                self.text.insert("end",
                    "  ✅  Aucun pattern problématique détecté sur cette simulation.\n", "ok")
            return

        for ins in insights:
            icon = _ICONES_ADV.get(ins.niveau, "ℹ️")
            tag  = _TAGS_ADV.get(ins.niveau, "info")

            self.text.insert("end", f"\n  {icon}  {ins.titre}\n", tag)
            for ligne in ins.corps.split("\n"):
                if ligne.strip():
                    self.text.insert("end", f"       {ligne}\n", "dim")
            if ins.action:
                self.text.insert("end", "\n     → Recommandation :\n", tag)
                for ligne in ins.action.split("\n"):
                    if ligne.strip():
                        self.text.insert("end", f"       {ligne}\n", tag)
            self.text.insert("end", "\n", "dim")

