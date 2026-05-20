"""Onglet Assistant IA — interface de chat en langage naturel avec Ollama.

Permet à un gestionnaire sans compétences techniques de :
  • Poser des questions sur les résultats de simulation
  • Décrire des changements organisationnels (nouveau tech, machine remplacée…)
  • Recevoir des propositions de mise à jour de configuration à confirmer
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import re
import asyncio
import tempfile
import ctypes
import ui.theme as theme

# ─── TTS (edge-tts, optionnel) ────────────────────────────────────────────────
try:
    import edge_tts as _edge_tts
    TTS_OK = True
except ImportError:
    TTS_OK = False

# ─── Micro (sounddevice + numpy, optionnel) ───────────────────────────────────
try:
    import sounddevice as _sd
    import numpy as _np
    MICRO_OK = True
except ImportError:
    MICRO_OK = False

# ─── Whisper (optionnel) ──────────────────────────────────────────────────────
try:
    import warnings as _w, os as _os
    _os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        from faster_whisper import WhisperModel as _WhisperModel
        _whisper = _WhisperModel("base", device="cpu", compute_type="int8")
    WHISPER_OK = True
except Exception:
    _whisper = None
    WHISPER_OK = False


class TabAssistant:
    def __init__(self, parent, config_manager, tab_live_ref=None):
        self.parent         = parent
        self.config_manager = config_manager
        self.tab_live       = tab_live_ref
        self._conversation  = None
        self._model         = tk.StringVar(value="llama3")
        self._backend       = "ollama"   # "ollama" | "github"
        self._en_cours      = False
        self._patch_en_attente = None
        # ── Mémoire / feedback ──
        self._derniere_question = ""
        self._derniere_reponse  = ""
        self._patches_session   = []   # descriptions des patches appliqués cette session
        # ── TTS / Micro ──
        self._tts_actif   = tk.BooleanVar(value=TTS_OK)
        self._micro_actif = False
        self._audio_data  = []
        self._build_ui()
        # Vérification des backends en arrière-plan au démarrage
        threading.Thread(target=self._charger_modeles, daemon=True).start()

    def set_tab_live(self, tab_live):
        self.tab_live = tab_live

    # ─────────────────────────────────────────────────────────────────────────
    #  Construction de l'interface
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Barre supérieure ──────────────────────────────────────────────────
        top = tk.Frame(self.parent, bg="#13131f")
        top.pack(fill="x", padx=0, pady=0)

        tk.Label(top,
                 text="🤖  Assistant IA — Gestionnaire de configuration",
                 font=theme.FONT_TITLE,
                 bg="#13131f", fg="#cba6f7",
                 anchor="w", padx=14, pady=10).pack(side=tk.LEFT)

        # Sélecteur de modèle + bouton refresh
        bar_droite = tk.Frame(top, bg="#13131f")
        bar_droite.pack(side=tk.RIGHT, padx=14)

        tk.Label(bar_droite, text="Modèle :", bg="#13131f", fg="#89b4fa",
                 font=theme.FONT_BODY).pack(side=tk.LEFT, padx=(0, 4))

        self._combo_model = ttk.Combobox(bar_droite, textvariable=self._model,
                                         width=32, state="readonly",
                                         font=theme.FONT_BODY)
        self._combo_model.pack(side=tk.LEFT)
        self._combo_model.bind("<<ComboboxSelected>>", self._on_model_change)

        ttk.Button(bar_droite, text="⟳  Modèles",
                   command=self._actualiser_modeles,
                   padding=(6, 2)).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(bar_droite, text="⛯  Token GitHub",
                   command=self._dialog_token_github,
                   padding=(6, 2)).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(bar_droite, text="🎨  Style IA",
                   command=self._dialog_style_ia,
                   padding=(6, 2)).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(bar_droite, text="📊  Sources",
                   command=self._dialog_sources,
                   padding=(6, 2)).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(bar_droite, text="↺  Réinitialiser",
                   command=self._reinitialiser_conversation,
                   padding=(6, 2)).pack(side=tk.LEFT, padx=(6, 0))

        # ── Bouton TTS ──
        self._btn_tts_lbl = "🔊 Voix" if TTS_OK else "🔇 Voix"
        self._btn_tts = tk.Checkbutton(
            bar_droite,
            text=self._btn_tts_lbl,
            variable=self._tts_actif,
            font=theme.FONT_BODY,
            bg="#13131f", fg="#89b4fa",
            selectcolor="#313145",
            activebackground="#13131f",
            state="normal" if TTS_OK else "disabled",
        )
        self._btn_tts.pack(side=tk.LEFT, padx=(10, 0))

        tk.Frame(self.parent, bg="#313145", height=1).pack(fill="x")

        # ── Zone principale : chat + panneau de confirmation ──────────────────
        main = tk.Frame(self.parent, bg="#1e1e2e")
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=0)
        main.rowconfigure(0, weight=1)

        # ── Colonne gauche : historique du chat ──────────────────────────────
        chat_frame = tk.Frame(main, bg="#1e1e2e")
        chat_frame.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=8)
        chat_frame.rowconfigure(0, weight=1)
        chat_frame.columnconfigure(0, weight=1)

        self._chat = tk.Text(
            chat_frame,
            font=theme.FONT_BODY,
            bg="#1e1e2e", fg="#cdd6f4",
            relief="flat", bd=0,
            wrap="word",
            state="disabled",
            padx=12, pady=10,
            cursor="arrow",
        )
        sb_chat = ttk.Scrollbar(chat_frame, orient="vertical", command=self._chat.yview)
        self._chat.configure(yscrollcommand=sb_chat.set)
        sb_chat.grid(row=0, column=1, sticky="ns")
        self._chat.grid(row=0, column=0, sticky="nsew")

        # Tags de couleur
        self._chat.tag_config("user",      foreground="#89dceb", font=theme.FONT_LABEL)
        self._chat.tag_config("assistant", foreground="#cdd6f4")
        self._chat.tag_config("system",    foreground="#585b70", font=theme.FONT_NOTE + ("italic",))
        self._chat.tag_config("patch",     foreground="#a6e3a1", font=theme.FONT_BODY)
        self._chat.tag_config("warn",      foreground="#f9e2af")
        self._chat.tag_config("error",     foreground="#f38ba8")

        # ── Barre de feedback (cachée par défaut) ─────────────────────────────────
        self._feedback_bar = tk.Frame(chat_frame, bg="#181825")
        # gridée dynamiquement en row=1 quand visible

        tk.Label(self._feedback_bar,
                 text="Cette réponse vous a-t-elle aidé ?",
                 bg="#181825", fg="#585b70",
                 font=theme.FONT_BODY).pack(side=tk.LEFT, padx=(10, 8))

        tk.Button(self._feedback_bar,
                  text="\U0001f44d  Utile",
                  font=theme.FONT_LABEL,
                  bg="#2ecc71", fg="white", relief="flat", bd=0,
                  padx=8, pady=3, activebackground="#27ae60", cursor="hand2",
                  command=self._approuver_reponse).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(self._feedback_bar,
                  text="\U0001f44e  Pas utile",
                  font=theme.FONT_BODY,
                  bg="#585b70", fg="white", relief="flat", bd=0,
                  padx=8, pady=3, activebackground="#4a4a5a", cursor="hand2",
                  command=self._rejeter_reponse).pack(side=tk.LEFT)

        self._lbl_nb_exemples = tk.Label(self._feedback_bar,
                  text="", bg="#181825", fg="#a6e3a1",
                  font=theme.FONT_NOTE + ("italic",))
        self._lbl_nb_exemples.pack(side=tk.RIGHT, padx=10)

        # ── Zone de saisie ──────────────────────────────────────────────────
        saisie_frame = tk.Frame(chat_frame, bg="#181825")
        saisie_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        saisie_frame.columnconfigure(0, weight=1)

        self._saisie = tk.Text(
            saisie_frame,
            font=theme.FONT_BODY,
            bg="#181825", fg="#cdd6f4",
            relief="flat", bd=0,
            height=3,
            padx=10, pady=8,
            wrap="word",
            insertbackground="#cdd6f4",
        )
        self._saisie.grid(row=0, column=0, sticky="ew", padx=(0, 1))
        self._saisie.bind("<Return>",       self._on_entree_rapide)
        self._saisie.bind("<Shift-Return>", lambda e: None)  # saut de ligne

        # Bouton micro
        self._btn_micro_widget = tk.Button(
            saisie_frame,
            text="🎤",
            font=("Segoe UI Emoji", 16),
            bg="#313145", fg="white",
            relief="flat", bd=0,
            padx=8, pady=4,
            activebackground="#45475a",
            cursor="hand2" if (MICRO_OK and WHISPER_OK) else "arrow",
            state="normal" if (MICRO_OK and WHISPER_OK) else "disabled",
            command=self._toggle_micro,
        )
        self._btn_micro_widget.grid(row=0, column=1, sticky="nsew", padx=(4, 2), pady=4)

        self._btn_envoyer = tk.Button(
            saisie_frame,
            text="Envoyer\n↵",
            font=theme.FONT_LABEL,
            bg="#7c3aed", fg="white",
            relief="flat", bd=0,
            padx=12, pady=4,
            activebackground="#6d28d9",
            cursor="hand2",
            command=self._envoyer,
        )
        self._btn_envoyer.grid(row=0, column=2, sticky="nsew", padx=(2, 8), pady=4)

        # ── Colonne droite : panneau de confirmation de patch ────────────────
        self._panel_confirm = tk.Frame(main, bg="#13131f", width=320)
        self._panel_confirm.grid(row=0, column=1, sticky="nsew", padx=(8, 10), pady=8)
        self._panel_confirm.pack_propagate(False)
        self._panel_confirm.columnconfigure(0, weight=1)

        tk.Label(self._panel_confirm,
                 text="📋  Modification proposée",
                 font=theme.FONT_SECTION,
                 bg="#13131f", fg="#a6e3a1",
                 anchor="w", padx=10, pady=8).pack(fill="x")

        tk.Frame(self._panel_confirm, bg="#313145", height=1).pack(fill="x")

        self._lbl_patch_vide = tk.Label(
            self._panel_confirm,
            text="Aucune modification\nen attente de confirmation.",
            font=theme.FONT_NOTE + ("italic",),
            bg="#13131f", fg="#585b70",
            justify="center",
        )
        self._lbl_patch_vide.pack(expand=True)

        # Contenu dynamique du patch (caché jusqu'à proposition)
        self._patch_frame = tk.Frame(self._panel_confirm, bg="#13131f")

        # Zone défilante pour les cases à cocher
        self._patch_scroll_canvas = tk.Canvas(
            self._patch_frame, bg="#1e1e2e", highlightthickness=0, height=200
        )
        _scroll_y = ttk.Scrollbar(
            self._patch_frame, orient="vertical",
            command=self._patch_scroll_canvas.yview,
        )
        self._patch_scroll_canvas.configure(yscrollcommand=_scroll_y.set)
        _scroll_y.pack(side=tk.RIGHT, fill="y")
        self._patch_scroll_canvas.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        self._patch_checks_frame = tk.Frame(self._patch_scroll_canvas, bg="#1e1e2e")
        self._patch_checks_window = self._patch_scroll_canvas.create_window(
            (0, 0), window=self._patch_checks_frame, anchor="nw"
        )
        self._patch_checks_frame.bind(
            "<Configure>",
            lambda e: self._patch_scroll_canvas.configure(
                scrollregion=self._patch_scroll_canvas.bbox("all")
            )
        )
        self._patch_scroll_canvas.bind(
            "<Configure>",
            lambda e: self._patch_scroll_canvas.itemconfig(
                self._patch_checks_window, width=e.width
            )
        )
        # Variables BooleanVar pour chaque opération (remplies dans _proposer_patch)
        self._patch_vars = []

        btn_row = tk.Frame(self._patch_frame, bg="#13131f")
        btn_row.pack(fill="x", padx=8, pady=(0, 12))

        self._btn_appliquer = tk.Button(
            btn_row,
            text="✅  Appliquer",
            font=theme.FONT_LABEL,
            bg="#2ecc71", fg="white",
            relief="flat", bd=0, padx=10, pady=6,
            activebackground="#27ae60",
            cursor="hand2",
            command=self._appliquer_patch,
        )
        self._btn_appliquer.pack(side=tk.LEFT, padx=(0, 6))

        self._btn_refuser = tk.Button(
            btn_row,
            text="✖  Refuser",
            font=theme.FONT_BODY,
            bg="#e74c3c", fg="white",
            relief="flat", bd=0, padx=10, pady=6,
            activebackground="#c0392b",
            cursor="hand2",
            command=self._refuser_patch,
        )
        self._btn_refuser.pack(side=tk.LEFT)

        # ── Statut en bas ─────────────────────────────────────────────────────
        self._lbl_statut = tk.Label(
            self.parent,
            text="⬤  Vérification d'Ollama…",
            font=theme.FONT_BODY,
            bg="#1e1e2e", fg="#585b70",
            anchor="w", padx=14, pady=4,
        )
        self._lbl_statut.pack(fill="x")

    # ─────────────────────────────────────────────────────────────────────────
    #  Chargement des modèles (Ollama + GitHub Models)
    # ─────────────────────────────────────────────────────────────────────────

    def _charger_modeles(self):
        """Thread : charge les modèles Ollama + GitHub Models disponibles."""
        from core.ai_assistant import (
            ollama_disponible, lister_modeles,
            github_models_disponible, GITHUB_MODELES,
        )
        entrees  = []
        statuts  = []

        if ollama_disponible():
            ollama_ms = lister_modeles()
            entrees  += [f"Ollama │ {m}" for m in ollama_ms]
            statuts.append(f"Ollama ({len(ollama_ms)} modèles)")
        else:
            statuts.append("Ollama absent")

        if github_models_disponible():
            entrees += [f"GitHub │ {m}" for m in GITHUB_MODELES]
            statuts.append("GitHub Models")
        else:
            statuts.append("GitHub non configuré")

        self.parent.after(0, self._on_modeles_charges, entrees, statuts)

    def _on_modeles_charges(self, entrees, statuts):
        """Callback UI : peuple le combobox et met à jour le statut."""
        try:
            if not self._combo_model.winfo_exists():
                return
        except Exception:
            return
        self._combo_model["values"] = entrees

        github_pret = any("GitHub Models" == s for s in statuts)
        ollama_pret = any(s.startswith("Ollama (") for s in statuts)

        if entrees:
            def _pref(e):
                return "gpt-4.1-mini" in e.lower() or "llama3" in e.lower()
            default = next((e for e in entrees if _pref(e)), entrees[0])
            self._model.set(default)
            self._on_model_change()

        if ollama_pret and github_pret:
            msg, fg = "⬤  Prêt (Ollama + GitHub Models)", "#a6e3a1"
        elif ollama_pret:
            msg, fg = "⬤  Ollama connecté — GitHub non configuré (cliquez ⛯ Token)", "#a6e3a1"
        elif github_pret:
            msg, fg = "⬤  GitHub Models prêt — Ollama absent", "#a6e3a1"
        else:
            msg = ("⬤  Aucun backend disponible — "
                   "installez Ollama (ollama.com) ou configurez un token GitHub (⛯ Token)")
            fg = "#f38ba8"

        self._lbl_statut.config(text=msg, fg=fg)

        if entrees:
            self._afficher_message_systeme(
                "Assistant prêt. Posez vos questions sur la simulation ou "
                "décrivez les changements souhaités."
            )
            self._initialiser_conversation()
        else:
            self._afficher_message_systeme(
                "⚠️  Aucun modèle disponible.\n\n"
                "Option 1 (local) : Installez Ollama → https://ollama.com\n"
                "  puis : ollama pull llama3 → ollama serve\n"
                "Option 2 (cloud) : Cliquez ⛯ Token et saisissez votre token GitHub Copilot.",
                tag="warn",
            )

    def _actualiser_modeles(self):
        self._lbl_statut.config(text="⬤  Chargement des modèles…", fg="#f9e2af")
        threading.Thread(target=self._charger_modeles, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    #  Dialog configuration du token GitHub
    # ─────────────────────────────────────────────────────────────────────────

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

    def _on_model_change(self, _event=None):
        """Détecte le backend à partir du préfixe et réinitialise la conversation."""
        selection = self._model.get()
        if selection.startswith("GitHub │ "):
            self._backend = "github"
            nom_modele    = selection[len("GitHub │ "):]
        else:
            self._backend = "ollama"
            # Support ancien format (sans préfixe) et nouveau "Ollama | xxx"
            nom_modele = selection.split("│ ", 1)[-1] if "│" in selection else selection
        # Stocker le vrai nom du modèle (sans préfixe) pour l'API
        self._nom_modele = nom_modele
        self._initialiser_conversation()
        self._afficher_message_systeme(
            f"Modèle : {nom_modele}  [ {self._backend.upper()} ]"
        )

    # ─────────────────────────────────────────────────────────────────────────
    #  Gestion de la conversation
    # ─────────────────────────────────────────────────────────────────────────

    def _initialiser_conversation(self):
        """(Re)construit le contexte et initialise la conversation."""
        from core.ai_assistant import Conversation
        stats      = getattr(self.tab_live, "stats_history", None) if self.tab_live else None
        aggregator = getattr(self.tab_live, "aggregator",    None) if self.tab_live else None
        nom_modele = getattr(self, "_nom_modele", self._model.get())
        backend    = getattr(self, "_backend", "ollama")
        conv = Conversation(model=nom_modele, backend=backend)
        conv.initialiser(self.config_manager.data, stats, aggregator=aggregator)
        self._conversation = conv

    def _reinitialiser_conversation(self):
        # Sauvegarder la session courante avant de réinitialiser
        if self._conversation and self._conversation.messages:
            from core.ai_memory import sauvegarder_resume_session
            nom_labo = self.config_manager.data.get("nom_projet", "")
            sauvegarder_resume_session(
                self._conversation.messages,
                self._patches_session,
                nom_labo,
            )
        # Reset du suivi de session
        self._patches_session   = []
        self._derniere_question = ""
        self._derniere_reponse  = ""
        self._masquer_feedback()
        self._initialiser_conversation()
        self._vider_chat()
        self._afficher_message_systeme("Conversation réinitialisée. Le contexte du labo a été rechargé.")

    # ─────────────────────────────────────────────────────────────────────────
    #  Envoi et réception de messages
    # ─────────────────────────────────────────────────────────────────────────

    def _on_entree_rapide(self, event):
        """Envoie avec Entrée (sans Shift)."""
        if not event.state & 0x1:   # Shift non enfoncé
            self._envoyer()
            return "break"

    def _envoyer(self):
        if self._en_cours:
            return
        texte = self._saisie.get("1.0", "end").strip()
        if not texte:
            return
        if not self._conversation:
            messagebox.showwarning("Assistant",
                                   "Ollama n'est pas disponible.",
                                   parent=self.parent)
            return

        self._derniere_question = texte   # ← mémoriser la question
        self._masquer_feedback()          # ← cacher le feedback de la réponse précédente

        # Rafraîchir le contexte si une simulation a été lancée depuis l'ouverture
        stats_actuelles = getattr(self.tab_live, "stats_history", None) if self.tab_live else None
        aggregator      = getattr(self.tab_live, "aggregator",    None) if self.tab_live else None
        if stats_actuelles and not self._conversation._has_simulation:
            self._conversation.actualiser_contexte(stats_actuelles, aggregator=aggregator)
        elif stats_actuelles and stats_actuelles != self._conversation._stats_history:
            self._conversation.actualiser_contexte(stats_actuelles, aggregator=aggregator)
        self._saisie.delete("1.0", "end")
        self._afficher_bulle_utilisateur(texte)
        self._demarrer_reponse()

        def _appel():
            try:
                reponse_tokens = []

                def on_token(tok):
                    reponse_tokens.append(tok)
                    self.parent.after(0, self._ajouter_token, tok)

                reponse = self._conversation.envoyer(texte, on_token=on_token)
                self.parent.after(0, self._finaliser_reponse, reponse)
            except ConnectionError as e:
                self.parent.after(0, self._erreur_reponse, str(e))
            except Exception as e:
                self.parent.after(0, self._erreur_reponse, f"Erreur inattendue : {e}")

        threading.Thread(target=_appel, daemon=True).start()

    def _demarrer_reponse(self):
        self._en_cours = True
        self._btn_envoyer.config(state="disabled", text="…")
        self._lbl_statut.config(text="⬤  Réflexion en cours…", fg="#f9e2af")
        self._chat.config(state="normal")
        self._chat.insert("end", "\n🤖  ", "assistant")
        self._chat.config(state="disabled")
        self._chat.see("end")
        # Marque la position de début du token stream
        self._chat.config(state="normal")
        self._token_start = self._chat.index("end-1c")
        self._chat.config(state="disabled")

    def _ajouter_token(self, token):
        """Ajoute un token streamé dans le chat (appelé depuis le thread principal)."""
        self._chat.config(state="normal")
        self._chat.insert("end", token, "assistant")
        self._chat.config(state="disabled")
        self._chat.see("end")

    def _finaliser_reponse(self, reponse_brute):
        """Appelé quand la réponse complète est reçue."""
        from core.ai_assistant import extraire_patch, texte_sans_patch

        self._en_cours = False
        self._btn_envoyer.config(state="normal", text="Envoyer\n↵")
        self._lbl_statut.config(text="⬤  Prêt", fg="#a6e3a1")

        # Supprimer le texte streamé et réécrire proprement sans le bloc patch
        self._chat.config(state="normal")
        # Supprimer depuis le début du token stream
        self._chat.delete(self._token_start, "end")
        texte_propre = texte_sans_patch(reponse_brute)
        self._chat.insert("end", texte_propre + "\n\n", "assistant")
        self._chat.config(state="disabled")
        self._chat.see("end")

        # Vérifier si un patch est proposé
        patch = extraire_patch(reponse_brute)
        if patch:
            self._proposer_patch(patch)

        # TTS
        self._derniere_reponse = texte_propre
        if self._tts_actif.get() and TTS_OK:
            threading.Thread(target=self._synthetiser_et_jouer,
                             args=(texte_propre,), daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    #  TTS
    # ─────────────────────────────────────────────────────────────────────────

    def _synthetiser_et_jouer(self, texte: str, voix: str = "fr-FR-DeniseNeural"):
        """Synthétise le texte et le joue via Windows MCI (thread arrière-plan)."""
        t = texte
        t = re.sub(r'```[\s\S]*?```', ' ', t)
        t = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', t)
        t = re.sub(r'^#{1,6}\s+', '', t, flags=re.MULTILINE)
        t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
        t = re.sub(r'`([^`]+)`', r'\1', t)
        t = re.sub(r'^\s*[-*]\s+', '', t, flags=re.MULTILINE)
        t = re.sub(r'\[M\d+\]', '', t)
        t = re.sub(r'\(\u2192\s*\[M\d+\]\)', '', t)
        t = re.sub(r' {2,}', ' ', t).strip()
        if not t:
            return
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                chemin = f.name
            async def _run():
                comm = _edge_tts.Communicate(t, voix)
                await comm.save(chemin)
            asyncio.run(_run())
            # Lecture via Windows MCI (aucune dépendance supplémentaire)
            alias = "_magsim_tts"
            ctypes.windll.winmm.mciSendStringW(
                f'open "{chemin}" type mpegvideo alias {alias}', None, 0, None)
            ctypes.windll.winmm.mciSendStringW(f'play {alias} wait', None, 0, None)
            ctypes.windll.winmm.mciSendStringW(f'close {alias}', None, 0, None)
        except Exception as exc:
            print(f"[TTS] {exc}")

    # ─────────────────────────────────────────────────────────────────────────
    #  Micro (sounddevice + Whisper)
    # ─────────────────────────────────────────────────────────────────────────

    def _toggle_micro(self):
        if not self._micro_actif:
            self._micro_actif = True
            self._audio_data  = []
            self._btn_micro_widget.config(bg="#dc2626", text="⏹")
            self._lbl_statut.config(text="⬤  Enregistrement… (re-cliquer pour arrêter)", fg="#f38ba8")
            self._stream = _sd.InputStream(
                samplerate=16000, channels=1, dtype="int16",
                callback=self._audio_callback
            )
            self._stream.start()
        else:
            self._arreter_micro()

    def _audio_callback(self, indata, frames, time, status):
        self._audio_data.append(indata.copy())

    def _arreter_micro(self):
        self._micro_actif = False
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        self._btn_micro_widget.config(bg="#313145", text="🎤")
        self._lbl_statut.config(text="⬤  Transcription…", fg="#f9e2af")
        threading.Thread(target=self._transcrire_et_injecter, daemon=True).start()

    def _transcrire_et_injecter(self):
        try:
            audio = _np.concatenate(self._audio_data, axis=0)
            if audio.shape[0] < 1600:  # < 0.1 s
                self.parent.after(0, self._lbl_statut.config,
                                  {"text": "⬤  Prêt (enregistrement trop court)", "fg": "#585b70"})
                return
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                chemin_wav = f.name
            import scipy.io.wavfile as _wavfile
            _wavfile.write(chemin_wav, 16000,
                           audio.flatten().astype("int16"))
            segments, _ = _whisper.transcribe(chemin_wav, language="fr")
            texte = " ".join(s.text for s in segments).strip()
            if texte:
                self.parent.after(0, self._injecter_texte, texte)
            else:
                self.parent.after(0, self._lbl_statut.config,
                                  {"text": "⬤  Rien entendu", "fg": "#585b70"})
        except Exception as exc:
            self.parent.after(0, self._lbl_statut.config,
                              {"text": f"⬤  Erreur micro : {exc}", "fg": "#f38ba8"})

    def _injecter_texte(self, texte: str):
        self._saisie.delete("1.0", "end")
        self._saisie.insert("1.0", texte)
        self._lbl_statut.config(text="⬤  Prêt", fg="#a6e3a1")
        self._envoyer()

    def _erreur_reponse(self, msg):
        self._en_cours = False
        self._btn_envoyer.config(state="normal", text="Envoyer\n↵")
        self._lbl_statut.config(text="⬤  Erreur de connexion", fg="#f38ba8")
        self._chat.config(state="normal")
        if "(429)" in msg:
            msg += "\n   → Trop de requêtes en peu de temps. Patientez 30 secondes et réessayez."
        self._chat.insert("end", f"\n⚠️  {msg}\n\n", "error")
        self._chat.config(state="disabled")
        self._chat.see("end")

    # ─────────────────────────────────────────────────────────────────────────
    #  Panneau de confirmation de patch
    # ─────────────────────────────────────────────────────────────────────────

    def _proposer_patch(self, patch_ops):
        """Affiche le panneau de confirmation avec une case à cocher par opération."""
        from core.ai_assistant import appliquer_patch

        # Valider d'abord (toutes les ops)
        try:
            _, descriptions = appliquer_patch(self.config_manager.data, patch_ops)
        except ValueError as e:
            self._afficher_message_systeme(f"⚠️  Modification refusée : {e}", tag="warn")
            return

        self._patch_en_attente = patch_ops

        # Vider les cases précédentes
        for w in self._patch_checks_frame.winfo_children():
            w.destroy()
        self._patch_vars.clear()

        tk.Label(
            self._patch_checks_frame,
            text="Cochez les modifications à appliquer :",
            font=("Segoe UI", 9, "bold"),
            bg="#1e1e2e", fg="#cdd6f4",
            anchor="w", pady=4,
        ).pack(fill="x", padx=6)

        for op, desc in zip(patch_ops, descriptions):
            var = tk.BooleanVar(value=True)
            self._patch_vars.append((var, op, desc))
            cb = tk.Checkbutton(
                self._patch_checks_frame,
                text=desc,
                variable=var,
                font=("Segoe UI", 9),
                bg="#1e1e2e", fg="#a6e3a1",
                selectcolor="#313145",
                activebackground="#1e1e2e",
                activeforeground="#a6e3a1",
                anchor="w",
                wraplength=270,
                justify="left",
            )
            cb.pack(fill="x", padx=6, pady=2)

        # Afficher le panneau
        self._lbl_patch_vide.pack_forget()
        self._patch_frame.pack(fill="both", expand=True, pady=(0, 8))

    def _appliquer_patch(self):
        """Applique uniquement les opérations cochées par l'utilisateur."""
        from core.ai_assistant import appliquer_patch

        if not self._patch_en_attente or not self._patch_vars:
            return

        ops_selectionnees = [op for var, op, _ in self._patch_vars if var.get()]
        if not ops_selectionnees:
            messagebox.showwarning(
                "Aucune sélection",
                "Cochez au moins une modification à appliquer.",
                parent=self.parent,
            )
            return

        try:
            nouveau_data, descriptions = appliquer_patch(
                self.config_manager.data, ops_selectionnees
            )
        except ValueError as e:
            messagebox.showerror("Erreur", str(e), parent=self.parent)
            return

        # Appliquer et sauvegarder
        self.config_manager.data = nouveau_data
        self.config_manager.sauvegarder()

        # Détecter les machines ajoutées en zone de dépôt
        nouvelles_en_attente = [
            m.get("nom") or k
            for k, m in nouveau_data.get("machines", {}).items()
            if isinstance(m, dict) and m.get("en_attente_placement")
               and m.get("type") not in ("TECH_OFFICE", "ENTREE", "SORTIE", "REPOS")
        ]

        # Enregistrer dans l'historique de session
        detail = " | ".join(descriptions)
        self._patches_session.append(detail)

        # Indiquer les ops ignorées si sélection partielle
        ignorees = [desc for var, _, desc in self._patch_vars if not var.get()]
        detail_affiche = "\n".join(f"✅ {d}" for d in descriptions)
        if ignorees:
            detail_affiche += "\n" + "\n".join(f"⏭ ignoré : {d}" for d in ignorees)

        msg_fin = "Relancez une simulation pour voir l'impact des changements."
        if nouvelles_en_attente:
            noms = ", ".join(nouvelles_en_attente)
            msg_fin = (
                f"📦  {noms} a été ajouté à la zone de dépôt du plan.\n"
                "👉  Allez dans l'onglet Configuration, faites glisser l'appareil "
                "à sa place dans le labo, puis relancez une simulation."
            )

        self._afficher_message_systeme(
            f"Configuration mise à jour :\n{detail_affiche}\n{msg_fin}",
            tag="patch",
        )

        self._initialiser_conversation()
        self._masquer_patch()

    def _refuser_patch(self):
        """Refuse le patch sans rien modifier."""
        self._patch_en_attente = None
        self._masquer_patch()
        self._afficher_message_systeme("Modification annulée. La configuration n'a pas changé.")

    def _masquer_patch(self):
        self._patch_en_attente = None
        self._patch_vars.clear()
        self._patch_frame.pack_forget()
        self._lbl_patch_vide.pack(expand=True)

    # ─────────────────────────────────────────────────────────────────────────
    #  Feedback 👍 / 👎
    # ─────────────────────────────────────────────────────────────────────────

    def _afficher_feedback(self):
        """Affiche la barre de feedback sous le chat."""
        from core.ai_memory import nb_exemples
        nom_labo = self.config_manager.data.get("nom_projet", "")
        n = nb_exemples(nom_labo)
        if n:
            self._lbl_nb_exemples.config(text=f"📚 {n} exemple(s) mémorisé(s)")
        else:
            self._lbl_nb_exemples.config(text="")
        self._feedback_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))

    def _masquer_feedback(self):
        """Cache la barre de feedback."""
        self._feedback_bar.grid_remove()

    def _approuver_reponse(self):
        """👍 — enregistre la paire Q/R dans la mémoire persistante."""
        from core.ai_memory import sauvegarder_exemple
        if not self._derniere_question or not self._derniere_reponse:
            self._masquer_feedback()
            return
        nom_labo = self.config_manager.data.get("nom_projet", "")
        sauvegarder_exemple(self._derniere_question, self._derniere_reponse, nom_labo)
        self._masquer_feedback()
        self._afficher_message_systeme(
            "✅ Réponse mémorisée — le modèle s'en souviendra lors des prochaines sessions.",
            tag="patch",
        )

    def _rejeter_reponse(self):
        """👎 — ignore la réponse, cache la barre."""
        self._masquer_feedback()

    # ─────────────────────────────────────────────────────────────────────────
    #  Helpers d'affichage
    # ─────────────────────────────────────────────────────────────────────────

    def _afficher_bulle_utilisateur(self, texte):
        self._chat.config(state="normal")
        self._chat.insert("end", f"👤  Vous : {texte}\n\n", "user")
        self._chat.config(state="disabled")
        self._chat.see("end")

    def _afficher_message_systeme(self, texte, tag="system"):
        self._chat.config(state="normal")
        self._chat.insert("end", f"{texte}\n\n", tag)
        self._chat.config(state="disabled")
        self._chat.see("end")

    def _vider_chat(self):
        self._chat.config(state="normal")
        self._chat.delete("1.0", "end")
        self._chat.config(state="disabled")
