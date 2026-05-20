"""gradio_app.py — Interface vocale et conversationnelle MAGsim.

Lancement :  python gradio_app.py
Prérequis :  Ollama en cours d'exécution  (ollama serve)
             faster-whisper installé      (pip install faster-whisper)

L'assistant répond uniquement quand le gestionnaire lui parle.
Il ne prend jamais la parole en premier.
"""

import os
import sys
import queue
import threading

# Ancrer le CWD à la racine du projet (les chemins config sont relatifs)
_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

import gradio as gr

from core.config_manager import ConfigManager
from core.ai_assistant import (
    Conversation,
    extraire_patch,
    texte_sans_patch,
    appliquer_patch,
)

# ─── Whisper (optionnel : désactivé si non dispo ou pas de ffmpeg) ────────────
try:
    import warnings, os as _os
    _os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from faster_whisper import WhisperModel
        _whisper = WhisperModel("base", device="cpu", compute_type="int8")
    WHISPER_OK = True
except Exception as _e:
    print(f"[gradio_app] Whisper non disponible : {_e}")
    print("[gradio_app] Le micro sera désactivé — le chat texte fonctionne normalement.")
    WHISPER_OK = False


# ─── Synthèse vocale edge-tts (optionnelle) ────────────────────────────
try:
    import edge_tts as _edge_tts
    TTS_OK = True
except ImportError:
    TTS_OK = False
    print("[gradio_app] edge-tts non disponible — synthese vocale desactivee.")


# ─── Singletons partagés ──────────────────────────────────────────────────────
_config_mgr = ConfigManager()


def _lire_modeles_ollama():
    """Tente de lister les modèles Ollama disponibles localement."""
    try:
        import urllib.request, json
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            data = json.loads(r.read())
        noms = [m["name"] for m in data.get("models", [])]
        return [f"{n} (Ollama)" for n in noms] if noms else ["llama3 (Ollama)"]
    except Exception:
        return ["llama3 (Ollama)"]


def _parse_choix_modele(choix: str):
    """'qwen2.5:32b (Ollama)' → ('qwen2.5:32b', 'ollama')"""
    if "(GitHub)" in choix:
        return choix.replace(" (GitHub)", "").strip(), "github"
    return choix.replace(" (Ollama)", "").strip(), "ollama"


# ─── Pont simulation → Gradio ─────────────────────────────────────────────────
_LAST_SIM_PATH = os.path.join(_ROOT, "data", "last_sim.json")

def _charger_stats_sim():
    """Lit data/last_sim.json écrit par tab_live à la fin de chaque simulation."""
    import json as _json
    try:
        with open(_LAST_SIM_PATH, "r", encoding="utf-8") as fh:
            return _json.load(fh)
    except (FileNotFoundError, ValueError):
        return None


def _init_conversation(choix_modele: str) -> Conversation:
    model, backend = _parse_choix_modele(choix_modele)
    conv = Conversation(model=model, backend=backend)
    conv.initialiser(_config_mgr.data, stats_history=_charger_stats_sim())
    return conv


# ─── Transcription audio ──────────────────────────────────────────────────────
def _transcrire(audio_path: str) -> str:
    if not WHISPER_OK or not audio_path:
        return ""
    try:
        segments, _ = _whisper.transcribe(audio_path, language="fr")
        return " ".join(s.text for s in segments).strip()
    except Exception as e:
        return f"[Erreur transcription : {e}]"


# ─── Formatage du panneau patch ───────────────────────────────────────────────
def _patch_en_markdown(ops: list) -> str:
    lignes = ["**Modifications proposées par l'assistant :**\n"]
    for op in ops:
        lignes.append(f"- `{op['chemin']}` → **{op['valeur']}**")
    lignes.append("\n*Confirmez pour appliquer, Annuler pour ignorer.*")
    return "\n".join(lignes)


# ─── Historique format Gradio 6 : liste de dicts {role, content} ────────────
# [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]

def _add_user(history, texte):
    return history + [{"role": "user", "content": texte}]

def _set_assistant(history, texte):
    h = list(history)
    h[-1] = {"role": "assistant", "content": texte}
    return h

def _add_assistant(history, texte):
    return history + [{"role": "assistant", "content": texte}]


