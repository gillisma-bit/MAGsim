"""Mixin _TabAssistantTools — extrait de tab_assistant.py.

Ces méthodes utilisent `self.xxx` défini dans TabAssistant.__init__.
"""
import re
import tempfile
import asyncio
import ctypes
import tkinter as tk
from tkinter import ttk, messagebox
import threading

# ─── Disponibilité des dépendances optionnelles ───────────────────────────────
# Redétectées ici indépendamment de tab_assistant.py (même patron que
# _tabassistantui.py) pour que ce mixin reste utilisable sans import circulaire.
try:
    import edge_tts as _edge_tts
    TTS_OK = True
except ImportError:
    _edge_tts = None
    TTS_OK = False

try:
    import sounddevice as _sd_check  # noqa: F401 — juste pour tester la disponibilité
    MICRO_OK = True
except ImportError:
    MICRO_OK = False

_WHISPER_PROMPT = (
    "MAGsim, laboratoire, tube, technicien, machine, simulation, navette, urgence, "
    "centrifugeur, analyseur, automate, protocole, consommable, workflow, priorité, "
    "spécimen, prélèvement, résultat, délai, file d'attente, zone, trajet"
)


class _TabAssistantTools:
    """Mixin : ne pas instancier directement."""

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
            # Import différé : évite de recharger le modèle Whisper (lourd) une
            # deuxième fois — on récupère l'instance déjà chargée par tab_assistant.py.
            from ui.tab_assistant import _whisper
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

    def _injecter_texte(self, texte: str):
        self._saisie.delete("1.0", "end")
        self._saisie.insert("1.0", texte)
        self._lbl_statut.config(text="⬤  Prêt", fg="#a6e3a1")
        self._envoyer()

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
