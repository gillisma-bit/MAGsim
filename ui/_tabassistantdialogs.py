"""Mixin _TabAssistantDialogs — extrait de tab_assistant.py.

Ces méthodes utilisent `self.xxx` défini dans TabAssistant.__init__.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import ui.theme as theme

class _TabAssistantDialogs:
    """Mixin : ne pas instancier directement."""

    def _dialog_sources(self):
        """Fenêtre affichant le dernier bloc MÉTRIQUES VÉRIFIABLES utilisé."""
        metriques = (
            self._conversation._dernieres_metriques
            if self._conversation else ""
        )
        if not metriques:
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
        dlg.geometry("620x520")
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
            font=theme.FONT_MONO,
            bg="#181825", fg="#cdd6f4",
            relief="flat", bd=0,
            wrap="none",
            padx=10, pady=8,
        )
        sb_v = ttk.Scrollbar(frame_txt, orient="vertical",   command=txt.yview)
        sb_h = ttk.Scrollbar(frame_txt, orient="horizontal",  command=txt.xview)
        txt.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)
        sb_v.grid(row=0, column=1, sticky="ns")
        sb_h.grid(row=1, column=0, sticky="ew")
        txt.grid(row=0, column=0, sticky="nsew")

        # Coloriser les numéros [Mx]
        txt.tag_config("num",  foreground="#a6e3a1", font=("Consolas", 9, "bold"))
        txt.tag_config("warn", foreground="#f9e2af")

        txt.config(state="normal")
        for ligne in metriques.splitlines():
            import re
            if re.search(r"\[M\d+\]", ligne):
                # Insérer avec coloration du [Mx]
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

    def _dialog_token_github(self):
        """Fenêtre modale pour saisir/modifier le token GitHub."""
        from core.ai_assistant import get_cle_github, set_cle_github
        dlg = tk.Toplevel(self.parent)
        dlg.title("Token GitHub Models")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(bg="#1e1e2e")

        self.parent.update_idletasks()
        px = self.parent.winfo_rootx() + self.parent.winfo_width()  // 2
        py = self.parent.winfo_rooty() + self.parent.winfo_height() // 2
        dlg.geometry(f"520x290+{px - 260}+{py - 145}")

        def _label(txt):
            tk.Label(dlg, text=txt, bg="#1e1e2e", fg="#cdd6f4",
                     font=("Segoe UI", 9), justify="left",
                     wraplength=480).pack(anchor="w", padx=18, pady=(4, 0))

        tk.Label(dlg, text="⛯  GitHub Models — Token d'accès",
                 bg="#1e1e2e", fg="#cba6f7",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=18, pady=(14, 6))

        _label(
            "Générez un Personal Access Token sur github.com :\n"
            "  Settings → Developer settings → Personal access tokens → Tokens (classic)\n"
            "  Cochez « read:user » ou laissez sans scope — les deux fonctionnent."
        )
        _label(
            "Le token est stocké localement dans data/config_api.json "
            "(jamais envoyé à nos serveurs)."
        )

        frame_entry = tk.Frame(dlg, bg="#1e1e2e")
        frame_entry.pack(fill="x", padx=18, pady=(10, 0))
        tk.Label(frame_entry, text="Token :", bg="#1e1e2e", fg="#89b4fa",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 6))

        var_token  = tk.StringVar(value=get_cle_github() or "")
        var_masque = tk.BooleanVar(value=True)
        entry = tk.Entry(frame_entry, textvariable=var_token, show="•",
                         width=42, font=("Courier New", 9),
                         bg="#313244", fg="#cdd6f4",
                         insertbackground="#cdd6f4", relief="flat", bd=4)
        entry.pack(side=tk.LEFT)

        def _toggle():
            entry.config(show="" if not var_masque.get() else "•")
        tk.Checkbutton(frame_entry, text="Voir", variable=var_masque,
                       command=_toggle,
                       bg="#1e1e2e", fg="#585b70",
                       selectcolor="#1e1e2e",
                       font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(6, 0))

        frame_btn = tk.Frame(dlg, bg="#1e1e2e")
        frame_btn.pack(fill="x", padx=18, pady=14)

        def _sauver():
            cle = var_token.get().strip()
            if not cle:
                messagebox.showwarning("Token vide",
                    "Saisissez un token avant de sauvegarder.", parent=dlg)
                return
            set_cle_github(cle)
            dlg.destroy()
            self._afficher_message_systeme(
                "✓ Token GitHub enregistré. Chargement des modèles…"
            )
            self._actualiser_modeles()

        def _effacer():
            if messagebox.askyesno("Effacer le token",
                    "Voulez-vous supprimer le token GitHub enregistré ?",
                    parent=dlg):
                set_cle_github("")
                dlg.destroy()
                self._afficher_message_systeme("Token GitHub supprimé.")
                self._actualiser_modeles()

        ttk.Button(frame_btn, text="✓  Enregistrer", command=_sauver,
                   padding=(10, 4)).pack(side=tk.LEFT)
        ttk.Button(frame_btn, text="✕  Effacer", command=_effacer,
                   padding=(10, 4)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(frame_btn, text="Annuler", command=dlg.destroy,
                   padding=(10, 4)).pack(side=tk.RIGHT)

        entry.focus_set()

    def _dialog_style_ia(self):
        """Fenêtre modale pour configurer le style de réponse de l'IA."""
        from core.ai_assistant import get_style_ia, set_style_ia
        style_actuel = get_style_ia()

        dlg = tk.Toplevel(self.parent)
        dlg.title("Style de l'assistant IA")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(bg="#1e1e2e")

        self.parent.update_idletasks()
        px = self.parent.winfo_rootx() + self.parent.winfo_width()  // 2
        py = self.parent.winfo_rooty() + self.parent.winfo_height() // 2
        dlg.geometry(f"440x240+{px - 220}+{py - 120}")

        tk.Label(dlg, text="🎨  Style de l'assistant IA",
                 bg="#1e1e2e", fg="#cba6f7",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=18, pady=(14, 10))

        tk.Label(dlg, text="Ces réglages s'appliquent immédiatement à la prochaine réponse.",
                 bg="#1e1e2e", fg="#6c7086",
                 font=("Segoe UI", 8)).pack(anchor="w", padx=18, pady=(0, 10))

        var_court = tk.BooleanVar(value=style_actuel.get("reponses_courtes", False))
        var_questions = tk.BooleanVar(value=style_actuel.get("questions_proactives", True))

        def _case(parent, variable, texte, description):
            f = tk.Frame(parent, bg="#1e1e2e")
            f.pack(fill="x", padx=18, pady=4)
            tk.Checkbutton(f, text=texte, variable=variable,
                           font=("Segoe UI", 10),
                           bg="#1e1e2e", fg="#cdd6f4",
                           selectcolor="#313244",
                           activebackground="#1e1e2e").pack(anchor="w")
            tk.Label(f, text=description, bg="#1e1e2e", fg="#6c7086",
                     font=("Segoe UI", 8)).pack(anchor="w", padx=20)

        _case(dlg, var_court,
              "Réponses courtes et directes",
              "Maximum 3-4 phrases, sans introduction ni conclusion.")
        _case(dlg, var_questions,
              "Poser une question en fin de réponse",
              "Décochez pour que l'IA agisse sans demander confirmation.")

        frame_btn = tk.Frame(dlg, bg="#1e1e2e")
        frame_btn.pack(fill="x", padx=18, pady=16)

        def _sauver():
            nouveau_style = {
                "reponses_courtes":    var_court.get(),
                "questions_proactives": var_questions.get(),
            }
            set_style_ia(nouveau_style)
            # Reconstruire le prompt système immédiatement
            if self._conversation is not None and self._conversation._config is not None:
                self._conversation._system = self._conversation._build_system(
                    self._conversation._config,
                    self._conversation._stats_history,
                )
            dlg.destroy()
            self._afficher_message_systeme("✓ Style de l'assistant mis à jour.")

        ttk.Button(frame_btn, text="✓  Enregistrer", command=_sauver,
                   padding=(10, 4)).pack(side=tk.LEFT)
        ttk.Button(frame_btn, text="Annuler", command=dlg.destroy,
                   padding=(10, 4)).pack(side=tk.RIGHT)
