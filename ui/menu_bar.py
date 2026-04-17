"""Barre de menus principale de MAGsim.

Module indépendant — ne contient que la logique de menu.
L'intégration dans la fenêtre principale se fait via MenuBar(app).
"""

import tkinter as tk
from tkinter import messagebox

from ui.dialog_consommables import DialogConsommables


class MenuBar:
    """Crée et attache la barre de menus à la fenêtre principale.

    Paramètres
    ----------
    app : MAGsimApp
        Référence à l'application principale (accès aux onglets et root).
    """

    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.menubar = tk.Menu(self.root)

        self._creer_menu_fichier()
        self._creer_menu_configuration()
        self._creer_menu_simulation()
        self._creer_menu_aide()

        self.root.config(menu=self.menubar)

    # ------------------------------------------------------------------
    # Fichier
    # ------------------------------------------------------------------
    def _creer_menu_fichier(self):
        menu = tk.Menu(self.menubar, tearoff=0)
        menu.add_command(label="Sauvegarder la configuration",
                         accelerator="Ctrl+S",
                         command=self._sauvegarder)
        menu.add_separator()
        menu.add_command(label="Quitter",
                         accelerator="Alt+F4",
                         command=self._quitter)
        self.menubar.add_cascade(label="Fichier", menu=menu)

        # Raccourcis clavier
        self.root.bind_all("<Control-s>", lambda e: self._sauvegarder())

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def _creer_menu_configuration(self):
        menu = tk.Menu(self.menubar, tearoff=0)
        menu.add_command(label="Plan du laboratoire",
                         command=lambda: self._aller_onglet(0))
        menu.add_command(label="Machines",
                         command=lambda: self._aller_onglet(0))
        menu.add_command(label="Personnel",
                         command=lambda: self._aller_onglet(0))
        menu.add_separator()
        menu.add_command(label="Consommables",
                         command=self._ouvrir_config_consommables)
        menu.add_command(label="Protocoles",
                         command=lambda: self._aller_onglet(0))
        self.menubar.add_cascade(label="Configuration", menu=menu)

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------
    def _creer_menu_simulation(self):
        menu = tk.Menu(self.menubar, tearoff=0)
        menu.add_command(label="Lancer la simulation",
                         accelerator="F5",
                         command=self._lancer_simulation)
        menu.add_command(label="Arrêter la simulation",
                         command=self._arreter_simulation)
        menu.add_separator()
        menu.add_command(label="Statistiques et goulots",
                         command=lambda: self._aller_onglet(2))
        menu.add_command(label="Diagnostic",
                         command=lambda: self._aller_onglet(3))
        self.menubar.add_cascade(label="Simulation", menu=menu)

        self.root.bind_all("<F5>", lambda e: self._lancer_simulation())

    # ------------------------------------------------------------------
    # Aide
    # ------------------------------------------------------------------
    def _creer_menu_aide(self):
        menu = tk.Menu(self.menubar, tearoff=0)
        menu.add_command(label="À propos de MAGsim",
                         command=self._a_propos)
        self.menubar.add_cascade(label="Aide", menu=menu)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _aller_onglet(self, index: int):
        """Active l'onglet correspondant à l'index."""
        self.app.notebook.select(index)

    def _sauvegarder(self):
        """Sauvegarde la configuration JSON."""
        self.app.config_manager.sauvegarder()
        messagebox.showinfo("Sauvegarde", "Configuration sauvegardée avec succès.")

    def _quitter(self):
        """Demande confirmation avant de fermer."""
        if messagebox.askyesno("Quitter", "Voulez-vous quitter MAGsim ?"):
            self.root.quit()

    def _lancer_simulation(self):
        """Navigue vers l'onglet simulation et lance si possible."""
        self._aller_onglet(1)
        tab_live = getattr(self.app, "tab_live", None)
        if tab_live and hasattr(tab_live, "demarrer_simulation"):
            tab_live.demarrer_simulation()

    def _arreter_simulation(self):
        """Arrête la simulation en cours si possible."""
        tab_live = getattr(self.app, "tab_live", None)
        if tab_live and hasattr(tab_live, "arreter_simulation"):
            tab_live.arreter_simulation()

    def _ouvrir_config_consommables(self):
        """Ouvre la fenêtre de gestion des consommables."""
        db  = getattr(self.app, "db_manager", None)
        cfg = getattr(self.app, "config_manager", None)
        if db is None:
            messagebox.showerror("Erreur", "Base de données non initialisée.", parent=self.root)
            return
        DialogConsommables(self.root, db, cfg)

    def _a_propos(self):
        messagebox.showinfo(
            "À propos de MAGsim",
            "MAGsim — Digital Twin Laboratory Suite\n\n"
            "Simulation de flux de laboratoire médical.\n"
            "Développé avec Python & SimPy."
        )
