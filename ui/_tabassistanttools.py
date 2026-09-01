"""Mixin _TabAssistantTools — extrait de tab_assistant.py.

Ces méthodes utilisent `self.xxx` défini dans TabAssistant.__init__.
"""
import re
import tempfile
import asyncio
import ctypes
import tkinter as tk
from tkinter import ttk
import threading

# ─── TTS (edge-tts, optionnel) ────────────────────────────────────────────────
try:
    import edge_tts as _edge_tts
except ImportError:
    _edge_tts = None

class _TabAssistantTools:
    """Mixin : ne pas instancier directement."""

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

    def _toggle_micro(self):
        if not self._micro_actif:
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
            if audio.shape[0] < 1600:  # < 0.1 s
                self.parent.after(0, self._lbl_statut.config,
                                  {"text": "⬤  Prêt (enregistrement trop court)", "fg": "#585b70"})
                return
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                chemin_wav = f.name
            import scipy.io.wavfile as _wavfile
            _wavfile.write(chemin_wav, 16000,
                           audio.flatten().astype("int16"))
            # Accéder au modèle Whisper depuis le module parent
            import sys
            _tab = sys.modules.get("ui.tab_assistant")
            whisper = getattr(_tab, "_whisper", None) if _tab else None
            if whisper is None:
                self.parent.after(0, self._lbl_statut.config,
                                  {"text": "⬤  Whisper non disponible", "fg": "#f38ba8"})
                return
            segments, _ = whisper.transcribe(chemin_wav, language="fr")
            texte = " ".join(s.text for s in segments).strip()
            # Filtrer les artefacts Whisper (silence, ponctuation seule)
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

        # Rafraîchir le plan de configuration si disponible
        if getattr(self, "tab_config", None) is not None:
            try:
                self.tab_config._refresh_plan_machines()
            except Exception:
                pass

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
