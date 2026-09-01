"""Mixin _TabAssistantUI — extrait de tab_assistant.py.

Ces méthodes utilisent `self.xxx` défini dans TabAssistant.__init__.
"""
import tkinter as tk
from tkinter import ttk
import ui.theme as theme

# ─── Disponibilité des dépendances optionnelles ───────────────────────────────
try:
    import edge_tts as _edge_tts
    TTS_OK = True
except ImportError:
    TTS_OK = False

try:
    import sounddevice as _sd
    MICRO_OK = True
except ImportError:
    MICRO_OK = False

try:
    from faster_whisper import WhisperModel as _WhisperModel
    WHISPER_OK = True
except Exception:
    WHISPER_OK = False

class _TabAssistantUI:
    """Mixin : ne pas instancier directement."""

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
