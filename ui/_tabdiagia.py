"""Mixin _TabDiagIA — extrait de ui/tab_diagnostic.py.
"""
import tkinter as tk
from tkinter import ttk
import threading
import ui.theme as theme


class _TabDiagIA:
    """Mixin : ne pas instancier directement."""

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
            protocoles_m = m.get("protocoles", {})
            if not isinstance(protocoles_m, dict):
                continue
            for etape, proto in protocoles_m.items():
                if isinstance(proto, dict):
                    temps = proto.get("temps", 60)      # minutes SimPy
                elif isinstance(proto, (int, float)):
                    temps = proto
                else:
                    temps = 60
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

        # ── Analyse IA automatique (post-simulation) ──────────────────────────
        self._lancer_analyse_ia()

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

    # ── Analyse IA automatique (post-simulation) ─────────────────────────────

    def _lancer_analyse_ia(self):
        """Insère un placeholder et démarre l'analyse IA en thread si une simulation est dispo."""
        import threading

        hist = getattr(self.tab_live, "stats_history", None) if self.tab_live else None
        if not hist or not hist.get("time"):
            return  # pas de données → section IA omise

        try:
            from core.ai_assistant import openai_disponible, ollama_disponible
            has_openai  = openai_disponible()
            has_ollama = ollama_disponible()
        except Exception:
            has_openai = has_ollama = False

        self._section("7 · Analyse IA — synthèse des résultats")
        self.text.tag_config("ia_rep", foreground="#cba6f7", font=theme.FONT_MONO_S)

        if not has_openai and not has_ollama:
            self.text.insert("end",
                "  ⚠️  Aucun modèle IA disponible.\n"
                "      Configurez une clé OpenAI dans Paramètres → Assistant IA\n"
                "      ou lancez Ollama pour activer l'analyse automatique.\n",
                "warn")
            return

        # Placeholder "En cours…" — marque ia_result_start pour remplacement ultérieur
        self.text.mark_set("ia_result_start", self.text.index("end"))
        self.text.mark_gravity("ia_result_start", "left")
        self.text.insert("end", "  ⏳  Analyse IA en cours…\n", "info")

        threading.Thread(target=self._analyse_ia_thread, daemon=True).start()

    def _analyse_ia_thread(self):
        """Thread : construit la synthèse et appelle le LLM."""
        try:
            from core.ai_assistant import (
                construire_contexte, construire_metriques_block,
                openai_disponible, envoyer_messages_openai,
                ollama_disponible, envoyer_messages,
            )

            hist   = getattr(self.tab_live, "stats_history", {}) or {}
            config = self.config_manager.data

            contexte  = construire_contexte(config, hist)
            metriques = construire_metriques_block(config, hist)

            synthese = (
                f"Voici les données de simulation du laboratoire :\n\n"
                f"{contexte}\n\n"
                f"{metriques}\n\n"
            )
            prompt_user = (
                "Analyse ces résultats de simulation et donne-moi un diagnostic concis "
                "(5 à 8 points maximum). Pour chaque point : identifie le problème ou la force, "
                "cite le chiffre exact qui le justifie, et propose une action concrète si nécessaire. "
                "Réponds en français, en liste à puces (•)."
            )
            prompt_system = (
                "Tu es un expert en simulation de laboratoires médicaux. "
                "Tu analyses des résultats de simulation et fournis des diagnostics précis et actionnables. "
                "Réponds TOUJOURS en français. Sois concis et factuel. "
                "Ne cite que des chiffres présents dans les métriques fournies."
            )

            messages = [
                {"role": "system", "content": prompt_system},
                {"role": "user",   "content": synthese + prompt_user},
            ]

            if openai_disponible():
                reponse = envoyer_messages_openai(messages, model="gpt-4o-mini", timeout=60)
            else:
                reponse = envoyer_messages(messages, model="llama3", timeout=120)

            self.parent.after(0, lambda r=reponse: self._afficher_resultat_ia(r))

        except Exception as exc:
            msg = f"Erreur lors de l'analyse IA : {exc}"
            self.parent.after(0, lambda m=msg: self._afficher_resultat_ia(m, erreur=True))

    def _afficher_resultat_ia(self, texte, erreur=False):
        """Met à jour le widget texte avec la réponse IA (thread principal uniquement)."""
        try:
            self.text.config(state="normal")
            # Supprimer le placeholder entre ia_result_start et la fin
            try:
                self.text.delete("ia_result_start", "end")
            except Exception:
                pass

            if erreur:
                self.text.insert("end", f"  ❌  {texte}\n", "error")
            else:
                for ligne in texte.split("\n"):
                    stripped = ligne.strip()
                    if not stripped:
                        continue
                    if stripped.startswith(("•", "-", "*")):
                        self.text.insert("end", f"  {stripped}\n", "ia_rep")
                    else:
                        self.text.insert("end", f"  {stripped}\n", "dim")

            self.text.config(state="disabled")
            self.text.see("end")
        except Exception:
            pass  # widget peut avoir été détruit si l'onglet est fermé