def _synthetiser(texte: str, voix: str = "fr-FR-DeniseNeural"):
    """Synthetise le texte en audio via edge-tts. Retourne le chemin MP3 ou None."""
    if not TTS_OK or not texte or not texte.strip():
        return None
    import asyncio, tempfile, re
    # Supprimer le formatage Markdown avant lecture
    t = texte
    t = re.sub(r'```[\s\S]*?```', ' ', t)        # blocs de code
    t = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', t)  # gras / italique
    t = re.sub(r'^#{1,6}\s+', '', t, flags=re.MULTILINE)  # titres
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)  # liens
    t = re.sub(r'`([^`]+)`', r'\1', t)          # code inline
    t = re.sub(r'^\s*[-*]\s+', '', t, flags=re.MULTILINE)  # listes
    t = re.sub(r'\[M\d+\]', '', t)              # references metriques [M1]
    t = re.sub(r'\(\u2192\s*\[M\d+\]\)', '', t) # (-> [M1])
    t = re.sub(r' {2,}', ' ', t).strip()
    if not t:
        return None
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        chemin = f.name
    async def _run():
        comm = _edge_tts.Communicate(t, voix)
        await comm.save(chemin)
    asyncio.run(_run())
    return chemin


# ─── Envoi d'un message et streaming de la reponse ───────────────────────────
def _handle_message(texte: str, history: list, conv: Conversation, patch_state, tts_actif: bool):
    """Generateur : stream la reponse token par token, detecte les patches."""

    if not texte or not texte.strip():
        yield history, "", gr.update(visible=False), "", None, None
        return

    texte = texte.strip()
    history = _add_user(history, texte)
    yield history, "", gr.update(visible=False), "", None, None

    # Lancer le LLM dans un thread avec streaming
    q: queue.Queue = queue.Queue()

    def on_token(token: str):
        q.put(("tok", token))

    def run():
        try:
            result = conv.envoyer(texte, on_token=on_token)
            q.put(("done", result))
        except ConnectionError as e:
            q.put(("err",
                   "Impossible de joindre Ollama. "
                   "Verifiez qu'Ollama est lance (ollama serve) "
                   f"et que le modele est disponible.\n\nDetail : {e}"))
        except Exception as e:
            q.put(("err", f"Erreur inattendue : {e}"))

    threading.Thread(target=run, daemon=True).start()

    # Ajouter un message assistant vide pour le streaming
    history = history + [{"role": "assistant", "content": ""}]

    partial = ""
    full_response = None

    while True:
        kind, val = q.get()

        if kind == "tok":
            partial += val
            history = _set_assistant(history, partial)
            yield history, "", gr.update(visible=False), "", None, None

        elif kind == "done":
            full_response = val
            break

        elif kind == "err":
            history = _set_assistant(history, val)
            yield history, "", gr.update(visible=False), "", None, None
            return

    # Reponse complete — detecter un eventuel patch de config
    patch_ops    = extraire_patch(full_response)
    texte_propre = texte_sans_patch(full_response)
    history      = _set_assistant(history, texte_propre)

    audio = _synthetiser(texte_propre) if tts_actif else None

    if patch_ops:
        yield history, "", gr.update(visible=True), _patch_en_markdown(patch_ops), patch_ops, audio
    else:
        yield history, "", gr.update(visible=False), "", None, audio


def handle_text(message, history, conv, patch_state, tts_actif):
    yield from _handle_message(message, history, conv, patch_state, tts_actif)


def handle_audio(audio_path, history, conv, patch_state, tts_actif):
    texte = _transcrire(audio_path)
    if not texte:
        yield history, "", gr.update(visible=False), "", None, None
        return
    # Afficher le texte transcrit comme message utilisateur
    yield from _handle_message(texte, history, conv, patch_state, tts_actif)


# ─── Confirmation / annulation du patch ──────────────────────────────────────
def confirmer_patch(history, patch_ops, conv):
    if not patch_ops:
        return history, gr.update(visible=False), "", None

    try:
        nouvelle_config, descriptions = appliquer_patch(_config_mgr.data, patch_ops)
        _config_mgr.data = nouvelle_config
        _config_mgr.sauvegarder()

        conv._config = nouvelle_config
        conv._system = conv._build_system(nouvelle_config, conv._stats_history)

        desc_txt = "\n".join(descriptions)
        msg = "Configuration mise a jour et sauvegardee :\n" + desc_txt

    except ValueError as e:
        msg = f"Impossible d'appliquer : {e}"

    history = _add_assistant(history, msg)
    return history, gr.update(visible=False), "", None


