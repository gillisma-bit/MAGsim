"""Fenêtre de gestion des horaires hebdomadaires du personnel."""
import tkinter as tk
from tkinter import ttk, messagebox

JOURS_ABBR = ["L", "M", "Me", "J", "V", "S", "D"]
JOURS_LONG = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# Largeurs minimales des colonnes (pixels) :
# [Nom, L, M, Me, J, V, S, D, Début(h), Fin(h), Actif]
_COL_MINSIZE = [160, 30, 30, 34, 30, 30, 30, 30, 70, 70, 48]


class FenetreHoraires:
    """Popup de gestion des horaires hebdomadaires par technicien.

    Structure JSON sauvegardée :
        config["horaires"] = {
            "<nom_tech>": {
                "jours": [0,1,2,3,4],   # indices 0=L … 6=D
                "heure_debut": 7,        # heure décimale (ex: 7.5 = 07h30)
                "heure_fin":  15,        # idem ; si debut > fin → quart de nuit
                "actif": true
            }
        }
        config["personnel"]["jour_debut_simulation"] = 0  # 0=Lundi
    """

    def __init__(self, parent, config_manager):
        self.config_manager = config_manager
        self._rows = []

        self.win = tk.Toplevel(parent)
        self.win.title("🗓️  Horaires du personnel")
        self.win.geometry("700x460")
        self.win.resizable(True, True)
        self.win.grab_set()

        self._build_ui()
        self._charger()

    # ──────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Titre ─────────────────────────────────────────────────────────
        tk.Label(
            self.win,
            text="🗓️  Horaires hebdomadaires du personnel",
            font=("Segoe UI", 13, "bold"),
            pady=8,
        ).pack(fill="x", padx=12)
        tk.Frame(self.win, bg="#d5d8dc", height=1).pack(fill="x")

        # ── Jour de départ de simulation ──────────────────────────────────
        bar = tk.Frame(self.win, pady=6, padx=12)
        bar.pack(fill="x")
        tk.Label(bar, text="Simulation démarre un :", font=("Segoe UI", 9)).pack(
            side=tk.LEFT
        )
        self.var_jour_debut = tk.StringVar()
        ttk.Combobox(
            bar,
            textvariable=self.var_jour_debut,
            values=JOURS_LONG,
            state="readonly",
            width=14,
        ).pack(side=tk.LEFT, padx=8)
        tk.Label(
            bar, text="(J0 = t=0 en SimPy)", foreground="gray", font=("Segoe UI", 8)
        ).pack(side=tk.LEFT)

        tk.Frame(self.win, bg="#d5d8dc", height=1).pack(fill="x")

        # ── Zone tableau scrollable ────────────────────────────────────────
        # Header ET lignes de données dans le MÊME frm_table → alignement garanti
        frm_outer = tk.Frame(self.win)
        frm_outer.pack(fill="both", expand=True, padx=10, pady=(4, 0))

        self._scroll_canvas = tk.Canvas(frm_outer, highlightthickness=0)
        vsb = ttk.Scrollbar(frm_outer, orient="vertical", command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill="y")
        self._scroll_canvas.pack(side=tk.LEFT, fill="both", expand=True)

        # Frame unique pour header + données
        self.frm_table = tk.Frame(self._scroll_canvas)
        self._scroll_canvas.create_window((0, 0), window=self.frm_table, anchor="nw")
        self.frm_table.bind(
            "<Configure>",
            lambda e: self._scroll_canvas.configure(
                scrollregion=self._scroll_canvas.bbox("all")
            ),
        )
        self._scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # Toutes les colonnes partagent la même configuration
        for c, w in enumerate(_COL_MINSIZE):
            self.frm_table.columnconfigure(c, minsize=w, weight=0)
        self.frm_table.columnconfigure(0, minsize=_COL_MINSIZE[0], weight=1)

        # ── Note d'aide ────────────────────────────────────────────────────
        note = (
            "💡  Début > Fin = quart de nuit (ex : 16 → 8).  "
            "Décimales acceptées (ex : 7.5 = 07h30).  "
            "Décocher « Actif » désactive le technicien pour toute la simulation."
        )
        tk.Label(
            self.win,
            text=note,
            foreground="#555",
            font=("Segoe UI", 8),
            wraplength=680,
            justify="left",
            pady=4,
        ).pack(fill="x", padx=10)

        # ── Boutons ────────────────────────────────────────────────────────
        bas = tk.Frame(self.win, pady=8)
        bas.pack(fill="x")
        ttk.Button(bas, text="💾  Sauvegarder", command=self._sauvegarder, padding=8).pack(
            side=tk.RIGHT, padx=12
        )
        ttk.Button(bas, text="Fermer", command=self.win.destroy, padding=8).pack(
            side=tk.RIGHT, padx=4
        )

    def _on_mousewheel(self, event):
        self._scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ──────────────────────────────────────────────────────────────────────
    def _creer_entete(self):
        """Ligne d'en-tête (row 0) dans frm_table, partagée avec les données."""
        headers = ["Technicien"] + JOURS_ABBR + ["Début (h)", "Fin (h)", "Actif"]
        for c, texte in enumerate(headers):
            tk.Label(
                self.frm_table,
                text=texte,
                font=("Segoe UI", 9, "bold"),
                bg="#2c3e50",
                fg="white",
                anchor="center",
                pady=6,
                padx=4,
            ).grid(row=0, column=c, sticky="nsew", padx=1, pady=0)

        # Ligne séparatrice
        tk.Frame(self.frm_table, bg="#7f8c8d", height=2).grid(
            row=1, column=0, columnspan=len(headers), sticky="ew"
        )

    # ──────────────────────────────────────────────────────────────────────
    def _charger(self):
        """Construit le tableau complet depuis la config actuelle."""
        for w in self.frm_table.winfo_children():
            w.destroy()
        self._rows = []

        cfg = self.config_manager.data
        machines = cfg.get("machines", {})
        horaires = cfg.get("horaires", {})
        personnel = cfg.get("personnel", {})

        # Jour de départ
        jour_idx = int(personnel.get("jour_debut_simulation", 0))
        self.var_jour_debut.set(JOURS_LONG[min(max(jour_idx, 0), 6)])

        # En-tête recréé après vidage
        self._creer_entete()

        # Filtrer les TECH_OFFICE
        techs = [(k, v) for k, v in machines.items() if v.get("type") == "TECH_OFFICE"]

        if not techs:
            tk.Label(
                self.frm_table,
                text="Aucun technicien (TECH_OFFICE) défini dans le plan.",
                foreground="#e74c3c",
                font=("Segoe UI", 9),
                pady=15,
            ).grid(row=2, column=0, columnspan=11)
            return

        # Données : row=2 et suivantes (0=header, 1=séparateur)
        for i, (key, m) in enumerate(techs):
            nom = m.get("nom") or key
            h_cfg = horaires.get(nom, {})

            jours_actifs = h_cfg.get("jours", list(range(5)))
            debut        = h_cfg.get("heure_debut", 7)
            fin          = h_cfg.get("heure_fin",   15)
            actif        = h_cfg.get("actif", True)

            bg = "#ffffff" if i % 2 == 0 else "#eaf0fb"
            data_row = i + 2  # décalage : 0=header, 1=séparateur

            row = {"_key": key, "_nom": nom, "jours": [], "debut": None, "fin": None, "actif": None}

            # Col 0 : nom
            tk.Label(
                self.frm_table,
                text=nom,
                anchor="w",
                font=("Segoe UI", 9, "bold"),
                bg=bg,
                padx=10,
                pady=5,
            ).grid(row=data_row, column=0, sticky="nsew", padx=1, pady=1)

            # Col 1–7 : cases jours — wrapper centré dans la cellule
            for j in range(7):
                var = tk.BooleanVar(value=(j in jours_actifs))
                cell = tk.Frame(self.frm_table, bg=bg)
                cell.grid(row=data_row, column=1 + j, sticky="nsew", padx=1, pady=1)
                ttk.Checkbutton(cell, variable=var).pack(expand=True)
                row["jours"].append(var)

            # Col 8 : heure de début
            var_deb = tk.StringVar(value=str(debut))
            ttk.Entry(
                self.frm_table, textvariable=var_deb, width=6, justify="center"
            ).grid(row=data_row, column=8, sticky="ew", padx=6, pady=3)
            row["debut"] = var_deb

            # Col 9 : heure de fin
            var_fin = tk.StringVar(value=str(fin))
            ttk.Entry(
                self.frm_table, textvariable=var_fin, width=6, justify="center"
            ).grid(row=data_row, column=9, sticky="ew", padx=6, pady=3)
            row["fin"] = var_fin

            # Col 10 : actif — wrapper centré
            var_actif = tk.BooleanVar(value=actif)
            cell_actif = tk.Frame(self.frm_table, bg=bg)
            cell_actif.grid(row=data_row, column=10, sticky="nsew", padx=1, pady=1)
            ttk.Checkbutton(cell_actif, variable=var_actif).pack(expand=True)
            row["actif"] = var_actif

            self._rows.append(row)

    # ──────────────────────────────────────────────────────────────────────
    def _sauvegarder(self):
        """Valide et enregistre les horaires dans la config."""
        cfg = self.config_manager.data
        cfg.setdefault("horaires", {})
        cfg.setdefault("personnel", {})

        # Jour de départ de simulation
        jd = self.var_jour_debut.get()
        cfg["personnel"]["jour_debut_simulation"] = (
            JOURS_LONG.index(jd) if jd in JOURS_LONG else 0
        )

        for row in self._rows:
            nom = row["_nom"]
            jours = [j for j, v in enumerate(row["jours"]) if v.get()]

            try:
                debut = float(row["debut"].get())
                fin   = float(row["fin"].get())
            except ValueError:
                messagebox.showwarning(
                    "Erreur de saisie",
                    f"Heures invalides pour « {nom} ».\n"
                    "Veuillez entrer des nombres (ex : 7, 7.5, 16).",
                )
                return

            if not (0.0 <= debut < 24.0) or not (0.0 < fin <= 24.0):
                messagebox.showwarning(
                    "Heure hors plage",
                    f"Heures de « {nom} » hors plage 0–24.",
                )
                return

            cfg["horaires"][nom] = {
                "jours":       jours,
                "heure_debut": debut,
                "heure_fin":   fin,
                "actif":       row["actif"].get(),
            }

        self.config_manager.sauvegarder()
        messagebox.showinfo(
            "Sauvegardé",
            "Horaires enregistrés avec succès.\n"
            "Les changements seront pris en compte au prochain démarrage de simulation.",
        )
