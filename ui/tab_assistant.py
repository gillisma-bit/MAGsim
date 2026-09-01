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
except Exception:
    _sd = None
    _np = None
    MICRO_OK = False

# ─── Whisper (optionnel) ──────────────────────────────────────────────────────
_WHISPER_PROMPT = (
    "MAGsim, laboratoire, tube, technicien, machine, simulation, navette, urgence, "
    "centrifugeur, analyseur, automate, protocole, consommable, workflow, priorité, "
    "spécimen, prélèvement, résultat, délai, file d'attente, zone, trajet"
)
try:
    import warnings as _w, os as _os, sys as _sys
    _os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    # Ajouter les DLLs NVIDIA (cuDNN, cuBLAS) au chemin de recherche Windows
    for _pkg in ("nvidia.cudnn", "nvidia.cublas", "nvidia.cuda_runtime"):
        _parts = _pkg.split(".")
        try:
            import importlib as _il
            _mod = _il.import_module(_pkg.replace(".", "."))
            _dll_dir = _os.path.join(_os.path.dirname(_mod.__file__), "bin")
            if _os.path.isdir(_dll_dir):
                _os.add_dll_directory(_dll_dir)
        except Exception:
            pass
    # Fallback : chercher dans site-packages/nvidia/*/bin
    for _sp in _sys.path:
        _nvidia_root = _os.path.join(_sp, "nvidia")
        if _os.path.isdir(_nvidia_root):
            for _sub in _os.listdir(_nvidia_root):
                _bin = _os.path.join(_nvidia_root, _sub, "bin")
                if _os.path.isdir(_bin):
                    _os.add_dll_directory(_bin)
            break
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        from faster_whisper import WhisperModel as _WhisperModel
        try:
            _whisper = _WhisperModel("large-v3", device="cuda", compute_type="int8")
            print("[Whisper] large-v3 sur GPU (CUDA int8)")
        except Exception as _cuda_err:
            print(f"[Whisper] GPU indisponible ({_cuda_err}), repli sur medium/CPU")
            _whisper = _WhisperModel("medium", device="cpu", compute_type="int8")
    WHISPER_OK = True
except Exception:
    _whisper = None
    WHISPER_OK = False


