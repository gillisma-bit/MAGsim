"""Fenêtre de gestion des horaires hebdomadaires du personnel."""
import tkinter as tk
from tkinter import ttk, messagebox

JOURS_ABBR = ["L", "M", "Me", "J", "V", "S", "D"]
JOURS_LONG = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# Largeurs de colonnes (pixels) pour l'alignement
_COL_WIDTHS = [140, 36, 36, 40, 36, 36, 36, 36, 72, 72, 52]


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
        self.win.geometry("860x480")
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
            bar,
            text="(J0 = t=0 en SimPy)",
            foreground="gray",
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT)

        tk.Frame(self.win, bg="#d5d8dc", height=1).pack(fill="x")

        # ── Zone tableau ──────────────────────────────────────────────────
        frm_outer = tk.Frame(self.win)
        frm_outer.pack(fill="both", expand=True, padx=10, pady=(6, 0))

        # En-tête fixe
        frm_head = tk.Frame(frm_outer, bg="#2c3e50")
        frm_head.pack(fill="x")
        self._creer_entete(frm_head)

        # Lignes (scrollable)
        scroll_canvas = tk.Canvas(frm_outer, highlightthickness=0)
        vsb = ttk.Scrollbar(frm_outer, orient="vertical", command=scroll_canvas.yview)
        self.frm_rows = tk.Frame(scroll_canvas)
        self.frm_rows.bind(
            "<Configure>",
            lambda e: scroll_canvas.configure(
                scrollregion=scroll_canvas.bbox("all")
            ),
        )
        scroll_canvas.create_window((0, 0), window=self.frm_rows, anchor="nw")
        scroll_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill="y")
        scroll_canvas.pack(fill="both", expand=True)

        # ── Note d'aide ────────────────────────────────────────────────────
        note = (
            "💡  Début > Fin = quart de nuit (ex: 16h→8h couvre la nuit).  "
            "Heures décimales acceptées (ex: 7.5 = 07h30).  "
            "Décocher « Actif » désactive le technicien pour toute la simulation."
        )
        tk.Label(
            self.win,
            text=note,
            foreground="#555",
            font=("Segoe UI", 8),
            wraplength=820,
            justify="left",
            pady=4,
        ).pack(fill="x", padx=10)

        # ── Boutons ────────────────────────────────────────────────────────
        bas = tk.Frame(self.win, pady=8)
        bas.pack(fill="x")
        ttk.Button(
            bas, text="💾  Sauvegarder", command=self._sauvegarder, padding=8
        ).pack(side=tk.RIGHT, padx=12)
        ttk.Button(
            bas, text="Fermer", command=self.win.destroy, padding=8
        ).pack(side=tk.RIGHT, padx=4)

    # ──────────────────────────────────────────────────────────────────────
    def _creer_entete(self, parent):
        en_tetes = (
            ["Technicien"] + JOURS_ABBR + ["Début (h)", "Fin (h)", "Actif"]
        )
        for c, (texte, larg) in enumerate(zip(en_tetes, _COL_WIDTHS)):
            tk.Label(
                parent,
                text=texte,
                font=("Segoe UI", 9, "bold"),
                bg="#2c3e50",
                fg="white",
                width=larg // 8,
                relief="flat",
                pady=5,
            ).grid(row=0, column=c, padx=1, pady=0, sticky="ew")

    # ──────────────────────────────────────────────────────────────────────
    def _charger(self):
        """Construit les lignes du tableau depuis la config actuelle."""
        for w in self.frm_rows.winfo_children():
            w.destroy()
        self._rows = []

        cfg = self.config_manager.data
        machines = cfg.get("machines", {})
        horaires = cfg.get("horaires", {})
        personnel = cfg.get("personnel", {})

        # Jour de départ
        jour_idx = int(personnel.get("jour_debut_simulation", 0))
        self.var_jour_debut.set(JOURS_LONG[min(max(jour_idx, 0), 6)])

        # Filtrer les TECH_OFFICE
        techs = [
            (k, v)
            for k, v in machines.items()
            if v.get("type") == "TECH_OFFICE"
        ]

        if not techs:
            tk.Label(
                self.frm_rows,
                text="Aucun technicien (TECH_OFFICE) défini dans le plan.",
                foreground="#e74c3c",
                font=("Segoe UI", 9),
                pady=15,
            ).grid(row=0, column=0, columnspan=12)
            return

        for row_idx, (key, m) in enumerate(techs):
            nom = m.get("nom") or key
            h_cfg = horaires.get(nom, {})

            jours_actifs = h_cfg.get("jours", list(range(5)))  # L–V par défaut
            debut = h_cfg.get("heure_debut", 7)
            fin = h_cfg.get("heure_fin", 15)
            actif = h_cfg.get("actif", True)

            bg = "#ffffff" if row_idx % 2 == 0 else "#eaf0fb"

            row = {
                "_key": key,
                "_nom": nom,
                "jours": [],
                "debut": None,
                "fin": None,
                "actif": None,
            }

            # Nom du technicien
            tk.Label(
                self.frm_rows,
                text=nom,
                anchor="w",
                font=("Segoe UI", 9, "bold"),
                bg=bg,
                relief="groove",
                padx=8,
                width=_COL_WIDTHS[0] // 8,
            ).grid(row=row_idx, column=0, padx=1, pady=2, sticky="ew")

            # Cases à cocher de jours (L M Me J V S D)
            for j_idx in range(7):
                var = tk.BooleanVar(value=(j_idx in jours_actifs))
                ttk.Checkbutton(
                    self.frm_rows, variable=var
                ).grid(row=row_idx, column=1 + j_idx, padx=2, pady=2)
                row["jours"].append(var)

            # Heure de début
            var_deb = tk.StringVar(value=str(debut))
            ttk.Entry(
                self.frm_rows, textvariable=var_deb, width=7, justify="center"
            ).grid(row=row_idx, column=8, padx=4, pady=2)
            row["debut"] = var_deb

            # Heure de fin
            var_fin = tk.StringVar(value=str(fin))
            ttk.Entry(
                self.frm_rows, textvariable=var_fin, width=7, justify="center"
            ).grid(row=row_idx, column=9, padx=4, pady=2)
            row["fin"] = var_fin

            # Actif (checkbox)
            var_actif = tk.BooleanVar(value=actif)
            ttk.Checkbutton(
                self.frm_rows, variable=var_actif
            ).grid(row=row_idx, column=10, padx=4, pady=2)
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
            jours = [i for i, v in enumerate(row["jours"]) if v.get()]

            try:
                debut = float(row["debut"].get())
                fin = float(row["fin"].get())
            except ValueError:
                messagebox.showwarning(
                    "Erreur de saisie",
                    f"Heures invalides pour « {nom} ».\n"
                    "Veuillez entrer des nombres (ex: 7, 7.5, 16).",
                )
                return

            if not (0.0 <= debut < 24.0) or not (0.0 < fin <= 24.0):
                messagebox.showwarning(
                    "Heure hors plage",
                    f"Heures de « {nom} » hors plage 0–24.",
                )
                return

            cfg["horaires"][nom] = {
                "jours": jours,
                "heure_debut": debut,
                "heure_fin": fin,
                "actif": row["actif"].get(),
            }

        self.config_manager.sauvegarder()
        messagebox.showinfo(
            "Sauvegardé", "Horaires enregistrés avec succès.\n"
            "Les changements seront pris en compte au prochain démarrage de simulation."
        )
