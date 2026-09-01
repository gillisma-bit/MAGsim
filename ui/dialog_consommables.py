"""Fenêtre de gestion des produits consommables.

Permet de créer, modifier et supprimer des consommables.
La suppression vérifie si le produit est utilisé dans des protocoles actifs.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import unicodedata
import re
import ui.theme as theme

from core.db_manager import DBManager
from core.consommable import Consommable


class DialogConsommables(tk.Toplevel):
    """Fenêtre modale de gestion des consommables."""

    COULEURS_CAT = {
        "reactif": "#d6eaf8",
        "diluant": "#d5f5e3",
        "objet":   "#fdebd0",
    }

    def __init__(self, parent, db_manager: DBManager, config_manager=None):
        super().__init__(parent)
        self.db = db_manager
        self.config_manager = config_manager   # pour récupérer les noms de protocoles
        self._consommable_selectionne = None   # Consommable en cours d'édition

        self.title("Gestion des consommables")
        self.geometry("920x580")
        self.resizable(True, True)
        self.grab_set()                        # fenêtre modale

        self._construire_ui()
        self._rafraichir_liste()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------
    def _construire_ui(self):
        # ── Barre de filtres ──────────────────────────────────────────
        barre = ttk.Frame(self, padding=(10, 6))
        barre.pack(fill="x")

        ttk.Label(barre, text="Filtrer par service :").pack(side=tk.LEFT, padx=(0, 4))
        self._var_service = tk.StringVar(value="Tous")
        combo_service = ttk.Combobox(barre, textvariable=self._var_service,
                                     values=["Tous"] + list(Consommable.SERVICES.keys()),
                                     state="readonly", width=10)
        combo_service.pack(side=tk.LEFT, padx=4)
        combo_service.bind("<<ComboboxSelected>>", lambda e: self._rafraichir_liste())

        ttk.Label(barre, text="Catégorie :").pack(side=tk.LEFT, padx=(12, 4))
        self._var_cat = tk.StringVar(value="Toutes")
        combo_cat = ttk.Combobox(barre, textvariable=self._var_cat,
                                  values=["Toutes"] + Consommable.CATEGORIES,
                                  state="readonly", width=10)
        combo_cat.pack(side=tk.LEFT, padx=4)
        combo_cat.bind("<<ComboboxSelected>>", lambda e: self._rafraichir_liste())

        ttk.Button(barre, text="➕ Nouveau",
                   command=self._nouveau).pack(side=tk.RIGHT, padx=4)

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # ── Corps principal ───────────────────────────────────────────
        corps = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        corps.pack(fill="both", expand=True, padx=10, pady=10)

        # Panneau gauche — liste
        frame_liste = ttk.Frame(corps)
        corps.add(frame_liste, weight=2)
        self._construire_liste(frame_liste)

        # Panneau droit — formulaire
        frame_form = ttk.LabelFrame(corps, text="Détail du consommable", padding=12)
        corps.add(frame_form, weight=3)
        self._construire_formulaire(frame_form)

    def _construire_liste(self, parent):
        ttk.Label(parent, text="Consommables",
                  font=theme.FONT_LABEL).pack(anchor="w", pady=(0, 4))

        colonnes = ("nom", "cat", "service", "cout")
        self._tree = ttk.Treeview(parent, columns=colonnes, show="headings",
                                   selectmode="browse", height=20)
        self._tree.heading("nom",     text="Nom")
        self._tree.heading("cat",     text="Catégorie")
        self._tree.heading("service", text="Service")
        self._tree.heading("cout",    text="Coût/unité")
        self._tree.column("nom",     width=180, stretch=True)
        self._tree.column("cat",     width=80,  stretch=False)
        self._tree.column("service", width=60,  stretch=False)
        self._tree.column("cout",    width=80,  stretch=False, anchor="e")

        sb = ttk.Scrollbar(parent, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)

        self._tree.pack(side=tk.LEFT, fill="both", expand=True)
        sb.pack(side=tk.LEFT, fill="y")

        self._tree.bind("<<TreeviewSelect>>", self._on_selection)

    def _construire_formulaire(self, parent):
        # Identifiant — généré automatiquement, affiché en lecture seule
        ttk.Label(parent, text="Identifiant (auto)").grid(
            row=0, column=0, sticky="w", pady=3)
        self._var_id = tk.StringVar(value="—")
        ttk.Label(parent, textvariable=self._var_id,
                  foreground="#666666",
                  font=theme.FONT_MONO).grid(row=0, column=1, sticky="w", padx=6, pady=3)

        # Nom
        ttk.Label(parent, text="Nom du produit *").grid(
            row=1, column=0, sticky="w", pady=3)
        self._var_nom = tk.StringVar()
        ent_nom = ttk.Entry(parent, textvariable=self._var_nom)
        ent_nom.grid(row=1, column=1, sticky="ew", padx=6, pady=3)

        # Catégorie
        ttk.Label(parent, text="Catégorie *").grid(
            row=2, column=0, sticky="w", pady=3)
        self._var_categorie = tk.StringVar(value=Consommable.CATEGORIES[0])
        ttk.Combobox(parent, textvariable=self._var_categorie,
                     values=Consommable.CATEGORIES,
                     state="readonly").grid(row=2, column=1, sticky="ew", padx=6, pady=3)

        # Service
        ttk.Label(parent, text="Service *").grid(
            row=3, column=0, sticky="w", pady=3)
        self._var_service_form = tk.StringVar(value="CTS")
        ttk.Combobox(parent, textvariable=self._var_service_form,
                     values=list(Consommable.SERVICES.keys()),
                     state="readonly").grid(row=3, column=1, sticky="ew", padx=6, pady=3)

        # Unité de mesure
        ttk.Label(parent, text="Unité de mesure *").grid(
            row=4, column=0, sticky="w", pady=3)
        self._var_unite = tk.StringVar(value=Consommable.UNITES[0])
        ttk.Combobox(parent, textvariable=self._var_unite,
                     values=Consommable.UNITES,
                     state="readonly").grid(row=4, column=1, sticky="ew", padx=6, pady=3)

        # Coût unitaire
        ttk.Label(parent, text="Coût unitaire ($) *").grid(
            row=5, column=0, sticky="w", pady=3)
        self._var_cout = tk.StringVar(value="0.0")
        ttk.Entry(parent, textvariable=self._var_cout).grid(
            row=5, column=1, sticky="ew", padx=6, pady=3)

        # Description
        ttk.Label(parent, text="Description").grid(
            row=6, column=0, sticky="nw", pady=3)
        self._txt_description = tk.Text(parent, height=4, width=30, wrap="word")
        self._txt_description.grid(row=6, column=1, sticky="ew", padx=6, pady=3)

        parent.columnconfigure(1, weight=1)

        # ── Boutons d'action ─────────────────────────────────────────
        ttk.Separator(parent, orient="horizontal").grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=10)

        frame_btns = ttk.Frame(parent)
        frame_btns.grid(row=8, column=0, columnspan=2, sticky="ew")

        ttk.Button(frame_btns, text="💾 Sauvegarder",
                   command=self._sauvegarder).pack(side=tk.LEFT, padx=4)
        ttk.Button(frame_btns, text="🔄 Effacer le formulaire",
                   command=self._nouveau).pack(side=tk.LEFT, padx=4)

        self._btn_suppr = tk.Button(frame_btns, text="🗑️ Supprimer",
                                    bg=theme.BTN_DEL_BG, fg=theme.BTN_DEL_FG,
                                    activebackground=theme.BTN_DEL_ACT,
                                    font=theme.FONT_BTN_DEL,
                                    command=self._supprimer,
                                    state="disabled")
        self._btn_suppr.pack(side=tk.RIGHT, padx=4)

    # ------------------------------------------------------------------
    # Données
    # ------------------------------------------------------------------
    @staticmethod
    def _slugifier(texte: str) -> str:
        """Convertit un nom en identifiant : 'Réactif EDTA K2' → 'REACTIF_EDTA_K2'."""
        # Supprime les accents
        texte = unicodedata.normalize("NFD", texte)
        texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
        # Majuscules, remplace les caractères non alphanumériques par _
        texte = re.sub(r"[^A-Za-z0-9]+", "_", texte).upper().strip("_")
        return texte

    def _generer_id_unique(self, nom: str) -> str:
        """Génère un ID unique basé sur le nom, avec suffixe si collision."""
        base = self._slugifier(nom)
        if not base:
            base = "CONSOMMABLE"
        # Récupère tous les IDs existants
        ids_existants = {c.id for c in self.db.get_consommables()}
        if base not in ids_existants:
            return base
        # Ajoute un suffixe numérique
        i = 2
        while f"{base}_{i}" in ids_existants:
            i += 1
        return f"{base}_{i}"

    def _rafraichir_liste(self):
        """Recharge la liste selon les filtres actifs."""
        service = self._var_service.get()
        cat     = self._var_cat.get()

        if service != "Tous":
            consommables = self.db.get_consommables_par_service(service)
        else:
            consommables = self.db.get_consommables()

        if cat != "Toutes":
            consommables = [c for c in consommables if c.categorie == cat]

        self._tree.delete(*self._tree.get_children())
        for c in consommables:
            tag = c.categorie
            self._tree.insert("", "end", iid=c.id, tags=(tag,),
                               values=(c.nom, c.categorie, c.service,
                                       f"{c.cout_unitaire:.4f} $/{c.unite_mesure}"))

        # Colorisation par catégorie
        for cat_key, couleur in self.COULEURS_CAT.items():
            self._tree.tag_configure(cat_key, background=couleur)

    def _charger_dans_formulaire(self, c: Consommable):
        """Remplit le formulaire avec un consommable existant."""
        self._var_id.set(c.id)
        self._var_nom.set(c.nom)
        self._var_categorie.set(c.categorie)
        self._var_service_form.set(c.service)
        self._var_unite.set(c.unite_mesure)
        self._var_cout.set(str(c.cout_unitaire))
        self._txt_description.delete("1.0", tk.END)
        self._txt_description.insert("1.0", c.description)
        self._btn_suppr.config(state="normal")

    def _lire_formulaire(self):
        """Lit et valide les champs. Retourne un dict ou lève ValueError."""
        nom = self._var_nom.get().strip()
        if not nom:
            raise ValueError("Le nom du produit est obligatoire.")

        # ID : conserve l'existant en édition, génère un nouveau à la création
        if self._consommable_selectionne:
            id_val = self._consommable_selectionne.id
        else:
            id_val = self._generer_id_unique(nom)
            self._var_id.set(id_val)  # affiche l'ID généré

        try:
            cout = float(self._var_cout.get().replace(",", "."))
            if cout < 0:
                raise ValueError()
        except ValueError:
            raise ValueError("Le coût doit être un nombre positif.")

        return {
            "id":           id_val,
            "nom":          nom,
            "categorie":    self._var_categorie.get(),
            "service":      self._var_service_form.get(),
            "unite_mesure": self._var_unite.get(),
            "cout_unitaire": cout,
            "description":  self._txt_description.get("1.0", tk.END).strip(),
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _nouveau(self):
        """Vide le formulaire pour créer un nouveau consommable."""
        self._consommable_selectionne = None
        self._var_id.set("— généré à la sauvegarde —")
        self._var_nom.set("")
        self._var_categorie.set(Consommable.CATEGORIES[0])
        self._var_service_form.set("CTS")
        self._var_unite.set(Consommable.UNITES[0])
        self._var_cout.set("0.0")
        self._txt_description.delete("1.0", tk.END)
        self._btn_suppr.config(state="disabled")
        self._tree.selection_remove(self._tree.selection())

    def _on_selection(self, _event=None):
        """Charge le consommable sélectionné dans le formulaire."""
        sel = self._tree.selection()
        if not sel:
            return
        cid = sel[0]
        c = self.db.get_consommable(cid)
        if c:
            self._consommable_selectionne = c
            self._charger_dans_formulaire(c)

    def _sauvegarder(self):
        """Crée ou met à jour le consommable."""
        try:
            data = self._lire_formulaire()
        except ValueError as e:
            messagebox.showerror("Erreur de saisie", str(e), parent=self)
            return

        self.db.ajouter_consommable(**data)
        self._rafraichir_liste()

        # Re-sélectionner l'élément sauvegardé
        try:
            self._tree.selection_set(data["id"])
            self._tree.see(data["id"])
        except tk.TclError:
            pass  # l'élément peut être filtré

        messagebox.showinfo("Succès",
                            f"Consommable « {data['nom']} » sauvegardé.",
                            parent=self)

    def _supprimer(self):
        """Vérifie les protocoles impactés puis supprime si confirmation."""
        if not self._consommable_selectionne:
            return

        c = self._consommable_selectionne
        protocoles_touches = self.db.get_protocoles_utilisant(c.id)

        if protocoles_touches:
            # Résolution des noms de protocoles depuis le JSON si possible
            noms = self._resoudre_noms_protocoles(protocoles_touches)
            liste = "\n".join(f"  • {n}" for n in noms)
            messagebox.showwarning(
                "Suppression impossible",
                f"Le consommable « {c.nom} » est utilisé dans le(s) protocole(s) suivant(s) :\n\n"
                f"{liste}\n\n"
                f"Retirez-le de ces protocoles avant de le supprimer.",
                parent=self
            )
            return

        if not messagebox.askyesno(
            "Confirmer la suppression",
            f"Supprimer définitivement « {c.nom} » ?\n\nCette action est irréversible.",
            parent=self
        ):
            return

        self.db.supprimer_consommable(c.id)
        self._nouveau()
        self._rafraichir_liste()
        messagebox.showinfo("Supprimé",
                            f"« {c.nom} » a été supprimé.",
                            parent=self)

    def _resoudre_noms_protocoles(self, ids: list) -> list:
        """Convertit les IDs de protocoles en noms lisibles si possible."""
        if self.config_manager:
            catalogue = self.config_manager.get_catalog_protocoles()
            return [catalogue.get(pid, {}).get("nom", pid) or pid for pid in ids]
        return ids
