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

from ui._tabassistantdialogs import _TabAssistantDialogs
from ui._tabassistanttools import _TabAssistantTools
from ui._tabassistantui import _TabAssistantUI


class TabAssistant(_TabAssistantDialogs, _TabAssistantTools, _TabAssistantUI):
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

    _WHISPER_ARTEFACTS = {"...", "[Inaudible]", "[Musique]", "[BLANK_AUDIO]", "[ Silence ]", "[silence]"}

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
