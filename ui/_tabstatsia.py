"""Mixin _TabStatsIA — extrait de tab_stats.py.

Ces méthodes utilisent `self.xxx` défini dans TabStats.__init__.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import ui.theme as theme

class _TabStatsIA:
    """Mixin : ne pas instancier directement."""

    def _ia_compte_rendu_auto(self):
        """Envoie automatiquement une demande de compte rendu à l'IA après une sim accélérée.
        Utilise une conversation fraîche et un contexte tronqué pour éviter les erreurs 413.
        N'est déclenché qu'en backend cloud (OpenAI/GitHub) — Ollama (modèle local GPU)
        n'est JAMAIS appelé automatiquement pour éviter de charger la GPU sans action explicite.
        """
        if self._ia_en_cours or self._ia_conversation is None:
            return

        # Refuser silencieusement si le backend est Ollama (modèle local GPU)
        if self._ia_backend not in ("openai", "github"):
            self.lbl_fast_status.config(text="✅ Terminé.")
            return

        stats      = getattr(self.tab_live, "stats_history", None) if self.tab_live else None
        aggregator = getattr(self.tab_live, "aggregator",    None) if self.tab_live else None

        # Construire un bloc de métriques compact (agrégateur + métriques enrichies)
        from core.ai_assistant import (
            construire_metriques_aggregateur, construire_metriques_block,
            envoyer_messages_openai, envoyer_messages,
        )
        metriques_parties = []
        if aggregator and aggregator.nb_jours >= 1.0:
            bloc_agg = construire_metriques_aggregateur(aggregator)
            if bloc_agg:
                metriques_parties.append(bloc_agg)
        if stats:
            bloc_rich = construire_metriques_block(self._ia_conversation._config, stats)
            if bloc_rich:
                metriques_parties.append(bloc_rich)
        metriques = "\n\n".join(metriques_parties)
        # Tronquer à 6000 caractères pour rester dans les limites de tokens
        if len(metriques) > 6000:
            metriques = metriques[:6000] + "\n… [tronqué pour limite de tokens]"

        QUESTION = (
            "Fais un compte rendu structuré en trois parties :\n"
            "1. **Bilan global** : débit, temps de transit moyen, taux de rejet et de dégradation.\n"
            "2. **Goulots identifiés** : quelles machines ou étapes limitent le flux, avec les chiffres clés.\n"
            "3. **Recommandations concrètes** : au moins 3 actions précises et réalisables pour améliorer "
            "le service. Pour chaque recommandation, indique l'impact attendu."
        )

        system_compact = (
            "Tu es l'assistant IA de MAGsim. Réponds TOUJOURS en français. "
            "Tu analyses les résultats d'une simulation de laboratoire médical. "
            "Cite chaque chiffre avec sa référence [Mx] depuis les métriques ci-dessous. "
            "Ne calcule rien toi-même — utilise uniquement les chiffres présents dans les métriques.\n\n"
            f"MÉTRIQUES DE LA SIMULATION :\n{metriques}"
        )
        messages_directs = [
            {"role": "system", "content": system_compact},
            {"role": "user",   "content": QUESTION},
        ]

        self._ia_afficher("[Compte rendu automatique]\n\n", "system")
        self._ia_afficher(f"Vous : {QUESTION}\n\n", "user")

        self._ia_en_cours = True
        self._ia_stop_event = __import__('threading').Event()
        self._ia_btn_envoyer.config(state="disabled")
        self._ia_btn_stop.config(state="normal")
        self._ia_lbl_statut.config(text="⬤  Réflexion…", fg="#f9e2af")
        self._ia_afficher("🤖  ", "assistant")
        self._ia_chat.config(state="normal")
        self._ia_token_start = self._ia_chat.index("end-1c")
        self._ia_chat.config(state="disabled")
        self.lbl_fast_status.config(text="✅ Terminé — génération du compte rendu…")

        _stop    = self._ia_stop_event
        backend  = self._ia_backend
        model    = self._ia_model
        conv     = self._ia_conversation

        def _appel():
            try:
                def on_token(tok):
                    self.parent.after(0, self._ia_on_token, tok)
                if backend == "openai":
                    reponse = envoyer_messages_openai(
                        messages=messages_directs, model=model,
                        on_token=on_token, stop_event=_stop,
                    )
                else:
                    reponse = envoyer_messages(
                        messages_directs, model=model,
                        on_token=on_token, stop_event=_stop,
                    )
                # Injecter la réponse dans l'historique de la conv principale
                conv.ajouter_message_utilisateur(QUESTION)
                conv.ajouter_message_assistant(reponse)
                self.parent.after(0, self._ia_finaliser_compte_rendu, reponse)
            except Exception as e:
                self.parent.after(0, self._ia_erreur, f"Erreur compte rendu : {e}")

        import threading
        threading.Thread(target=_appel, daemon=True).start()

    def _ia_finaliser_compte_rendu(self, reponse_brute):
        """Finalise le compte rendu automatique et met à jour le statut."""
        self._ia_finaliser(reponse_brute)
        self.lbl_fast_status.config(text="✅ Terminé — compte rendu généré")

    def _ouvrir_assistant(self):
        """Ouvre l'assistant IA dans une fenêtre flottante indépendante."""
        from ui.tab_assistant import TabAssistant

        # Si la fenêtre existe déjà, la remettre au premier plan
        if self._assistant_window is not None:
            try:
                if self._assistant_window.winfo_exists():
                    self._assistant_window.lift()
                    self._assistant_window.focus_force()
                    return
            except Exception:
                pass

        win = tk.Toplevel(self.parent)
        win.title("🤖 Assistant IA — MAGsim")
        win.geometry("920x700")
        win.minsize(640, 480)
        self._assistant_window = win

        # Centrer par rapport à la fenêtre principale
        self.parent.update_idletasks()
        root = self.parent.winfo_toplevel()
        rx = root.winfo_x() + root.winfo_width() // 2 - 460
        ry = root.winfo_y() + root.winfo_height() // 2 - 350
        win.geometry(f"920x700+{max(0, rx)}+{max(0, ry)}")

        frame = ttk.Frame(win)
        frame.pack(expand=True, fill="both")
        TabAssistant(frame, self.config_manager, tab_live_ref=self.tab_live)

        def _on_close():
            self._assistant_window = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_close)

    def _ia_afficher(self, texte, tag="system"):
        self._ia_chat.config(state="normal")
        self._ia_chat.insert("end", texte, tag)
        self._ia_chat.config(state="disabled")
        self._ia_chat.see("end")

    def _ia_charger_modeles(self):
        """Thread : charge les modèles Ollama + OpenAI disponibles."""
        from core.ai_assistant import (
            ollama_disponible, lister_modeles,
            openai_disponible, OPENAI_MODELES,
        )
        entrees = []
        if ollama_disponible():
            entrees += [f"Ollama │ {m}" for m in lister_modeles()]
        if openai_disponible():
            entrees += [f"OpenAI │ {m}" for m in OPENAI_MODELES]
        self.parent.after(0, self._ia_on_modeles_charges, entrees)

    def _ia_on_modeles_charges(self, entrees):
        self._ia_combo["values"] = entrees

        if entrees:
            def _pref(e):
                return "gpt-4o-mini" in e.lower() or "gpt-4.1-mini" in e.lower() or "llama3" in e.lower()
            sel = next((e for e in entrees if _pref(e)), entrees[0])
            self._ia_model_var.set(sel)
            self._ia_appliquer_selection(sel)
            self._ia_lbl_statut.config(text=f"⬤  Prêt  [{self._ia_backend.upper()}]", fg="#a6e3a1")
            self._ia_afficher("Assistant prêt. Posez-moi une question sur la simulation.\n\n", "system")
            self._ia_init_conversation()
        else:
            self._ia_lbl_statut.config(text="⬤  Aucun backend", fg="#f38ba8")
            self._ia_afficher(
                "⚠️  Aucun backend disponible.\n"
                "Option 1 : Installez Ollama (ollama.com)\n"
                "Option 2 : Configurez une clé OpenAI dans l'onglet Assistant IA (⛯ Clé OpenAI).\n\n",
                "error",
            )

    def _ia_appliquer_selection(self, sel):
        """Extrait backend + nom du modèle depuis une entrée du combobox."""
        if sel.startswith("OpenAI │ "):
            self._ia_backend = "openai"
            self._ia_model   = sel[len("OpenAI │ "):]
        elif sel.startswith("GitHub │ "):
            self._ia_backend = "github"
            self._ia_model   = sel[len("GitHub │ "):]
        else:
            self._ia_backend = "ollama"
            self._ia_model   = sel.split("│ ", 1)[-1] if "│" in sel else sel

    def _ia_on_model_change(self, _event=None):
        """Callback quand l'utilisateur change de modèle dans le combobox."""
        sel = self._ia_model_var.get()
        self._ia_appliquer_selection(sel)
        self._ia_lbl_statut.config(
            text=f"⬤  {self._ia_model}  [{self._ia_backend.upper()}]", fg="#a6e3a1"
        )
        self._ia_init_conversation()

    def _ia_on_ollama_ok(self, modeles):
        # Méthode gardée pour compatibilité — redirige vers _ia_on_modeles_charges
        entrees = [f"Ollama │ {m}" for m in modeles]
        self._ia_on_modeles_charges(entrees)

    def _ia_on_ollama_absent(self):
        self._ia_on_modeles_charges([])

    def _ia_init_conversation(self):
        from core.ai_assistant import Conversation
        stats      = getattr(self.tab_live, "stats_history", None) if self.tab_live else None
        aggregator = getattr(self.tab_live, "aggregator",    None) if self.tab_live else None
        conv = Conversation(model=self._ia_model, backend=self._ia_backend)
        conv.initialiser(self.config_manager.data, stats, aggregator=aggregator)
        self._ia_conversation = conv

    def _ia_actualiser_contexte(self, stats):
        """Appelé depuis refresh() — met à jour le contexte sans effacer l'historique."""
        if self._ia_conversation is None:
            return
        try:
            aggregator = getattr(self.tab_live, "aggregator", None) if self.tab_live else None
            if not self._ia_conversation._has_simulation and stats and stats.get("time"):
                self._ia_conversation.actualiser_contexte(stats, aggregator=aggregator)
            elif stats and stats != self._ia_conversation._stats_history:
                self._ia_conversation.actualiser_contexte(stats, aggregator=aggregator)
        except Exception:
            pass

    def _ia_on_entree_rapide(self, event):
        if not event.state & 0x1:  # Shift non enfoncé
            self._ia_envoyer()
            return "break"

    def _ia_envoyer(self):
        if self._ia_en_cours:
            return
        texte = self._ia_saisie.get("1.0", "end").strip()
        if not texte:
            return
        if not self._ia_conversation:
            messagebox.showwarning("Assistant IA", "Ollama n'est pas disponible.", parent=self.parent)
            return

        # Rafraîchir le contexte si une nouvelle sim est disponible
        stats_actuelles = getattr(self.tab_live, "stats_history", None) if self.tab_live else None
        if stats_actuelles:
            self._ia_actualiser_contexte(stats_actuelles)

        self._ia_saisie.delete("1.0", "end")
        self._ia_afficher(f"Vous : {texte}\n\n", "user")

        self._ia_en_cours = True
        self._ia_stop_event = __import__('threading').Event()
        self._ia_btn_envoyer.config(state="disabled")
        self._ia_btn_stop.config(state="normal")
        self._ia_lbl_statut.config(text="⬤  Réflexion…", fg="#f9e2af")
        self._ia_afficher("🤖  ", "assistant")
        self._ia_chat.config(state="normal")
        self._ia_token_start = self._ia_chat.index("end-1c")
        self._ia_chat.config(state="disabled")

        _stop = self._ia_stop_event

        def _appel():
            try:
                def on_token(tok):
                    self.parent.after(0, self._ia_on_token, tok)
                reponse = self._ia_conversation.envoyer(texte, on_token=on_token, stop_event=_stop)
                self.parent.after(0, self._ia_finaliser, reponse)
            except ConnectionError as e:
                self.parent.after(0, self._ia_erreur, str(e))
            except Exception as e:
                self.parent.after(0, self._ia_erreur, f"Erreur : {e}")

        threading.Thread(target=_appel, daemon=True).start()

    def _ia_on_token(self, token):
        self._ia_chat.config(state="normal")
        self._ia_chat.insert("end", token, "assistant")
        self._ia_chat.config(state="disabled")
        self._ia_chat.see("end")

    def _ia_finaliser(self, reponse_brute):
        from core.ai_assistant import texte_sans_patch
        self._ia_en_cours = False
        self._ia_stop_event = None
        self._ia_btn_envoyer.config(state="normal")
        self._ia_btn_stop.config(state="disabled")
        self._ia_lbl_statut.config(text="⬤  Prêt", fg="#a6e3a1")
        self._ia_chat.config(state="normal")
        self._ia_chat.delete(self._ia_token_start, "end")
        texte_propre = texte_sans_patch(reponse_brute)
        self._ia_chat.insert("end", texte_propre + "\n\n", "assistant")
        self._ia_chat.config(state="disabled")
        self._ia_chat.see("end")

    def _ia_stopper(self):
        """Interrompt la génération en cours."""
        if self._ia_stop_event:
            self._ia_stop_event.set()
        self._ia_afficher("\n[Arrêté]\n\n", "system")
        self._ia_en_cours = False
        self._ia_btn_envoyer.config(state="normal")
        self._ia_btn_stop.config(state="disabled")
        self._ia_lbl_statut.config(text="⬤  Prêt", fg="#a6e3a1")

    def _ia_dialog_sources(self):
        """Fenêtre affichant le dernier bloc MÉTRIQUES VÉRIFIABLES utilisé."""
        import re
        metriques = (
            self._ia_conversation._dernieres_metriques
            if self._ia_conversation else ""
        )
        if not metriques:
            from tkinter import messagebox
            messagebox.showinfo(
                "Sources",
                "Aucune métrique disponible.\nLancez d'abord une simulation.",
                parent=self.parent,
            )
            return

        dlg = tk.Toplevel(self.parent)
        dlg.title("📊 Métriques vérifiables")
        dlg.configure(bg="#1e1e2e")
        dlg.resizable(True, True)
        dlg.geometry("600x480")
        dlg.transient(self.parent)

        tk.Label(dlg,
                 text="📊  Chiffres utilisés par l'IA",
                 font=theme.FONT_SECTION,
                 bg="#1e1e2e", fg="#cba6f7",
                 anchor="w", padx=12, pady=8).pack(fill="x")
        tk.Label(dlg,
                 text="Chaque [Mx] cité dans une réponse correspond à une ligne ci-dessous.",
                 font=theme.FONT_NOTE + ("italic",),
                 bg="#1e1e2e", fg="#585b70",
                 anchor="w", padx=12).pack(fill="x")
        tk.Frame(dlg, bg="#313145", height=1).pack(fill="x", pady=(4, 0))

        frame_txt = tk.Frame(dlg, bg="#1e1e2e")
        frame_txt.pack(fill="both", expand=True, padx=8, pady=8)
        frame_txt.rowconfigure(0, weight=1)
        frame_txt.columnconfigure(0, weight=1)

        txt = tk.Text(
            frame_txt,
            font=("Consolas", 9),
            bg="#181825", fg="#cdd6f4",
            relief="flat", bd=0,
            wrap="none",
            padx=10, pady=8,
        )
        sb_v = ttk.Scrollbar(frame_txt, orient="vertical",   command=txt.yview)
        sb_h = ttk.Scrollbar(frame_txt, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)
        sb_v.grid(row=0, column=1, sticky="ns")
        sb_h.grid(row=1, column=0, sticky="ew")
        txt.grid(row=0, column=0, sticky="nsew")

        txt.tag_config("num",  foreground="#a6e3a1", font=("Consolas", 9, "bold"))
        txt.tag_config("warn", foreground="#f9e2af")

        txt.config(state="normal")
        for ligne in metriques.splitlines():
            if re.search(r"\[M\d+\]", ligne):
                parts = re.split(r"(\[M\d+\])", ligne)
                for p in parts:
                    if re.match(r"\[M\d+\]", p):
                        txt.insert("end", p, "num")
                    elif "⚠" in p or "SURCHARG" in p:
                        txt.insert("end", p, "warn")
                    else:
                        txt.insert("end", p)
                txt.insert("end", "\n")
            elif "===" in ligne or "---" in ligne:
                txt.insert("end", ligne + "\n", "num")
            else:
                txt.insert("end", ligne + "\n")
        txt.config(state="disabled")

        ttk.Button(dlg, text="Fermer", command=dlg.destroy,
                   padding=(10, 4)).pack(side=tk.BOTTOM, pady=(0, 10))

    def _ia_erreur(self, msg):
        self._ia_en_cours = False
        self._ia_stop_event = None
        self._ia_btn_envoyer.config(state="normal")
        self._ia_btn_stop.config(state="disabled")
        self._ia_lbl_statut.config(text="⬤  Erreur", fg="#f38ba8")
        self._ia_afficher(f"⚠️  {msg}\n\n", "error")
