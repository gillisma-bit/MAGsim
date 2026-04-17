import tkinter as tk
from tkinter import ttk
from core.config_manager import ConfigManager
from core.db_manager import DBManager
from ui.menu_bar import MenuBar
from ui.tab_config import TabConfig
from ui.tab_live import TabLive
from ui.tab_stats import TabStats
from ui.tab_diagnostic import TabDiagnostic

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

        # 3. Style visuel (Thème moderne)
        self.style = ttk.Style()
        self.style.theme_use('clam') 
        self.style.configure("TNotebook.Tab", font=("Segoe UI", 11, "bold"), padding=[15, 8])
        
        # 3. Création du conteneur d'onglets
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)
        
        # 4. Création des Frames pour chaque onglet
        self.tab_config_frame     = ttk.Frame(self.notebook)
        self.tab_live_frame       = ttk.Frame(self.notebook)
        self.tab_stats_frame      = ttk.Frame(self.notebook)
        self.tab_diagnostic_frame = ttk.Frame(self.notebook)

        # 5. Ajout des onglets au Notebook
        self.notebook.add(self.tab_config_frame,     text=" ⚙️ CONFIGURATION ")
        self.notebook.add(self.tab_live_frame,       text=" 🚀 SIMULATION LIVE ")
        self.notebook.add(self.tab_stats_frame,      text=" 📊 ANALYSE & GOULOTS ")
        self.notebook.add(self.tab_diagnostic_frame, text=" 🔍 DIAGNOSTIC ")

        # 6. CHARGEMENT DU CONTENU DES ONGLETS
        self.tab_config     = TabConfig(self.tab_config_frame, self.config_manager)
        self.tab_live       = TabLive(self.tab_live_frame, self.config_manager)
        self.tab_stats      = TabStats(self.tab_stats_frame, self.config_manager, tab_live_ref=self.tab_live)
        self.tab_diagnostic = TabDiagnostic(self.tab_diagnostic_frame, self.config_manager)

        # Rafraîchir le diagnostic quand l'onglet devient actif
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Interception du bouton X de la fenêtre
        self.root.protocol("WM_DELETE_WINDOW", self.menu_bar._quitter)

    def _on_tab_changed(self, event):
        tab = self.notebook.index(self.notebook.select())
        if tab == 3:   # onglet Diagnostic
            self.tab_diagnostic.lancer_diagnostic()

if __name__ == "__main__":
    root = tk.Tk()
    app = MAGsimApp(root)
    root.mainloop()