def annuler_patch(history):
    history = _add_assistant(history, "Modification annulee.")
    return history, gr.update(visible=False), "", None


# ─── Réinitialisation de la conversation ─────────────────────────────────────
def changer_modele(choix_modele, conv):
    """Change le modele LLM sans effacer l'historique de la conversation."""
    model, backend = _parse_choix_modele(choix_modele)
    conv.model   = model
    conv.backend = backend
    return conv


def reset_conversation(choix_modele):
    conv = _init_conversation(choix_modele)
    return conv, [], gr.update(visible=False), "", None


def rafraichir_stats(conv: Conversation):
    """Recharge last_sim.json dans la conversation courante sans effacer l'historique."""
    stats = _charger_stats_sim()
    conv.actualiser_contexte(stats)
    if stats and stats.get("time"):
        nb_j = stats["time"][-1] / 1440.0 if stats["time"] else 0
        msg = f"✅ Simulation rechargée ({nb_j:.1f} jours). Vous pouvez maintenant analyser les résultats."
    else:
        msg = "⚠️ Aucune simulation trouvée. Lancez et arrêtez une simulation dans MAGsim d'abord."
    return conv, msg


# ─── Construction de l'interface Gradio ──────────────────────────────────────
def build_app():
    modeles_ollama = _lire_modeles_ollama()
    modeles_github = ["openai/gpt-4.1-mini (GitHub)", "openai/gpt-4o (GitHub)"]
    tous_modeles   = modeles_github + modeles_ollama
    defaut         = "openai/gpt-4.1-mini (GitHub)"

    css = """
    .patch-panel {
        border: 1px solid #a6e3a1;
        border-radius: 10px;
        padding: 14px;
        background: #1a2e1a;
        margin-top: 8px;
    }
    .patch-panel button { margin-right: 8px; }
    footer { display: none !important; }
    """

    with gr.Blocks(title="Assistant MAGsim") as demo:

        # ── États (par session) ────────────────────────────────────────────
        conv_state  = gr.State(_init_conversation(defaut))
        patch_state = gr.State(None)

        # ── En-tete ────────────────────────────────────────────────────────
        with gr.Row(equal_height=True):
            gr.Markdown("## Assistant MAGsim")
            modele_dd = gr.Dropdown(
                choices=tous_modeles,
                value=defaut,
                label="Modele LLM",
                scale=2,
                min_width=220,
            )
            refresh_btn = gr.Button("🔄 Charger simulation", variant="secondary", scale=1, min_width=170)
            reset_btn   = gr.Button("Nouvelle conversation",  variant="secondary", scale=1)

        refresh_info = gr.Markdown("", visible=True)

        gr.Markdown(
            "_Posez vos questions sur le laboratoire. "
            "L'assistant repond uniquement quand vous lui parlez._"
        )

        # ── Historique de chat ─────────────────────────────────────────────
        chatbot = gr.Chatbot(
            label="",
            height=440,
        )

        # ── Lecture vocale ───────────────────────────────────────────────
        with gr.Row(equal_height=True):
            tts_cb = gr.Checkbox(
                label="Lire les reponses a voix haute",
                value=True,
                interactive=TTS_OK,
                scale=1,
            )
            audio_out = gr.Audio(
                label="",
                autoplay=True,
                visible=TTS_OK,
                interactive=False,
                scale=3,
            )

        # ── Zone de saisie ─────────────────────────────────────────────────
        with gr.Row(equal_height=True):
            gr.HTML("""
<div style="display:flex;align-items:center;justify-content:center;height:100%;padding:4px 12px;">
  <div style="text-align:center;">
    <button id="btn-parler" onclick="voixDemarrer()"
      style="width:58px;height:58px;border-radius:50%;border:none;cursor:pointer;
             background:#7c3aed;color:white;font-size:26px;
             box-shadow:0 2px 8px rgba(0,0,0,.35);transition:background .15s;">
      &#127908;
    </button>
    <div id="voice-etat" style="font-size:10px;color:#999;margin-top:4px;">cliquer pour parler</div>
  </div>
</div>""", scale=0)
            msg_in = gr.Textbox(
                placeholder="Posez votre question... (Entree pour envoyer)",
                label="Message",
                scale=4,
                lines=2,
                max_lines=6,
                show_label=False,
                elem_id="msg_in",
            )
            send_btn = gr.Button("Envoyer", variant="primary", scale=1, min_width=100, elem_id="send_btn")

        # ── Panneau de confirmation de patch ───────────────────────────────
        with gr.Group(visible=False) as patch_panel:
            patch_md = gr.Markdown("")
            with gr.Row():
                confirm_btn = gr.Button("Confirmer et sauvegarder", variant="primary")
                cancel_btn  = gr.Button("Annuler")

        # ── Sorties communes ───────────────────────────────────────────────
        common_outputs = [chatbot, msg_in, patch_panel, patch_md, patch_state, audio_out]

        # ── Connexions ─────────────────────────────────────────────────────
        refresh_btn.click(
            rafraichir_stats,
            inputs=[conv_state],
            outputs=[conv_state, refresh_info],
        )
        modele_dd.change(
            changer_modele,
            inputs=[modele_dd, conv_state],
            outputs=[conv_state],
        )
        send_btn.click(
            handle_text,
            inputs=[msg_in, chatbot, conv_state, patch_state, tts_cb],
            outputs=common_outputs,
        )
        msg_in.submit(
            handle_text,
            inputs=[msg_in, chatbot, conv_state, patch_state, tts_cb],
            outputs=common_outputs,
        )

        confirm_btn.click(
            confirmer_patch,
            inputs=[chatbot, patch_state, conv_state],
            outputs=[chatbot, patch_panel, patch_md, patch_state],
        )
        cancel_btn.click(
            annuler_patch,
            inputs=[chatbot],
            outputs=[chatbot, patch_panel, patch_md, patch_state],
        )
        reset_btn.click(
            reset_conversation,
            inputs=[modele_dd],
            outputs=[conv_state, chatbot, patch_panel, patch_md, patch_state],
        )

        demo.load(
            None,
            js="""
() => {
  var reco = null;
  window.voixDemarrer = function() {
    if (reco) { reco.abort(); reco = null; return; }
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    var etat = document.getElementById('voice-etat');
    var btn  = document.getElementById('btn-parler');
    if (!SR) { if(etat) etat.textContent = 'Chrome/Edge requis'; return; }
    reco = new SR();
    reco.lang = 'fr-FR';
    reco.continuous = false;
    reco.interimResults = false;
    if (btn)  btn.style.background  = '#dc2626';
    if (etat) etat.textContent = 'en ecoute...';
    reco.onresult = function(e) {
      var t = e.results[0][0].transcript;
      if (etat) etat.textContent = t.substring(0, 30);
      var ta = document.querySelector('#msg_in textarea');
      if (ta) {
        var setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(ta, t);
        ta.dispatchEvent(new Event('input',  { bubbles: true }));
        ta.dispatchEvent(new Event('change', { bubbles: true }));
      }
    };
    reco.onend = function() {
      reco = null;
      if (btn)  btn.style.background  = '#7c3aed';
      if (etat) etat.textContent = 'cliquer pour parler';
      setTimeout(function() {
        var b = document.querySelector('#send_btn button');
        if (b) b.click();
      }, 200);
    };
    reco.onerror = function(ev) {
      reco = null;
      if (btn)  btn.style.background = '#7c3aed';
      if (etat) etat.textContent = ev.error === 'no-speech' ? 'rien entendu' : ev.error;
    };
    reco.start();
  };
}
"""
        )

    return demo


# ─── Point d'entrée ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  Assistant MAGsim -- Interface Gradio")
    print("=" * 60)
    whisper_status = "actif (modele base)" if WHISPER_OK else "desactive"
    print(f"  Whisper (voix) : {whisper_status}")
    print(f"  Config labo    : {_config_mgr.filepath}")
    labo = _config_mgr.data.get('nom_projet', '(sans nom)')
    print(f"  Labo           : {labo}")
    print("=" * 60)

    app = build_app()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=True,
        show_error=True,
        theme=gr.themes.Soft(primary_hue="purple", neutral_hue="slate"),
    )
