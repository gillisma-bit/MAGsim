import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
from ui.dialog_rh import FenetreRH
import ui.theme as theme

# Tailles par défaut (largeur_cases × hauteur_cases) pour chaque type de machine
_TAILLES_DEFAUT = {
    "Centrifugeuse":    (1, 1),
    "Automate":         (2, 1),
    "Paillasse":        (2, 1),
    "Incubateur":       (1, 1),
    "Réfrigérateur":    (1, 2),
    "Laveur de plaque": (2, 1),
    "Lecteur de plaque":(1, 1),
    "Bain-marie":       (1, 1),
    "Agitateur":        (1, 1),
    "Microscope":       (1, 1),
    "Hotte":            (3, 1),
    "Congélateur":      (1, 2),
    "ENTREE":           (1, 1),
    "SORTIE":           (1, 1),
    "REPOS":            (1, 1),
}

from ui._tabconfigpopup import _TabConfigPopup
from ui._tabconfigworkflow import _TabConfigWorkflow


class TabConfig(_TabConfigPopup, _TabConfigWorkflow):
    def __init__(self, parent, config_manager):
        self.parent = parent
        self.config_manager = config_manager
        self.selected_machine = None

        # --- DRAG & DROP ---
        self._drag_machine = None   # nom de la machine en cours de drag
        self._drag_last_x  = 0     # dernière position canvas x
        self._drag_last_y  = 0     # dernière position canvas y
        self._drag_moved   = False  # déplacement réel (vs simple clic)

        # --- PARAMÈTRES MÉTRIQUES ---
        self.grid_size = 50  # 1 carreau = 50px = 50cm
        self.mode = "SELECT" 
        
        self.paned = ttk.PanedWindow(self.parent, orient=tk.HORIZONTAL)
        self.paned.pack(expand=True, fill="both")
        
        # --- GAUCHE : LE PLAN ---
        self.canvas_frame = ttk.Frame(self.paned)
        self.paned.add(self.canvas_frame, weight=4)
        
        self.canvas = tk.Canvas(self.canvas_frame, bg="#ffffff", scrollregion=(0, 0, 3000, 2000))
        self.canvas.pack(expand=True, fill="both")
        
        # --- DROITE : OUTILS ---
        self.edit_frame = ttk.Frame(self.paned, padding=15)
        self.paned.add(self.edit_frame, weight=1)
        
        self.setup_ui_elements()
        self.dessiner_grille()
        
        # CRUCIAL : On charge l'existant APRÈS avoir défini les fonctions
        self.charger_config_existante()
        
        # Bindings
        self.canvas.bind("<Button-1>",        self.on_canvas_click)
        self.canvas.bind("<B1-Motion>",       self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

    def setup_ui_elements(self):
        ttk.Label(self.edit_frame, text="🏗️ ÉDITEUR MAGsim", font=theme.FONT_TITLE).pack(pady=(0, 10))
        
        # MODES DE DESSIN
        frame_modes = ttk.LabelFrame(self.edit_frame, text="Outils de sol", padding=10)
        frame_modes.pack(fill="x", pady=5)
        ttk.Button(frame_modes, text="🖱️ Sélection", command=lambda: self.set_mode("SELECT")).pack(fill="x", pady=2)
        ttk.Button(frame_modes, text="⬜ Comptoir (Gris)", command=lambda: self.set_mode("COUNTER")).pack(fill="x", pady=2)
        ttk.Button(frame_modes, text="⬛ Mur (Noir)", command=lambda: self.set_mode("WALL")).pack(fill="x", pady=2)
        ttk.Button(frame_modes, text="🧹 Gomme", command=lambda: self.set_mode("FLOOR")).pack(fill="x", pady=2)

        # Échelle du plan
        f_echelle = ttk.LabelFrame(self.edit_frame, text="📏 Échelle du plan", padding=8)
        f_echelle.pack(fill="x", pady=(8, 0))
        ttk.Label(f_echelle, text="1 case =", font=theme.FONT_BODY).grid(row=0, column=0, sticky="w")
        self.ent_mpc = ttk.Entry(f_echelle, width=6)
        ent_mpc_val = self.config_manager.data.get("personnel", {}).get("metres_par_case", 3.0)
        self.ent_mpc.insert(0, ent_mpc_val)
        self.ent_mpc.grid(row=0, column=1, padx=4)
        ttk.Label(f_echelle, text="mètres", font=theme.FONT_BODY).grid(row=0, column=2, sticky="w")
        ttk.Button(f_echelle, text="✓ Appliquer",
                   command=self._sauver_echelle).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(f_echelle, text="(1 case = 50 px)",
                  foreground="gray", font=theme.FONT_NOTE).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))

        # Personnel
        f_horaires = ttk.LabelFrame(self.edit_frame, text="👥 Personnel", padding=8)
        f_horaires.pack(fill="x", pady=(8, 0))
        ttk.Button(
            f_horaires,
            text="👥  Gérer le personnel",
            command=self._ouvrir_rh,
        ).pack(fill="x", pady=2)

        ttk.Separator(self.edit_frame).pack(fill="x", pady=15)

        # GESTION DES PROCÉDURES
        ttk.Label(self.edit_frame, text="🔬 PROCÉDURES", font=theme.FONT_SECTION).pack(anchor="w")
        ttk.Button(self.edit_frame, text="⚙️ Gérer les procédures de tubes", command=self.ouvrir_editeur_workflows).pack(fill="x", pady=5)

        ttk.Separator(self.edit_frame).pack(fill="x", pady=15)

        # AJOUT MACHINE
        ttk.Label(self.edit_frame, text="📦 MACHINE", font=theme.FONT_SECTION).pack(anchor="w")
        self.ent_nom = ttk.Entry(self.edit_frame)
        self.ent_nom.pack(fill="x", pady=5)
        
        self.combo_type = ttk.Combobox(self.edit_frame, values=[
            "Centrifugeuse", "Automate", "Paillasse",
            "Incubateur", "Réfrigérateur", "Laveur de plaque",
            "Lecteur de plaque", "Bain-marie", "Agitateur",
            "Microscope", "Hotte", "Congélateur",
            "ENTREE", "SORTIE", "REPOS",
        ])
        self.combo_type.pack(fill="x", pady=5)
        self.combo_type.set("Centrifugeuse")
        self.combo_type.bind("<<ComboboxSelected>>", self._on_type_change)

        # Dimensions avant placement
        f_dim_pre = ttk.LabelFrame(self.edit_frame, text="📐 Dimensions (cases)", padding=6)
        f_dim_pre.pack(fill="x", pady=(0, 4))
        f_dim_row = ttk.Frame(f_dim_pre)
        f_dim_row.pack(fill="x")
        ttk.Label(f_dim_row, text="Larg :").pack(side="left")
        self.spin_larg = ttk.Spinbox(f_dim_row, from_=1, to=10, width=4)
        self.spin_larg.pack(side="left", padx=(2, 8))
        ttk.Label(f_dim_row, text="Haut :").pack(side="left")
        self.spin_haut = ttk.Spinbox(f_dim_row, from_=1, to=10, width=4)
        self.spin_haut.pack(side="left", padx=2)
        # Valeurs par défaut du premier type
        larg0, haut0 = _TAILLES_DEFAUT.get("Centrifugeuse", (1, 1))
        self.spin_larg.set(larg0)
        self.spin_haut.set(haut0)
        ttk.Label(f_dim_pre, text="(auto selon type — modifiez si besoin)",
                  foreground="gray", font=("Segoe UI", 7)).pack(anchor="w")

        ttk.Button(self.edit_frame, text="📍 Placer au centre", command=lambda: self.set_mode("PLACE_MACHINE")).pack(fill="x", pady=10)

        # Bouton Supprimer (en rouge pour la sécurité)
        self.btn_suppr = tk.Button(self.edit_frame, text="🗑️ Supprimer la sélection",
                                   bg=theme.BTN_DEL_BG, fg=theme.BTN_DEL_FG,
                                   font=theme.FONT_BTN_DEL,
                                   command=self.supprimer_selection)
        self.btn_suppr.pack(fill="x", pady=5)

    def _sauver_echelle(self):
        try:
            mpc = max(0.1, float(self.ent_mpc.get()))
        except ValueError:
            return
        if "personnel" not in self.config_manager.data:
            self.config_manager.data["personnel"] = {}
        self.config_manager.data["personnel"]["metres_par_case"] = mpc
        self.config_manager.sauvegarder()

    def _ouvrir_rh(self):
        FenetreRH(self.parent, self.config_manager,
                  refresh_callback=self._refresh_plan_machines)

    def set_mode(self, mode):
        self.mode = mode
        self.canvas.config(cursor="crosshair" if mode != "SELECT" else "")

    def dessiner_grille(self):
        for i in range(0, 3000, self.grid_size):
            color = "#f0f0f0" if i % 100 != 0 else "#d0d0d0"
            self.canvas.create_line(i, 0, i, 2000, fill=color, tags="grille")
            self.canvas.create_line(0, i, 3000, i, fill=color, tags="grille")

    def on_canvas_click(self, event):
        x_c = self.canvas.canvasx(event.x)
        y_c = self.canvas.canvasy(event.y)
        col, row = int(x_c // self.grid_size), int(y_c // self.grid_size)

        if self.mode == "PLACE_MACHINE":
            self.placer_machine_centree(col, row)
        elif self.mode in ["COUNTER", "WALL", "FLOOR"]:
            self.peindre_case(col, row)
        else:  # SELECT — préparer un éventuel drag
            self._drag_machine = None
            self._drag_moved   = False
            items = self.canvas.find_overlapping(x_c - 2, y_c - 2, x_c + 2, y_c + 2)
            for item in items:
                for t in self.canvas.gettags(item):
                    if t.startswith("obj_"):
                        self._drag_machine = t.replace("obj_", "")
                        self._drag_last_x  = x_c
                        self._drag_last_y  = y_c
                        self.selected_machine = self._drag_machine
                        self.canvas.config(cursor="fleur")
                        return

    def on_canvas_drag(self, event):
        if self.mode in ["COUNTER", "WALL", "FLOOR"]:
            x = self.canvas.canvasx(event.x)
            y = self.canvas.canvasy(event.y)
            self.peindre_case(int(x // self.grid_size), int(y // self.grid_size))
        elif self.mode == "SELECT" and self._drag_machine:
            x_c = self.canvas.canvasx(event.x)
            y_c = self.canvas.canvasy(event.y)
            dx  = x_c - self._drag_last_x
            dy  = y_c - self._drag_last_y
            self.canvas.move(f"obj_{self._drag_machine}", dx, dy)
            self._drag_last_x = x_c
            self._drag_last_y = y_c
            self._drag_moved  = True

    def on_canvas_release(self, event):
        """Finalise le drag (snap grille + sauvegarde) ou ouvre le popup (simple clic)."""
        if self.mode != "SELECT" or self._drag_machine is None:
            return

        nom = self._drag_machine

        if self._drag_moved:
            # ── Snap au centre de la case la plus proche ────────────────────
            bbox = self.canvas.bbox(f"obj_{nom}")
            if bbox:
                curr_cx = (bbox[0] + bbox[2]) / 2
                curr_cy = (bbox[1] + bbox[3]) / 2
                # Utiliser le dict brut pour inclure les machines en zone tampon
                raw_machines = self.config_manager.data.get("machines", {})
                m_snap = raw_machines.get(nom, {})
                larg_s = m_snap.get("largeur_cases", 1)
                haut_s = m_snap.get("hauteur_cases", 1)
                col = max(0, round(curr_cx / self.grid_size - larg_s / 2))
                row = max(0, round(curr_cy / self.grid_size - haut_s / 2))
                snap_cx = col * self.grid_size + larg_s * self.grid_size / 2
                snap_cy = row * self.grid_size + haut_s * self.grid_size / 2
                # Déplacement résiduel pour aligner précisément
                self.canvas.move(f"obj_{nom}", snap_cx - curr_cx, snap_cy - curr_cy)
                # Sauvegarder la nouvelle position (via dict brut pour éviter le filtre get_machines)
                if nom in raw_machines:
                    raw_machines[nom].setdefault("coords", {})
                    raw_machines[nom]["coords"]["x"] = snap_cx
                    raw_machines[nom]["coords"]["y"] = snap_cy
                    # Retirer le flag de staging si la machine vient de la zone tampon
                    if raw_machines[nom].get("en_attente_placement"):
                        raw_machines[nom].pop("en_attente_placement", None)
                        # Redessiner en couleur normale (sans tag staging)
                        self.canvas.delete(f"obj_{nom}")
                        self.dessiner_bloc_machine(snap_cx, snap_cy, nom, raw_machines[nom]["type"],
                                                   raw_machines[nom].get("largeur_cases"),
                                                   raw_machines[nom].get("hauteur_cases"))
                        self._dessiner_zone_staging()
                    self.config_manager.sauvegarder()
                    # Si c'est le marqueur REPOS, syncer dans personnel.zone_repos
                    if raw_machines[nom].get("type") == "REPOS":
                        self.config_manager.data.setdefault("personnel", {})["zone_repos"] = {
                            "x": snap_cx, "y": snap_cy
                        }
                        self.config_manager.sauvegarder()
        else:
            # Simple clic : ouvrir le popup de configuration
            self.ouvrir_popup_machine()

        self._drag_machine = None
        self._drag_moved   = False
        self.canvas.config(cursor="")

    def peindre_case(self, col, row):
        tag_case = f"tile_{col}_{row}"
        self.canvas.delete(tag_case)
        
        x1, y1 = col * self.grid_size, row * self.grid_size
        x2, y2 = x1 + self.grid_size, y1 + self.grid_size
        
        couleurs = {"COUNTER": "#ecf0f1", "WALL": "#2c3e50", "FLOOR": "#ffffff"}
        color = couleurs.get(self.mode, "#ffffff")
        
        if self.mode != "FLOOR":
            self.canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="#d0d0d0", tags=("sol", tag_case))
            self.canvas.tag_lower(tag_case)
        
        if hasattr(self.config_manager, 'sauver_tuile_sol'):
            self.config_manager.sauver_tuile_sol(col, row, self.mode)

    def _on_type_change(self, event=None):
        """Met à jour les spinbox Larg/Haut quand on change le type de machine."""
        type_m = self.combo_type.get()
        larg, haut = _TAILLES_DEFAUT.get(type_m, (1, 1))
        self.spin_larg.set(larg)
        self.spin_haut.set(haut)

    def _detecter_orientation(self, col, row, largeur, hauteur):
        """Swap largeur/hauteur si un mur vertical est adjacent (machine posée contre un mur latéral)."""
        if largeur == hauteur:
            return largeur, hauteur
        sol = self.config_manager.data.get("sol", {})
        mur_gauche = sol.get(f"{col - 1}_{row}") == "WALL"
        mur_droite = sol.get(f"{col + largeur}_{row}") == "WALL"
        if mur_gauche or mur_droite:
            return hauteur, largeur  # rotation 90°
        return largeur, hauteur

    def placer_machine_centree(self, col, row):
        nom = self.ent_nom.get().strip()
        if not nom:
            messagebox.showwarning("Erreur", "Veuillez entrer un nom pour la machine.")
            return
        type_m = self.combo_type.get()
        try:
            larg = max(1, int(self.spin_larg.get()))
            haut = max(1, int(self.spin_haut.get()))
        except ValueError:
            larg, haut = _TAILLES_DEFAUT.get(type_m, (1, 1))
        larg, haut = self._detecter_orientation(col, row, larg, haut)
        cx = col * self.grid_size + larg * self.grid_size / 2
        cy = row * self.grid_size + haut * self.grid_size / 2
        self.dessiner_bloc_machine(cx, cy, nom, type_m, larg, haut)
        self.config_manager.ajouter_modifier_machine(nom, type_m, cx, cy, 4, {})
        # Sauvegarder les dimensions dans la config
        self.config_manager.data["machines"][nom]["largeur_cases"] = larg
        self.config_manager.data["machines"][nom]["hauteur_cases"] = haut
        self.config_manager.sauvegarder()
        self.set_mode("SELECT")

    def dessiner_bloc_machine(self, x, y, nom, type_m, largeur_cases=None, hauteur_cases=None):
        # Taille par défaut selon le type si non précisé
        if largeur_cases is None or hauteur_cases is None:
            larg_def, haut_def = _TAILLES_DEFAUT.get(type_m, (1, 1))
            if largeur_cases is None:
                largeur_cases = larg_def
            if hauteur_cases is None:
                hauteur_cases = haut_def
        # Palette de couleurs par type
        couleurs = {
            "Centrifugeuse":   "#3498db",  # Bleu
            "Automate":        "#e67e22",  # Orange
            "Paillasse":       "#95a5a6",  # Gris
            "Incubateur":      "#e91e63",  # Rose
            "Réfrigérateur":   "#00bcd4",  # Cyan
            "Laveur de plaque":"#009688",  # Teal
            "Lecteur de plaque":"#4caf50", # Vert clair
            "Bain-marie":      "#ff5722",  # Rouge-orangé
            "Agitateur":       "#9c27b0",  # Violet
            "Microscope":      "#607d8b",  # Bleu-gris
            "Hotte":           "#795548",  # Marron
            "Congélateur":     "#5c6bc0",  # Indigo
            "ENTREE":          "#2ecc71",  # Vert (Source)
            "SORTIE":          "#e74c3c",  # Rouge (Puits)
            "TECH_OFFICE":     "#95a5a6",  # Gris bureau tech
            "REPOS":           "#8e44ad",  # Violet zone repos
        }
        color = couleurs.get(type_m, "#34495e")

        half_w = largeur_cases * self.grid_size * 0.45
        half_h = hauteur_cases * self.grid_size * 0.45
        tag = f"obj_{nom}"

        self.canvas.create_rectangle(x - half_w, y - half_h, x + half_w, y + half_h,
                                     fill=color, outline="white", width=2, tags=("machine", tag))
        # Texte plus long si la machine est plus large
        max_chars = 3 + (largeur_cases - 1) * 2
        self.canvas.create_text(x, y, text=nom[:max_chars], fill="white",
                                font=("Arial", 8, "bold"), tags=("machine", tag))

    # ─────────────────────────────────────────────────────────────────────────
    #  Zone de dépôt — machines ajoutées par l'IA en attente de placement
    # ─────────────────────────────────────────────────────────────────────────

    def _dessiner_zone_staging(self):
        """Dessine le bandeau des machines en attente de placement (ajoutées par l'IA)."""
        self.canvas.delete("staging")

        en_attente = {
            k: v for k, v in self.config_manager.data.get("machines", {}).items()
            if isinstance(v, dict) and v.get("en_attente_placement")
            and v.get("type") not in ("TECH_OFFICE", "ENTREE", "SORTIE", "REPOS")
        }
        if not en_attente:
            return

        # Bandeau violet en haut à gauche du canvas (coords canvas fixes)
        MARGE = 10
        LARG_CASE = self.grid_size
        HAUT_CASE = self.grid_size
        COLS = 6
        PAD = 8

        nb = len(en_attente)
        nb_lignes = max(1, -(-nb // COLS))  # ceil division
        bande_h = nb_lignes * (HAUT_CASE + PAD) + 50
        bande_w = COLS * (LARG_CASE + PAD) + 20

        # Fond du bandeau
        self.canvas.create_rectangle(
            MARGE, MARGE, MARGE + bande_w, MARGE + bande_h,
            fill="#2d1b69", outline="#a78bfa", width=2,
            tags="staging"
        )
        self.canvas.create_text(
            MARGE + bande_w // 2, MARGE + 12,
            text="📦  Machines à placer — glissez-les sur le plan",
            fill="#e9d5ff", font=("Segoe UI", 9, "bold"),
            tags="staging"
        )

        for i, (nom, m) in enumerate(en_attente.items()):
            col_i = i % COLS
            row_i = i // COLS
            cx = MARGE + 10 + col_i * (LARG_CASE + PAD) + LARG_CASE // 2
            cy = MARGE + 30 + row_i * (HAUT_CASE + PAD) + HAUT_CASE // 2

            # Mettre à jour les coords dans le JSON pour que le drag fonctionne
            if "coords" not in m or m.get("en_attente_placement"):
                m["coords"] = {"x": cx, "y": cy}

            tag_obj = f"obj_{nom}"
            self.canvas.create_rectangle(
                cx - LARG_CASE // 2, cy - HAUT_CASE // 2,
                cx + LARG_CASE // 2, cy + HAUT_CASE // 2,
                fill="#7c3aed", outline="#c4b5fd", width=2,
                tags=("machine", "staging", tag_obj)
            )
            max_chars = 7
            self.canvas.create_text(
                cx, cy, text=nom[:max_chars],
                fill="white", font=("Arial", 7, "bold"),
                tags=("machine", "staging", tag_obj)
            )

    def _refresh_plan_machines(self):
        """Redessine uniquement les sprites machines (après ajout/suppression tech)."""
        self.canvas.delete("machine")
        machines = self.config_manager.get_machines()
        for nom, m in machines.items():
            if m["type"] == "TECH_OFFICE":
                continue
            if m.get("en_attente_placement"):
                continue  # sera dessiné par _dessiner_zone_staging
            self.dessiner_bloc_machine(
                m["coords"]["x"], m["coords"]["y"], nom, m["type"],
                m.get("largeur_cases"), m.get("hauteur_cases"))
        self._dessiner_zone_staging()