"""Onglet Diagnostic — validation de la configuration et détection de problèmes.

Vérifie en temps réel :
  • Cohérence des workflows : chaque étape a une machine capable
  • Machines inutilisées : aucun type de tube ne les visite
  • Goulots d'étranglement : file_max potentiellement insuffisante
  • Présence d'une ENTREE et d'une SORTIE
  • Fréquence d'arrivée vs débit des machines
"""

import tkinter as tk
from tkinter import ttk


# ── Niveaux de sévérité ──────────────────────────────────────────────────────
INFO    = "info"
WARN    = "warn"
ERROR   = "error"
OK      = "ok"

_ICONS = {OK: "✅", INFO: "ℹ️", WARN: "⚠️", ERROR: "❌"}
_TAGS  = {OK: "ok", INFO: "info", WARN: "warn", ERROR: "error"}


class TabDiagnostic:
    def __init__(self, parent, config_manager):
        self.parent = parent
        self.config_manager = config_manager
        self._build_ui()

    # ── Construction de l'interface ──────────────────────────────────────────

    def _build_ui(self):
        top = ttk.Frame(self.parent, padding=(12, 8))
        top.pack(fill="x")

        ttk.Label(top, text="🔍 Diagnostic de configuration",
                  font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)

        ttk.Button(top, text="↻  Actualiser", command=self.lancer_diagnostic,
                   padding=(10, 4)).pack(side=tk.RIGHT)

        # Zone de résultats avec scrollbar
        frame_res = ttk.Frame(self.parent, padding=(12, 4))
        frame_res.pack(fill="both", expand=True)

        self.text = tk.Text(
            frame_res,
            font=("Consolas", 10),
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
        self.text.tag_config("section", foreground="#cba6f7", font=("Consolas", 11, "bold"))
        self.text.tag_config("dim",     foreground="#585b70")

        # Barre de résumé en bas
        self.lbl_resume = ttk.Label(self.parent, text="", font=("Segoe UI", 10),
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