class TabAssistant:
    def __init__(self, parent, config_manager, tab_live_ref=None, tab_config_ref=None):
        self.parent         = parent
        self.config_manager = config_manager
        self.tab_live       = tab_live_ref
        self.tab_config     = tab_config_ref
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
        _tts_init = TTS_OK
        if not _tts_init:
            try:
                from core.ai_assistant import openai_disponible as _od
                _tts_init = _od()
            except Exception:
                pass
        self._tts_actif    = tk.BooleanVar(value=_tts_init)
        self._tts_stop_event = threading.Event()   # interrompre la lecture en cours
        self._vad_actif    = tk.BooleanVar(value=False)   # auto-interruption (casque requis)
        self._micro_actif  = False
        self._audio_data   = []
        self._ptt_maintenu = False   # push-to-talk : Ctrl gauche maintenu
        self._build_ui()
        self._activer_push_to_talk()
        # Vérification des backends en arrière-plan au démarrage
        threading.Thread(target=self._charger_modeles, daemon=True).start()

    def _activer_push_to_talk(self):
        """Maintenir Ctrl (gauche) démarre l'enregistrement, le relâcher l'arrête et l'envoie."""
        if not MICRO_OK:
            return
        toplevel = self.parent.winfo_toplevel()
        toplevel.bind_all("<KeyPress-Control_L>", self._ptt_press)
        toplevel.bind_all("<KeyRelease-Control_L>", self._ptt_release)

    def _ptt_press(self, _event=None):
        if self._ptt_maintenu or self._micro_actif:
            return  # ignore l'auto-répétition du système pendant le maintien
        self._ptt_maintenu = True
        self._toggle_micro()

    def _ptt_release(self, _event=None):
        if not self._ptt_maintenu:
            return
        self._ptt_maintenu = False
        if self._micro_actif:
            self._toggle_micro()

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
                                         width=18, state="readonly",
                                         font=theme.FONT_BODY)
        self._combo_model.pack(side=tk.LEFT)
        self._combo_model.bind("<<ComboboxSelected>>", self._on_model_change)

        ttk.Button(bar_droite, text="⟳  Modèles",
                   command=self._actualiser_modeles,
                   padding=(6, 2)).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(bar_droite, text="⛯  Clé OpenAI",
                   command=self._dialog_token_openai,
                   padding=(6, 2)).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(bar_droite, text="📊  Sources",
                   command=self._dialog_sources,
                   padding=(6, 2)).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(bar_droite, text="↺  Réinitialiser",
                   command=self._reinitialiser_conversation,
                   padding=(6, 2)).pack(side=tk.LEFT, padx=(6, 0))

        # ── Bouton TTS ──
        self._btn_tts_lbl = "🔊 Voix" if TTS_OK else "🔇 Voix"
        _tts_btn_ok = TTS_OK
        if not _tts_btn_ok:
            try:
                from core.ai_assistant import openai_disponible as _od2
                _tts_btn_ok = _od2()
            except Exception:
                pass
        self._btn_tts = tk.Checkbutton(
            bar_droite,
            text=self._btn_tts_lbl,
            variable=self._tts_actif,
            font=theme.FONT_BODY,
            bg="#13131f", fg="#89b4fa",
            selectcolor="#313145",
            activebackground="#13131f",
            state="normal" if _tts_btn_ok else "disabled",
        )
        self._btn_tts.pack(side=tk.LEFT, padx=(10, 0))

        self._btn_vad = tk.Checkbutton(
            bar_droite,
            text="🎙️ Auto-interruption",
            variable=self._vad_actif,
            font=theme.FONT_BODY,
            bg="#13131f", fg="#89b4fa",
            selectcolor="#313145",
            activebackground="#13131f",
            state="normal" if MICRO_OK else "disabled",
        )
        self._btn_vad.pack(side=tk.LEFT, padx=(10, 0))

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
            cursor="hand2" if MICRO_OK else "arrow",
            state="normal" if MICRO_OK else "disabled",
            command=self._toggle_micro,
        )
        self._btn_micro_widget.grid(row=0, column=1, sticky="nsew", padx=(4, 2), pady=4)

        if MICRO_OK:
            tk.Label(saisie_frame, text="Ctrl (maintenu) = parler",
                     font=("Segoe UI", 7), bg="#181825", fg="#585b70"
                     ).grid(row=1, column=1, sticky="n")

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
        """Thread : charge les modèles Ollama + OpenAI disponibles."""
        from core.ai_assistant import (
            ollama_disponible, lister_modeles,
            openai_disponible, OPENAI_MODELES,
        )
        entrees  = []
        statuts  = []

        if ollama_disponible():
            ollama_ms = lister_modeles()
            entrees  += [f"Ollama │ {m}" for m in ollama_ms]
            statuts.append(f"Ollama ({len(ollama_ms)} modèles)")
        else:
            statuts.append("Ollama absent")

        if openai_disponible():
            entrees += [f"OpenAI │ {m}" for m in OPENAI_MODELES]
            statuts.append("OpenAI")
        else:
            statuts.append("OpenAI non configuré")

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
                "Option 2 (cloud) : Cliquez Clé OpenAI et saisissez votre clé API openai.com.",
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

    def _dialog_token_openai(self):
        """Fenêtre modale pour saisir/modifier la clé API OpenAI."""
        from core.ai_assistant import get_cle_openai, set_cle_openai
        dlg = tk.Toplevel(self.parent)
        dlg.title("Clé API OpenAI")
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

        tk.Label(dlg, text="⛯  OpenAI — Clé API",
                 bg="#1e1e2e", fg="#cba6f7",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=18, pady=(14, 6))

        _label(
            "Créez une clé API sur platform.openai.com :\n"
            "  Dashboard → API keys → Create new secret key\n"
            "  Le modèle gpt-4o-mini est recommandé (le moins cher)."
        )
        _label(
            "La clé est stockée localement dans data/config_api.json "
            "(jamais envoyée à nos serveurs)."
        )

        frame_entry = tk.Frame(dlg, bg="#1e1e2e")
        frame_entry.pack(fill="x", padx=18, pady=(10, 0))
        tk.Label(frame_entry, text="Clé :", bg="#1e1e2e", fg="#89b4fa",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 6))

        var_token  = tk.StringVar(value=get_cle_openai() or "")
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
                messagebox.showwarning("Clé vide",
                    "Saisissez une clé avant de sauvegarder.", parent=dlg)
                return
            set_cle_openai(cle)
            dlg.destroy()
            self._afficher_message_systeme(
                "✓ Clé OpenAI enregistrée. Chargement des modèles…"
            )
            self._actualiser_modeles()

        def _effacer():
            if messagebox.askyesno("Effacer la clé",
                    "Voulez-vous supprimer la clé OpenAI enregistrée ?",
                    parent=dlg):
                set_cle_openai("")
                dlg.destroy()
                self._afficher_message_systeme("Clé OpenAI supprimée.")
                self._actualiser_modeles()

        ttk.Button(frame_btn, text="✓  Enregistrer", command=_sauver,
                   padding=(10, 4)).pack(side=tk.LEFT)
        ttk.Button(frame_btn, text="✕  Effacer", command=_effacer,
                   padding=(10, 4)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(frame_btn, text="Annuler", command=dlg.destroy,
                   padding=(10, 4)).pack(side=tk.RIGHT)

        entry.focus_set()

    def _on_model_change(self, _event=None):
        """Détecte le backend à partir du préfixe et réinitialise la conversation."""
        selection = self._model.get()
        if selection.startswith("OpenAI │ "):
            self._backend = "openai"
            nom_modele    = selection[len("OpenAI │ "):]
        elif selection.startswith("GitHub │ "):
            self._backend = "github"
            nom_modele    = selection[len("GitHub │ "):]
        else:
            self._backend = "ollama"
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

        # TTS — toujours lancer, _synthetiser_et_jouer gère la disponibilité
        self._derniere_reponse = texte_propre
        if self._tts_actif.get():
            threading.Thread(target=self._synthetiser_et_jouer,
                             args=(texte_propre,), daemon=True).start()

        # Apprentissage du profil — extraction de trait en arrière-plan (léger, non bloquant)
        if self._derniere_question:
            threading.Thread(
                target=self._apprendre_profil,
                args=(self._derniere_question, texte_propre),
                daemon=True,
            ).start()

    def _apprendre_profil(self, question, reponse):
        """Analyse l'échange en arrière-plan et enrichit le profil MD si un trait durable apparaît."""
        from core.ai_assistant import extraire_trait_profil, consolider_section_profil
        from core.ai_memory import nb_notes_section, SEUIL_CONSOLIDATION
        model   = getattr(self, "_nom_modele", None) or self._model.get()
        backend = getattr(self, "_backend", "ollama")
        trait = extraire_trait_profil(question, reponse, model, backend)
        if not trait:
            return
        section, _note = trait
        # Si la section devient trop fournie, laisser l'IA fusionner les notes proches
        if nb_notes_section(section) > SEUIL_CONSOLIDATION:
            consolider_section_profil(section, model, backend)
        if self._conversation is not None and self._conversation._config is not None:
            # Rafraîchir immédiatement le prompt système pour que le trait
            # s'applique dès la suite de cette même conversation
            self._conversation._system = self._conversation._build_system(
                self._conversation._config,
                self._conversation._stats_history,
            )

    # ─────────────────────────────────────────────────────────────────────────
    #  TTS
    # ─────────────────────────────────────────────────────────────────────────

    def _synthetiser_et_jouer(self, texte: str, voix: str = "auto"):
        """Pipeline TTS phrase par phrase avec interruption VAD."""
        import re as _re, queue as _q, threading as _thr, time as _time
        t = texte
        t = _re.sub(r'```[\s\S]*?```', ' ', t)
        t = _re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', t)
        t = _re.sub(r'^#{1,6}\s+', '', t, flags=_re.MULTILINE)
        t = _re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
        t = _re.sub(r'`([^`]+)`', r'\1', t)
        t = _re.sub(r'^\s*[-*]\s+', '', t, flags=_re.MULTILINE)
        t = _re.sub(r'\[M\d+\]', '', t)
        t = _re.sub(r'\(\u2192\s*\[M\d+\]\)', '', t)
        t = _re.sub(r' {2,}', ' ', t).strip()
        if not t:
            return

        from core.ai_assistant import get_cle_openai
        cle = get_cle_openai()
        if not cle and not TTS_OK:
            return

        # Capturer l'événement courant — permet l'interruption depuis _toggle_micro
        stop_ev = self._tts_stop_event
        stop_ev.clear()

        # Découper en groupes de ~100 caractères
        morceaux = _re.split(r'(?<=[.!?…])\s+', t)
        groupes, buf = [], ""
        for m in morceaux:
            buf = (buf + " " + m).strip() if buf else m
            if len(buf) >= 80:
                groupes.append(buf)
                buf = ""
        if buf:
            groupes.append(buf)

        file_q = _q.Queue(maxsize=2)
        DONE = object()

        def _producer():
            for g in groupes:
                if stop_ev.is_set() or not g or not any(c.isalpha() for c in g):
                    continue
                try:
                    ch = self._tts_generer_edge(g) if TTS_OK else self._tts_generer_openai(g, cle)
                    file_q.put(ch)
                except Exception as exc:
                    print(f"[TTS] {exc}")
            file_q.put(DONE)

        _thr.Thread(target=_producer, daemon=True).start()

        # Démarrer la surveillance VAD uniquement si l'utilisateur l'a activée
        # (désactivé par défaut — sur haut-parleurs, le micro capte la voix de
        # l'IA elle-même et déclenche des interruptions intempestives)
        if MICRO_OK and self._vad_actif.get():
            _thr.Thread(target=self._vad_pendant_tts, args=(stop_ev,), daemon=True).start()

        # Consumer : lecture non-bloquante avec vérification stop_ev toutes les 50ms
        while True:
            item = file_q.get()
            if item is DONE or stop_ev.is_set():
                break
            self._jouer_mp3_mci(item, stop_ev)

        # Si VAD a détecté la voix : démarrer l'enregistrement automatiquement
        if stop_ev.is_set() and not self._micro_actif:
            self.parent.after(0, self._demarrer_enregistrement_apres_vad)

    def _jouer_mp3_mci(self, chemin: str, stop_ev=None):
        """Joue un MP3 via MCI avec pré-chauffage du device (évite que le début soit coupé)."""
        import time as _time
        alias = "_magsim_tts"
        try:
            ctypes.windll.winmm.mciSendStringW(
                f'open "{chemin}" type mpegvideo alias {alias}', None, 0, None)
            # Pré-chauffage : jouer 1ms puis revenir au début — évite que le pilote
            # audio Windows "mange" le tout début du vrai signal au premier play
            ctypes.windll.winmm.mciSendStringW(f'play {alias} from 0 to 1', None, 0, None)
            _time.sleep(0.08)
            ctypes.windll.winmm.mciSendStringW(f'stop {alias}', None, 0, None)
            ctypes.windll.winmm.mciSendStringW(f'seek {alias} to start', None, 0, None)

            ctypes.windll.winmm.mciSendStringW(f'play {alias}', None, 0, None)
            buf_s = ctypes.create_unicode_buffer(64)
            while True:
                if stop_ev is not None and stop_ev.is_set():
                    ctypes.windll.winmm.mciSendStringW(f'stop {alias}', None, 0, None)
                    break
                ctypes.windll.winmm.mciSendStringW(f'status {alias} mode', buf_s, 64, None)
                if buf_s.value.lower() in ('stopped', ''):
                    break
                _time.sleep(0.05)
            ctypes.windll.winmm.mciSendStringW(f'close {alias}', None, 0, None)
        except Exception:
            pass

    def _vad_pendant_tts(self, stop_ev):
        """Écoute le micro pendant la TTS — coupe si l'utilisateur parle."""
        import time as _t
        try:
            import sounddevice as _sd_, numpy as _np_
        except Exception:
            return
        SEUIL_RMS = 2200  # élevé par défaut — recommandé avec casque uniquement
        FRAMES_MIN = 6    # ~6×50ms = 300ms de parole soutenue pour déclencher
        compteur = 0

        def _cb(indata, frames, t, status):
            nonlocal compteur
            if stop_ev.is_set():
                raise _sd_.CallbackStop
            rms = _np_.sqrt(_np_.mean(indata.astype(_np_.float32) ** 2))
            if rms > SEUIL_RMS:
                compteur += 1
                if compteur >= FRAMES_MIN:
                    stop_ev.set()
                    raise _sd_.CallbackStop
            else:
                compteur = max(0, compteur - 1)

        try:
            with _sd_.InputStream(samplerate=16000, channels=1, dtype="int16",
                                   blocksize=800, callback=_cb):
                while not stop_ev.is_set():
                    _t.sleep(0.05)
        except Exception:
            pass

    def _demarrer_enregistrement_apres_vad(self):
        """Lance l'enregistrement micro après interruption VAD (appelé sur le thread UI)."""
        if not self._micro_actif:
            self._toggle_micro()

    def _tts_generer_openai(self, texte: str, cle: str, voix: str = "nova") -> str:
        """Génère un fichier MP3 via OpenAI TTS HD, retourne son chemin."""
        import urllib.request, json as _json
        payload = _json.dumps({
            "model": "tts-1-hd",
            "input": texte[:4096],
            "voice": voix,
            "response_format": "mp3",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech",
            data=payload,
            headers={"Authorization": f"Bearer {cle}", "Content-Type": "application/json"},
            method="POST",
        )
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            chemin = f.name
        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(chemin, "wb") as f:
                f.write(resp.read())
        return chemin

    def _tts_generer_edge(self, texte: str, voix: str = "fr-CA-SylvieNeural") -> str:
        """Génère un fichier MP3 via edge-tts (fallback local), retourne son chemin."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            chemin = f.name
        async def _run():
            comm = _edge_tts.Communicate(texte, voix)
            await comm.save(chemin)
        asyncio.run(_run())
        return chemin

    # Anciennes méthodes conservées pour compatibilité éventuelle
    def _tts_openai(self, texte: str, cle: str, voix: str = "nova"):
        chemin = self._tts_generer_openai(texte, cle, voix)
        self._jouer_mp3_mci(chemin)

    def _tts_edge(self, texte: str, voix: str = "fr-FR-DeniseNeural"):
        chemin = self._tts_generer_edge(texte, voix)
        self._jouer_mp3_mci(chemin)

    # ─────────────────────────────────────────────────────────────────────────
    #  Micro (sounddevice + Whisper)
    # ─────────────────────────────────────────────────────────────────────────

    def _toggle_micro(self):
        if not self._micro_actif:
            # Couper immédiatement la TTS en cours
            self._tts_stop_event.set()
            self._tts_stop_event = threading.Event()
            try:
                import sounddevice as sd_
            except Exception as exc:
                self._lbl_statut.config(text=f"⬤  Micro indisponible : {exc}", fg="#f38ba8")
                return
            self._micro_actif = True
            self._audio_data  = []
            self._btn_micro_widget.config(bg="#dc2626", text="⏹")
            self._lbl_statut.config(text="⬤  Enregistrement… (re-cliquer pour arrêter)", fg="#f38ba8")
            try:
                self._stream = sd_.InputStream(
                    samplerate=16000, channels=1, dtype="int16",
                    callback=self._audio_callback
                )
                self._stream.start()
            except Exception as exc:
                self._micro_actif = False
                self._btn_micro_widget.config(bg="#313145", text="🎤")
                self._lbl_statut.config(text=f"⬤  Erreur micro : {exc}", fg="#f38ba8")
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

    _WHISPER_ARTEFACTS = {"...", "[Inaudible]", "[Musique]", "[BLANK_AUDIO]", "[ Silence ]", "[silence]"}

    def _transcrire_et_injecter(self):
        try:
            import numpy as np_
            if not self._audio_data:
                self.parent.after(0, self._lbl_statut.config,
                                  {"text": "⬤  Aucune donnée audio capturée", "fg": "#585b70"})
                return
            audio = np_.concatenate(self._audio_data, axis=0)
            if audio.shape[0] < 1600:
                self.parent.after(0, self._lbl_statut.config,
                                  {"text": "⬤  Prêt (enregistrement trop court)", "fg": "#585b70"})
                return
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                chemin_wav = f.name
            import scipy.io.wavfile as _wavfile
            _wavfile.write(chemin_wav, 16000, audio.flatten().astype("int16"))

            from core.ai_assistant import get_cle_openai
            cle = get_cle_openai()
            if cle:
                texte = self._transcrire_openai(chemin_wav, cle)
            elif _whisper:
                segments, _ = _whisper.transcribe(chemin_wav, language="fr",
                                                   initial_prompt=_WHISPER_PROMPT)
                texte = " ".join(s.text for s in segments).strip()
            else:
                raise RuntimeError(
                    "Aucun moteur STT disponible.\n"
                    "Configurez une clé OpenAI ou installez faster-whisper."
                )
            if texte and texte not in self._WHISPER_ARTEFACTS and any(c.isalpha() for c in texte):
                self.parent.after(0, self._injecter_texte, texte)
            else:
                self.parent.after(0, self._lbl_statut.config,
                                  {"text": "⬤  Rien entendu — parlez plus fort ou réessayez", "fg": "#585b70"})
        except Exception as exc:
            self.parent.after(0, self._lbl_statut.config,
                              {"text": f"⬤  Erreur micro : {exc}", "fg": "#f38ba8"})

    def _transcrire_openai(self, chemin_wav: str, cle: str) -> str:
        """Transcription via OpenAI Whisper API (whisper-1) — ~1-2 secondes."""
        import urllib.request, json as _json, time as _t
        boundary = "MBnd" + str(int(_t.time() * 1000))
        with open(chemin_wav, "rb") as f:
            audio_bytes = f.read()

        def _field(name, value):
            return (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")

        body = (
            _field("model", "whisper-1")
            + _field("language", "fr")
            + _field("prompt", _WHISPER_PROMPT)
            + (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
                f"Content-Type: audio/wav\r\n\r\n"
            ).encode("utf-8")
            + audio_bytes
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/transcriptions",
            data=body,
            headers={
                "Authorization": f"Bearer {cle}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        return data.get("text", "").strip()

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

        # Enregistrer dans l'historique de session
        detail = " | ".join(descriptions)
        self._patches_session.append(detail)

        # Indiquer les ops ignorées si sélection partielle
        ignorees = [desc for var, _, desc in self._patch_vars if not var.get()]
        detail_affiche = "\n".join(f"✅ {d}" for d in descriptions)
        if ignorees:
            detail_affiche += "\n" + "\n".join(f"⏭ ignoré : {d}" for d in ignorees)

        self._afficher_message_systeme(
            f"Configuration mise à jour :\n{detail_affiche}\n"
            "Relancez une simulation pour voir l'impact des changements.",
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
