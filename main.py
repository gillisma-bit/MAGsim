# ── DLLs NVIDIA (cuDNN, cuBLAS) — doit être avant tout import ctranslate2 ──────
import os as _os, sys as _sys
for _sp in _sys.path:
    _nvidia_root = _os.path.join(_sp, "nvidia")
    if _os.path.isdir(_nvidia_root):
        _bins = [_os.path.join(_nvidia_root, _s, "bin")
                 for _s in _os.listdir(_nvidia_root)
                 if _os.path.isdir(_os.path.join(_nvidia_root, _s, "bin"))]
        if _bins:
            _os.environ["PATH"] = ";".join(_bins) + ";" + _os.environ.get("PATH", "")
        break
# ──────────────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk
from core.config_manager import ConfigManager
from core.db_manager import DBManager
from ui.menu_bar import MenuBar
from ui.tab_config import TabConfig
from ui.tab_live import TabLive
from ui.tab_reseau import TabReseau
from ui.tab_stats import TabStats
from ui.tab_diagnostic import TabDiagnostic
from ui.tab_assistant import TabAssistant
import ui.theme as theme

class MAGsimApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MAGsim - Digital Twin Laboratory Suite")
        
        # --- RÉSOLUTION PLEIN ÉCRAN ---
        # Maximise la fenêtre au démarrage
        self.root.state('zoomed') 

        # 1. Initialisation de la mémoire (JSON)
        self.config_manager = ConfigManager()

        # 1b. Base de données SQLite (données métier)
        self.db_manager = DBManager()

        # 2. Barre de menus
        self.menu_bar = MenuBar(self)

        # 3. Style visuel — thème centralisé
        self.style = ttk.Style()
        theme.appliquer(self.style)
        
        # 3. Création du conteneur d'onglets
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)
        
        # 4. Création des Frames pour chaque onglet
        self.tab_reseau_frame     = ttk.Frame(self.notebook)
        self.tab_config_frame     = ttk.Frame(self.notebook)
        self.tab_live_frame       = ttk.Frame(self.notebook)
        self.tab_stats_frame      = ttk.Frame(self.notebook)
        self.tab_diagnostic_frame = ttk.Frame(self.notebook)
        self.tab_assistant_frame  = ttk.Frame(self.notebook)

        # 5. Ajout des onglets au Notebook
        self.notebook.add(self.tab_reseau_frame,     text=" 🔗 RÉSEAU ")
        self.notebook.add(self.tab_config_frame,     text=" ⚙️ CONFIGURATION ")
        self.notebook.add(self.tab_live_frame,       text=" 🚀 SIMULATION LIVE ")
        self.notebook.add(self.tab_stats_frame,      text=" 📊 ANALYSE & GOULOTS ")
        self.notebook.add(self.tab_diagnostic_frame, text=" 🔍 DIAGNOSTIC ")
        self.notebook.add(self.tab_assistant_frame,  text=" 🤖 ASSISTANT IA ")

        # 6. CHARGEMENT DU CONTENU DES ONGLETS
        self.tab_live       = TabLive(self.tab_live_frame, self.config_manager, self.db_manager)
        self.tab_reseau     = TabReseau(self.tab_reseau_frame, self.config_manager, self)
        self.tab_reseau.tab_live_ref = self.tab_live   # injection pour métriques live
        self.tab_config     = TabConfig(self.tab_config_frame, self.config_manager)
        self.tab_stats      = TabStats(self.tab_stats_frame, self.config_manager, tab_live_ref=self.tab_live)
        self.tab_diagnostic = TabDiagnostic(self.tab_diagnostic_frame, self.config_manager,
                                            tab_live_ref=self.tab_live)
        self.tab_assistant  = TabAssistant(self.tab_assistant_frame, self.config_manager,
                                           tab_live_ref=self.tab_live,
                                           tab_config_ref=self.tab_config)

        # Rafraîchir le diagnostic quand l'onglet devient actif
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Interception du bouton X de la fenêtre
        self.root.protocol("WM_DELETE_WINDOW", self.menu_bar._quitter)

    def _on_tab_changed(self, event):
        tab = self.notebook.index(self.notebook.select())
        if tab == 1:   # onglet Configuration
            self.tab_config._dessiner_zone_staging()
        elif tab == 4:   # onglet Diagnostic (index décalé par l'ajout de Réseau en 1ère pos.)
            self.tab_diagnostic.lancer_diagnostic()
        elif tab == 5:  # onglet Assistant IA
            if self.tab_assistant._conversation is not None:
                self.tab_assistant._initialiser_conversation()

if __name__ == "__main__":
    root = tk.Tk()
    app = MAGsimApp(root)
    root.mainloop()