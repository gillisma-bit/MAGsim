"""Mixin _TabConfigWorkflow pour TabConfig — extrait de ui/tab_config.py.

Ces méthodes utilisent `self.xxx` défini dans TabConfig.__init__.
"""
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser


class _TabConfigWorkflow:
    """Mixin : ne pas instancier directement."""

    def ouvrir_editeur_workflows(self):
        """Ouvre la fenêtre d'édition des procédures de tubes"""
        popup = tk.Toplevel(self.parent)
        popup.title("Éditeur de Procédures pour tubes")
        popup.geometry("900x680")
        popup.minsize(800, 600)
        popup.grab_set()

        ttk.Label(popup, text="🧪 Définissez les procédures pour chaque type de tube", 
                  font=("Segoe UI", 12, "bold")).pack(pady=10)

        # --- BOUTONS DE SAUVEGARDE (ancrés en bas, toujours visibles) ---
        frame_save = ttk.Frame(popup)
        frame_save.pack(side=tk.BOTTOM, fill="x", pady=10, padx=10)
        ttk.Button(frame_save, text="💾 SAUVER", command=lambda: self.sauver_workflow()).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_save, text="Fermer", command=popup.destroy).pack(side=tk.LEFT, padx=5)

        # --- FRAME GAUCHE : liste des types ---
        frame_left = ttk.Frame(popup)
        frame_left.pack(side=tk.LEFT, fill="both", expand=True, padx=10, pady=10)

        ttk.Label(frame_left, text="Types de tubes :", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        
        self.listbox_types = tk.Listbox(frame_left, height=15, width=25)
        self.listbox_types.pack(fill="both", expand=True, pady=5)
        self.listbox_types.bind("<<ListboxSelect>>", lambda e: self.charger_workflow_pour_edition())

        # Boutons pour gérer les types
        frame_btns_type = ttk.Frame(frame_left)
        frame_btns_type.pack(fill="x", pady=5)
        ttk.Button(frame_btns_type, text="➕ Nouveau type", command=lambda: self.ajouter_type_tube_dialog(popup)).pack(fill="x", pady=2)
        ttk.Button(frame_btns_type, text="🗑️ Supprimer", command=lambda: self.supprimer_type_tube_dialog(popup)).pack(fill="x", pady=2)

        # --- FRAME DROITE : édition du workflow ---
        frame_right = ttk.LabelFrame(popup, text="Procédure", padding=10)
        frame_right.pack(side=tk.RIGHT, fill="both", expand=True, padx=10, pady=10)

        ttk.Label(frame_right, text="Nom du type :", font=("Arial", 9, "bold")).pack(anchor="w")
        self.ent_nom_type = ttk.Entry(frame_right)
        self.ent_nom_type.pack(fill="x", pady=5)
        self.ent_nom_type.config(state="readonly")

        ttk.Label(frame_right, text="Couleur :", font=("Arial", 9)).pack(anchor="w")
        frame_couleur = ttk.Frame(frame_right)
        frame_couleur.pack(fill="x", pady=5)
        self.ent_couleur = ttk.Entry(frame_couleur, width=10)
        self.ent_couleur.pack(side=tk.LEFT, padx=5)

        def _choisir_couleur():
            result = colorchooser.askcolor(
                color=self.ent_couleur.get() or "#3498db",
                title="Choisir une couleur de tube")
            if result[1]:
                self.ent_couleur.delete(0, tk.END)
                self.ent_couleur.insert(0, result[1])
                self.update_color_preview()

        ttk.Button(frame_couleur, text="🎨", width=3,
                   command=_choisir_couleur).pack(side=tk.LEFT, padx=2)
        self.canvas_color = tk.Canvas(frame_couleur, width=30, height=30, bg="#ffffff")
        self.canvas_color.pack(side=tk.LEFT, padx=4)

        # ── Urgence & lots ───────────────────────────────────────
        f_lot = ttk.LabelFrame(frame_right, text="📦 Arrivées & urgence", padding=6)
        f_lot.pack(fill="x", pady=(8, 4))

        ttk.Label(f_lot, text="% de tubes urgents (0.0 – 1.0) :",
                  font=("Arial", 9)).grid(row=0, column=0, sticky="w", pady=2)
        self.ent_pct_urgent = ttk.Entry(f_lot, width=7)
        self.ent_pct_urgent.grid(row=0, column=1, padx=4)
        ttk.Label(f_lot, text="(s'ajoute à priorité=1)",
                  foreground="gray", font=("Arial", 8)).grid(row=0, column=2, padx=2)

        ttk.Label(f_lot, text="Taille de lot min (tubes) :",
                  font=("Arial", 9)).grid(row=1, column=0, sticky="w", pady=2)
        self.ent_lot_min = ttk.Entry(f_lot, width=7)
        self.ent_lot_min.grid(row=1, column=1, padx=4)

        ttk.Label(f_lot, text="Taille de lot max (tubes) :",
                  font=("Arial", 9)).grid(row=2, column=0, sticky="w", pady=2)
        self.ent_lot_max = ttk.Entry(f_lot, width=7)
        self.ent_lot_max.grid(row=2, column=1, padx=4)
        ttk.Label(f_lot, text="(taille aléatoire U[min, max] à chaque arrivée)",
                  foreground="gray", font=("Arial", 8)).grid(row=2, column=2, padx=2)

        ttk.Label(f_lot, text="Durée de validité (min, 0=illimitée) :",
                  font=("Arial", 9)).grid(row=3, column=0, sticky="w", pady=2)
        self.ent_validite = ttk.Entry(f_lot, width=7)
        self.ent_validite.grid(row=3, column=1, padx=4)
        ttk.Label(f_lot, text="(ex: 240 = 4 h max avant péremption)",
                  foreground="gray", font=("Arial", 8)).grid(row=3, column=2, padx=2)

        ttk.Label(frame_right, text="Étapes du workflow :", font=("Arial", 9, "bold")).pack(anchor="w", pady=(15, 5))
        
        # Listbox pour les étapes
        self.listbox_etapes = tk.Listbox(frame_right, height=8, width=35)
        self.listbox_etapes.pack(fill="both", expand=True)
        
        # Buttons pour gérer étapes
        frame_etapes = ttk.Frame(frame_right)
        frame_etapes.pack(fill="x", pady=5)
        ttk.Button(frame_etapes, text="➕ Ajouter étape", command=self.ajouter_etape_dialog).pack(side=tk.LEFT, padx=2)
        ttk.Button(frame_etapes, text="🗑️ Supprimer étape", command=self.supprimer_etape).pack(side=tk.LEFT, padx=2)

        # Binding pour mettre à jour la couleur en direct
        self.ent_couleur.bind("<KeyRelease>", lambda e: self.update_color_preview())

        # Charger la liste des types
        self.actualiser_liste_types()

    def actualiser_liste_types(self):
        """Rafraîchit la listbox des types de tubes"""
        self.listbox_types.delete(0, tk.END)
        types_tubes = self.config_manager.get_types_tubes()
        for nom in sorted(types_tubes.keys()):
            self.listbox_types.insert(tk.END, nom)

    def charger_workflow_pour_edition(self):
        """Charge le workflow du type sélectionné pour édition"""
        selection = self.listbox_types.curselection()
        if not selection:
            return
        
        nom_type = self.listbox_types.get(selection[0])
        workflow = self.config_manager.get_type_tube(nom_type)
        
        if not workflow:
            return
        
        # Remplir les champs
        self.ent_nom_type.config(state="normal")
        self.ent_nom_type.delete(0, tk.END)
        self.ent_nom_type.insert(0, nom_type)
        self.ent_nom_type.config(state="readonly")
        
        self.ent_couleur.delete(0, tk.END)
        self.ent_couleur.insert(0, workflow.get("couleur", "#3498db"))
        self.update_color_preview()

        self.ent_pct_urgent.delete(0, tk.END)
        self.ent_pct_urgent.insert(0, str(workflow.get("pct_urgent", 0.0)))
        self.ent_lot_min.delete(0, tk.END)
        self.ent_lot_min.insert(0, str(workflow.get("taille_lot_min", 1)))

        self.ent_lot_max.delete(0, tk.END)
        self.ent_lot_max.insert(0, str(workflow.get("taille_lot_max", 1)))

        self.ent_validite.delete(0, tk.END)
        self.ent_validite.insert(0, str(workflow.get("duree_validite_min", 0)))

        # Remplir les étapes
        self.listbox_etapes.delete(0, tk.END)
        for etape in workflow.get("workflow", []):
            self.listbox_etapes.insert(tk.END, etape)

    def ajouter_type_tube_dialog(self, parent):
        """Ouvre un dialog pour ajouter un nouveau type de tube"""
        dialog = tk.Toplevel(parent)
        dialog.title("Nouveau type de tube")
        dialog.geometry("300x150")
        dialog.grab_set()

        ttk.Label(dialog, text="Nom du type :", font=("Arial", 10)).pack(pady=5)
        ent_nom = ttk.Entry(dialog)
        ent_nom.pack(fill="x", padx=10, pady=5)

        def creer():
            nom = ent_nom.get().strip()
            if nom:
                self.config_manager.ajouter_type_tube(nom, 2, "#3498db", [])
                self.actualiser_liste_types()
                self.listbox_types.selection_clear(0, tk.END)
                idx = list(self.config_manager.get_types_tubes().keys()).index(nom)
                self.listbox_types.selection_set(idx)
                self.listbox_types.see(idx)
                self.charger_workflow_pour_edition()
                dialog.destroy()
            else:
                messagebox.showwarning("Erreur", "Veuillez entrer un nom")

        ttk.Button(dialog, text="Créer", command=creer).pack(pady=10)

    def supprimer_type_tube_dialog(self, parent):
        """Supprime le type sélectionné"""
        selection = self.listbox_types.curselection()
        if not selection:
            messagebox.showwarning("Attention", "Sélectionnez un type à supprimer")
            return
        
        nom = self.listbox_types.get(selection[0])
        if messagebox.askyesno("Confirmation", f"Supprimer le type '{nom}' ?"):
            self.config_manager.supprimer_type_tube(nom)
            self.actualiser_liste_types()
            self.ent_nom_type.config(state="normal")
            self.ent_nom_type.delete(0, tk.END)
            self.ent_nom_type.config(state="readonly")
            self.listbox_etapes.delete(0, tk.END)

    def ajouter_etape_dialog(self):
        """Ajoute une étape au workflow"""
        # Récupérer la liste des protocoles disponibles
        protocoles = list(self.config_manager.get_catalog_protocoles().keys())
        if not protocoles:
            messagebox.showwarning("Erreur", "Aucun protocole défini. Créez d'abord des protocoles dans vos machines.")
            return
        
        dialog = tk.Toplevel(self.parent)
        dialog.title("Ajouter une étape")
        dialog.geometry("350x200")
        dialog.grab_set()

        ttk.Label(dialog, text="Sélectionnez une étape/protocole :", font=("Arial", 10, "bold")).pack(pady=10)
        
        combo = ttk.Combobox(dialog, values=protocoles, width=30)
        combo.pack(fill="x", padx=10, pady=5)

        def ajouter():
            etape = combo.get()
            if etape:
                self.listbox_etapes.insert(tk.END, etape)
                dialog.destroy()
            else:
                messagebox.showwarning("Erreur", "Sélectionnez une étape")

        ttk.Button(dialog, text="Ajouter", command=ajouter).pack(pady=10)

    def supprimer_etape(self):
        """Supprime l'étape sélectionnée"""
        selection = self.listbox_etapes.curselection()
        if selection:
            self.listbox_etapes.delete(selection[0])

    def update_color_preview(self):
        """Met à jour l'aperçu de la couleur"""
        couleur = self.ent_couleur.get()
        try:
            self.canvas_color.config(bg=couleur)
        except tk.TclError:
            pass  # couleur invalide/incomplète pendant la saisie — ignoré volontairement

    def sauver_workflow(self):
        """Sauvegarde le workflow du type en cours d'édition"""
        nom_type = self.ent_nom_type.get()
        if not nom_type:
            messagebox.showwarning("Erreur", "Aucun type sélectionné")
            return

        couleur = self.ent_couleur.get()
        etapes = list(self.listbox_etapes.get(0, tk.END))

        try:
            pct_urgent = float(self.ent_pct_urgent.get())
            lot_min    = max(1, int(self.ent_lot_min.get()))
            lot_max    = max(lot_min, int(self.ent_lot_max.get()))
            validite   = max(0, int(self.ent_validite.get()))
        except ValueError:
            messagebox.showwarning("Erreur", "Valeurs numériques invalides (lot / urgence / validité).")
            return

        self.config_manager.ajouter_type_tube(
            nom_type, couleur, etapes,
            pct_urgent=pct_urgent,
            taille_lot_min=lot_min,
            taille_lot_max=lot_max,
            duree_validite_min=validite,
        )
        messagebox.showinfo("Succès", f"Procédure '{nom_type}' sauvegardée !")
