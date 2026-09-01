"""Fenêtre de gestion des horaires hebdomadaires du personnel."""
import tkinter as tk
from tkinter import ttk, messagebox
import ui.theme as theme

JOURS_ABBR = ["L", "M", "Me", "J", "V", "S", "D"]
JOURS_LONG = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# Largeurs minimales des colonnes (pixels) :
# [Nom, L, M, Me, J, V, S, D, Début(h), Fin(h), Pause deb, Pause fin, Pool garde, Actif]
_COL_MINSIZE = [160, 30, 30, 34, 30, 30, 30, 30, 70, 70, 70, 70, 60, 48]


class FenetreHoraires:
    """Popup de gestion des horaires hebdomadaires par technicien.

    Structure JSON sauvegardée :
        config["horaires"] = {
            "<nom_tech>": {
                "jours": [0,1,2,3,4],   # indices 0=L … 6=D
                "heure_debut": 7,        # heure décimale (ex: 7.5 = 07h30)
                "heure_fin":  15,        # idem ; si debut > fin → quart de nuit
                "pause_debut": 12.0,     # début pause déj (heure déc.)
                "pause_fin":   13.0,     # fin pause déj
                "pool_garde":  false,    # true = éligible aux gardes week-end
                "actif": true
            }
        }
        config["personnel"] = {
            "jour_debut_simulation": 0,         # 0=Lundi
            "pause_rotation_auto": false,
            "pause_creneau_debut": 12.0,
            "pause_duree_minutes": 30,
            "garde_trajet_minutes": 20,
            "garde_forfait_heures": 3,
            "garde_samedi":   "Rotation auto",  # nom du tech, "Rotation auto" ou "Personne"
            "garde_dimanche": "Rotation auto",
            "garde_feries":   "Personne"
        }
    """

    def __init__(self, parent, config_manager):
        self.config_manager = config_manager
        self._rows = []

        self.win = tk.Toplevel(parent)
        self.win.title("🗓️  Horaires du personnel")
        self.win.geometry("1250x660")
        self.win.minsize(1250, 500)
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
            font=theme.FONT_TITLE,
            pady=8,
        ).pack(fill="x", padx=12)
        tk.Frame(self.win, bg="#d5d8dc", height=1).pack(fill="x")

        # ── Jour de départ de simulation ──────────────────────────────────
        bar = tk.Frame(self.win, pady=6, padx=12)
        bar.pack(fill="x")
        tk.Label(bar, text="Simulation démarre un :", font=theme.FONT_BODY).pack(
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
            bar, text="(J0 = t=0 en SimPy)", foreground="gray", font=theme.FONT_NOTE
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
        self.win.bind("<Destroy>", self._on_destroy)

        # Toutes les colonnes partagent la même configuration
        for c, w in enumerate(_COL_MINSIZE):
            self.frm_table.columnconfigure(c, minsize=w, weight=0)
        self.frm_table.columnconfigure(0, minsize=_COL_MINSIZE[0], weight=1)

        # ── Configuration pauses & gardes ────────────────────────────────────
        tk.Frame(self.win, bg="#d5d8dc", height=1).pack(fill="x")
        frm_cfg = tk.Frame(self.win, pady=5, padx=10)
        frm_cfg.pack(fill="x")

        frm_pauses = tk.LabelFrame(frm_cfg, text="🍽️  Pauses déjeuner",
                                   font=theme.FONT_LABEL, padx=8, pady=4)
        frm_pauses.pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 6))

        self.var_rotation_auto = tk.BooleanVar()
        ttk.Checkbutton(frm_pauses, text="Rotation automatique (décaler chaque tech)",
                        variable=self.var_rotation_auto).grid(row=0, column=0, columnspan=4, sticky="w")
        tk.Label(frm_pauses, text="Créneau début :", font=theme.FONT_BODY).grid(
            row=1, column=0, sticky="w", padx=(0, 4))
        self.var_pause_debut_creneau = tk.StringVar(value="12.0")
        ttk.Entry(frm_pauses, textvariable=self.var_pause_debut_creneau, width=7,
                  justify="center").grid(row=1, column=1, padx=(0, 10))
        tk.Label(frm_pauses, text="Durée (min) :", font=theme.FONT_BODY).grid(
            row=1, column=2, sticky="w", padx=(0, 4))
        self.var_pause_duree = tk.StringVar(value="30")
        ttk.Entry(frm_pauses, textvariable=self.var_pause_duree, width=7,
                  justify="center").grid(row=1, column=3)
        tk.Label(frm_pauses,
                 text="💡 Si rotation auto cochée, les colonnes Pause deb/fin du tableau sont ignorées.",
                 foreground="#777", font=theme.FONT_NOTE, justify="left"
                 ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(3, 0))

        frm_gardes = tk.LabelFrame(frm_cfg, text="🔔  Gardes week-end & jours fériés",
                                   font=theme.FONT_LABEL, padx=8, pady=4)
        frm_gardes.pack(side=tk.LEFT, fill="x", expand=True)

        # Ligne 0 : trajet + forfait
        tk.Label(frm_gardes, text="Trajet (min) :", font=theme.FONT_BODY).grid(
            row=0, column=0, sticky="w", padx=(0, 4))
        self.var_trajet_garde = tk.StringVar(value="20")
        ttk.Entry(frm_gardes, textvariable=self.var_trajet_garde, width=7,
                  justify="center").grid(row=0, column=1, padx=(0, 12))
        tk.Label(frm_gardes, text="Forfait min (h) :", font=theme.FONT_BODY).grid(
            row=0, column=2, sticky="w", padx=(0, 4))
        self.var_forfait_heures = tk.StringVar(value="3")
        ttk.Entry(frm_gardes, textvariable=self.var_forfait_heures, width=7,
                  justify="center").grid(row=0, column=3)

        # Ligne 1 : qui est de garde S / D / Fériés
        tk.Label(frm_gardes, text="Samedi :", font=theme.FONT_BODY).grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        self.var_garde_samedi = tk.StringVar(value="Personne")
        self.combo_garde_samedi = ttk.Combobox(
            frm_gardes, textvariable=self.var_garde_samedi,
            values=["Personne", "Rotation auto"], state="readonly", width=16)
        self.combo_garde_samedi.grid(row=1, column=1, padx=(0, 12), pady=(6, 0))

        tk.Label(frm_gardes, text="Dimanche :", font=theme.FONT_BODY).grid(
            row=1, column=2, sticky="w", pady=(6, 0))
        self.var_garde_dimanche = tk.StringVar(value="Personne")
        self.combo_garde_dimanche = ttk.Combobox(
            frm_gardes, textvariable=self.var_garde_dimanche,
            values=["Personne", "Rotation auto"], state="readonly", width=16)
        self.combo_garde_dimanche.grid(row=1, column=3, padx=(0, 12), pady=(6, 0))

        tk.Label(frm_gardes, text="Jours fériés :", font=theme.FONT_BODY).grid(
            row=1, column=4, sticky="w", pady=(6, 0))
        self.var_garde_feries = tk.StringVar(value="Personne")
        self.combo_garde_feries = ttk.Combobox(
            frm_gardes, textvariable=self.var_garde_feries,
            values=["Personne", "Rotation auto"], state="readonly", width=16)
        self.combo_garde_feries.grid(row=1, column=5, pady=(6, 0))

        # Ligne 2 : bouton rotation auto
        ttk.Button(frm_gardes, text="🔄  Rotation auto S-D",
                   command=self._appliquer_rotation_auto_garde
                   ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        tk.Label(frm_gardes,
                 text="«Rotation auto» : la simulation tourne parmi tous les techs actifs, semaine par semaine.",
                 foreground="#555", font=theme.FONT_NOTE
                 ).grid(row=2, column=3, columnspan=3, sticky="w", pady=(6, 0))

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
            font=theme.FONT_NOTE,
            wraplength=1220,
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

    def _on_destroy(self, event=None):
        try:
            self._scroll_canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

    def _on_mousewheel(self, event):
        try:
            if self._scroll_canvas.winfo_exists():
                self._scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────
    def _creer_entete(self):
        """Ligne d'en-tête (row 0) dans frm_table, partagée avec les données."""
        headers = ["Technicien"] + JOURS_ABBR + ["Début (h)", "Fin (h)", "Pause deb", "Pause fin", "Pool garde 🔔", "Actif"]
        for c, texte in enumerate(headers):
            tk.Label(
                self.frm_table,
                text=texte,
                font=theme.FONT_LABEL,
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

        # Charger paramètres globaux pauses / gardes
        self.var_rotation_auto.set(personnel.get("pause_rotation_auto", False))
        self.var_pause_debut_creneau.set(str(personnel.get("pause_creneau_debut", 12.0)))
        self.var_pause_duree.set(str(int(personnel.get("pause_duree_minutes", 30))))
        self.var_trajet_garde.set(str(int(personnel.get("garde_trajet_minutes", 20))))
        self.var_forfait_heures.set(str(personnel.get("garde_forfait_heures", 3.0)))

        # Jour de départ — lu avant de bâtir les lignes ; les combos gardes
        # seront peuplés APRÈS la boucle techs (cf. fin de _charger)
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
                font=theme.FONT_BODY,
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

            row = {"_key": key, "_nom": nom, "jours": [], "debut": None, "fin": None,
                   "pool_garde": None, "actif": None}

            # Col 0 : nom
            tk.Label(
                self.frm_table,
                text=nom,
                anchor="w",
                font=theme.FONT_LABEL,
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

            # Col 10 : pause début
            pause_deb_val = h_cfg.get("pause_debut", 12.0)
            var_pause_deb = tk.StringVar(value=str(pause_deb_val))
            ttk.Entry(
                self.frm_table, textvariable=var_pause_deb, width=6, justify="center"
            ).grid(row=data_row, column=10, sticky="ew", padx=6, pady=3)
            row["pause_debut"] = var_pause_deb

            # Col 11 : pause fin
            pause_fin_val = h_cfg.get("pause_fin", 13.0)
            var_pause_fin = tk.StringVar(value=str(pause_fin_val))
            ttk.Entry(
                self.frm_table, textvariable=var_pause_fin, width=6, justify="center"
            ).grid(row=data_row, column=11, sticky="ew", padx=6, pady=3)
            row["pause_fin"] = var_pause_fin

            # Col 12 : pool garde
            var_pool = tk.BooleanVar(value=h_cfg.get("pool_garde", False))
            cell_pool = tk.Frame(self.frm_table, bg=bg)
            cell_pool.grid(row=data_row, column=12, sticky="nsew", padx=1, pady=1)
            ttk.Checkbutton(cell_pool, variable=var_pool).pack(expand=True)
            row["pool_garde"] = var_pool

            # Col 13 : actif — wrapper centré
            var_actif = tk.BooleanVar(value=actif)
            cell_actif = tk.Frame(self.frm_table, bg=bg)
            cell_actif.grid(row=data_row, column=13, sticky="nsew", padx=1, pady=1)
            ttk.Checkbutton(cell_actif, variable=var_actif).pack(expand=True)
            row["actif"] = var_actif

            self._rows.append(row)

        # ── Peupler les combos gardes avec les noms de techs ──────────────
        noms_techs = [r["_nom"] for r in self._rows]
        options = ["Personne", "Rotation auto"] + noms_techs
        self.combo_garde_samedi["values"]   = options
        self.combo_garde_dimanche["values"] = options
        self.combo_garde_feries["values"]   = options
        self.var_garde_samedi.set(personnel.get("garde_samedi",   "Personne"))
        self.var_garde_dimanche.set(personnel.get("garde_dimanche", "Personne"))
        self.var_garde_feries.set(personnel.get("garde_feries",   "Personne"))

    # ──────────────────────────────────────────────────────────────────────
    def _appliquer_rotation_auto_garde(self):
        """Met les trois combos à 'Rotation auto' en un clic."""
        self.var_garde_samedi.set("Rotation auto")
        self.var_garde_dimanche.set("Rotation auto")
        self.var_garde_feries.set("Rotation auto")

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
                debut     = float(row["debut"].get())
                fin       = float(row["fin"].get())
                pause_deb = float(row["pause_debut"].get())
                pause_fin = float(row["pause_fin"].get())
            except ValueError:
                messagebox.showwarning(
                    "Erreur de saisie",
                    f"Heures invalides pour « {nom} ».\n"
                    "Veuillez entrer des nombres (ex : 7, 7.5, 12).",
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
                "pause_debut": pause_deb,
                "pause_fin":   pause_fin,
                "pool_garde":  row["pool_garde"].get(),
                "actif":       row["actif"].get(),
            }

        # Paramètres globaux pauses / gardes
        try:
            cfg["personnel"]["pause_rotation_auto"]  = self.var_rotation_auto.get()
            cfg["personnel"]["pause_creneau_debut"]  = float(self.var_pause_debut_creneau.get())
            cfg["personnel"]["pause_duree_minutes"]  = int(float(self.var_pause_duree.get()))
            cfg["personnel"]["garde_trajet_minutes"] = int(float(self.var_trajet_garde.get()))
            cfg["personnel"]["garde_forfait_heures"] = float(self.var_forfait_heures.get())
            cfg["personnel"]["garde_samedi"]         = self.var_garde_samedi.get()
            cfg["personnel"]["garde_dimanche"]       = self.var_garde_dimanche.get()
            cfg["personnel"]["garde_feries"]         = self.var_garde_feries.get()
        except ValueError:
            messagebox.showwarning("Erreur de saisie",
                                   "Paramètres pauses/gardes invalides (nombres attendus).")
            return

        self.config_manager.sauvegarder()
        messagebox.showinfo(
            "Sauvegardé",
            "Horaires enregistrés avec succès.\n"
            "Les changements seront pris en compte au prochain démarrage de simulation.",
        )
