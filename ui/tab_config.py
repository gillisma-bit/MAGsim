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

class TabConfig:
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

    def selectionner_objet(self, x, y):
        """Sélectionne la machine sous le curseur (sans ouvrir le popup)."""
        items = self.canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2)
        self.selected_machine = None
        for item in items:
            for t in self.canvas.gettags(item):
                if t.startswith("obj_"):
                    self.selected_machine = t.replace("obj_", "")
                    return

    def ouvrir_popup_machine(self):
        import traceback as _tb
        try:
            self._ouvrir_popup_machine_impl()
        except Exception as _e:
            print(f"[TabConfig] ERREUR popup machine : {_e}")
            _tb.print_exc()

    def _ouvrir_popup_machine_impl(self):
        # Cherche d'abord dans les machines filtrées, puis dans le dict brut
        toutes = self.config_manager.get_machines()
        if self.selected_machine not in toutes:
            toutes = self.config_manager.data.get("machines", {})
        if self.selected_machine not in toutes:
            return
        m_data = toutes[self.selected_machine]
        type_m = m_data['type']
        
        popup = tk.Toplevel(self.parent)
        popup.title(f"Config : {self.selected_machine}")
        popup.geometry("780x820")
        popup.minsize(720, 700)
        popup.grab_set()

        ttk.Label(popup, text=f"⚙️ {type_m.upper()} : {self.selected_machine}", 
                  font=("Segoe UI", 12, "bold")).pack(pady=10)

        # --- CAS STOCKAGE : Réfrigérateur, Congélateur ---
        _TYPES_STOCKAGE = {"Réfrigérateur", "Congélateur"}
        # --- CAS 1 : LES MACHINES DE TRAITEMENT ---
        _TYPES_SPECIAUX = {"ENTREE", "SORTIE", "TECH_OFFICE", "REPOS"}
        if type_m in _TYPES_STOCKAGE:
            # ─── Popup STOCKAGE ───────────────────────────────────────────────
            f_s = ttk.LabelFrame(popup, text="🧊 Paramètres de stockage", padding=12)
            f_s.pack(fill="x", padx=20, pady=10)

            ttk.Label(f_s, text="Capacité max (tubes) :").grid(row=0, column=0, sticky="w")
            ent_cap_s = ttk.Entry(f_s, width=10)
            ent_cap_s.insert(0, m_data.get("capacite_max", m_data.get("file_max", 50)))
            ent_cap_s.grid(row=0, column=1, padx=5, pady=3)
            ttk.Label(f_s, text="(nbre total de tubes stockables simultanément)",
                      foreground="gray").grid(row=0, column=2, padx=5)

            ttk.Label(f_s, text="Conditions / température :").grid(row=1, column=0, sticky="w")
            ent_temp = ttk.Entry(f_s, width=20)
            ent_temp.insert(0, m_data.get("temperature_label", "4 °C" if type_m == "Réfrigérateur" else "-20 °C"))
            ent_temp.grid(row=1, column=1, columnspan=2, padx=5, pady=3, sticky="w")

            # Dimensions
            larg_def_s, haut_def_s = _TAILLES_DEFAUT.get(type_m, (1, 2))
            f_dim_s = ttk.LabelFrame(popup, text="📐 Dimensions (cases)", padding=8)
            f_dim_s.pack(fill="x", padx=20, pady=(0, 6))
            ttk.Label(f_dim_s, text="Largeur :").grid(row=0, column=0, sticky="w")
            ent_larg_s = ttk.Entry(f_dim_s, width=6)
            ent_larg_s.insert(0, m_data.get("largeur_cases", larg_def_s))
            ent_larg_s.grid(row=0, column=1, padx=5)
            ttk.Label(f_dim_s, text="Hauteur :").grid(row=0, column=2, sticky="w", padx=(10, 0))
            ent_haut_s = ttk.Entry(f_dim_s, width=6)
            ent_haut_s.insert(0, m_data.get("hauteur_cases", haut_def_s))
            ent_haut_s.grid(row=0, column=3, padx=5)

            # Fiabilité (pannes éventuelles du frigo)
            f_fiab_s = ttk.LabelFrame(popup, text="🔧 Fiabilité (optionnel)", padding=10)
            f_fiab_s.pack(fill="x", padx=20, pady=(0, 6))
            ttk.Label(f_fiab_s, text="TMEP — Temps moyen entre pannes (h) :").grid(row=0, column=0, sticky="w")
            ent_tmep_s = ttk.Entry(f_fiab_s, width=10)
            ent_tmep_s.insert(0, m_data.get("tmep", 0))
            ent_tmep_s.grid(row=0, column=1, padx=5, pady=2)
            ttk.Label(f_fiab_s, text="0 = jamais en panne", foreground="gray").grid(row=0, column=2, padx=4)
            ttk.Label(f_fiab_s, text="TMR — Temps moyen de réparation (h) :").grid(row=1, column=0, sticky="w")
            ent_tmr_s = ttk.Entry(f_fiab_s, width=10)
            ent_tmr_s.insert(0, m_data.get("tmr", 0))
            ent_tmr_s.grid(row=1, column=1, padx=5, pady=2)

            def save_stockage():
                try:
                    cap_s = max(1, int(ent_cap_s.get()))
                except ValueError:
                    cap_s = 50
                m_data["capacite_max"] = cap_s
                m_data["file_max"]     = cap_s
                m_data["capacite"]     = cap_s
                m_data["temperature_label"] = ent_temp.get().strip()
                m_data["sous_categorie"] = "STOCKAGE"
                try:
                    nl = max(1, int(ent_larg_s.get()))
                    nh = max(1, int(ent_haut_s.get()))
                except ValueError:
                    nl, nh = larg_def_s, haut_def_s
                m_data["largeur_cases"] = nl
                m_data["hauteur_cases"] = nh
                try:
                    tv = float(ent_tmep_s.get())
                    rv = float(ent_tmr_s.get())
                    if tv > 0 and rv > 0:
                        m_data["tmep"] = tv
                        m_data["tmr"]  = rv
                    else:
                        m_data.pop("tmep", None)
                        m_data.pop("tmr",  None)
                except ValueError:
                    pass
                self.config_manager.sauvegarder()
                if self.selected_machine:
                    self.canvas.delete(f"obj_{self.selected_machine}")
                    mx = self.config_manager.data["machines"][self.selected_machine]["coords"]["x"]
                    my = self.config_manager.data["machines"][self.selected_machine]["coords"]["y"]
                    self.dessiner_bloc_machine(mx, my, self.selected_machine, type_m, nl, nh)
                popup.destroy()

            frame_bas_s = ttk.Frame(popup)
            frame_bas_s.pack(side=tk.BOTTOM, fill="x", pady=8, padx=20)
            ttk.Button(frame_bas_s, text="💾 SAUVER", command=save_stockage, padding=10).pack()

        elif type_m not in _TYPES_SPECIAUX:
            # --- Bouton SAUVER ancré en bas (avant le contenu pour rester visible) ---
            frame_bas = ttk.Frame(popup)
            frame_bas.pack(side=tk.BOTTOM, fill="x", pady=8, padx=20)

            # --- PARAMÈTRES ---
            f_p = ttk.LabelFrame(popup, text="Capacité & Seuil", padding=10)
            f_p.pack(fill="x", padx=20)
            
            ttk.Label(f_p, text="Capacité du batch :").grid(row=0, column=0, sticky="w")
            ent_cap = ttk.Entry(f_p, width=10); ent_cap.insert(0, m_data.get("capacite", 4))
            ent_cap.grid(row=0, column=1, padx=5, pady=2)

            ttk.Label(f_p, text="Taille file d'attente max :").grid(row=1, column=0, sticky="w")
            ent_file_max = ttk.Entry(f_p, width=10); ent_file_max.insert(0, m_data.get("file_max", m_data.get("capacite", 4)))
            ent_file_max.grid(row=1, column=1, padx=5, pady=2)
            ttk.Label(f_p, text="(nbre max de tubes tech peut déposer)", foreground="gray").grid(row=1, column=2, padx=5)

            ttk.Label(f_p, text="Seuil de lancement :").grid(row=2, column=0, sticky="w")
            ent_seuil = ttk.Entry(f_p, width=10); ent_seuil.insert(0, m_data.get("seuil", 1))
            ent_seuil.grid(row=2, column=1, padx=5, pady=2)

            # --- DIMENSIONS ---
            larg_def, haut_def = _TAILLES_DEFAUT.get(type_m, (1, 1))
            f_dim = ttk.LabelFrame(popup, text="📏 Dimensions (cases)", padding=8)
            f_dim.pack(fill="x", padx=20, pady=(0, 4))
            ttk.Label(f_dim, text="Largeur :").grid(row=0, column=0, sticky="w")
            ent_larg = ttk.Entry(f_dim, width=6)
            ent_larg.insert(0, m_data.get("largeur_cases", larg_def))
            ent_larg.grid(row=0, column=1, padx=5)
            ttk.Label(f_dim, text="Hauteur :").grid(row=0, column=2, sticky="w", padx=(10, 0))
            ent_haut = ttk.Entry(f_dim, width=6)
            ent_haut.insert(0, m_data.get("hauteur_cases", haut_def))
            ent_haut.grid(row=0, column=3, padx=5)
            ttk.Label(f_dim, text="(1 case ≈ 50 cm — modifiez pour agrandir l’appareil)",
                      foreground="gray").grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))

            # --- LISTE FILTRÉE DES PROTOCOLES ---
            ttk.Label(popup, text=f"Protocoles compatibles avec {type_m} :", font=("Arial", 9, "bold")).pack(pady=5)
            
            list_frame = ttk.Frame(popup)
            list_frame.pack(fill="both", expand=True, padx=20)
            
            catalog = self.config_manager.get_catalog_protocoles()
            self.check_vars = {}

            for nom_p, d in catalog.items():
                if d.get("type_compatible") == type_m:
                    var = tk.BooleanVar(value=(nom_p in m_data.get("protocoles", {})))
                    self.check_vars[nom_p] = var
                    f_line = ttk.Frame(list_frame)
                    f_line.pack(fill="x", pady=1)
                    ttk.Checkbutton(f_line, variable=var).pack(side="left")
                    lbl = ttk.Label(f_line, text=f"{nom_p}")
                    lbl.pack(side="left")
                    # Champ de temps inline (éditable directement)
                    var_temps = tk.StringVar(value=str(d.get("temps", 0)))
                    ent_temps = ttk.Entry(f_line, textvariable=var_temps, width=6)
                    ent_temps.pack(side="left", padx=(6, 2))
                    ttk.Label(f_line, text="min", foreground="gray").pack(side="left")

                    def _make_save_temps(n=nom_p, vt=var_temps, lf=f_line):
                        def _save_temps(event=None):
                            try:
                                nouveau = int(vt.get())
                                self.config_manager.modifier_protocole_global(n, nouveau)
                            except ValueError:
                                pass
                        return _save_temps
                    ent_temps.bind("<FocusOut>", _make_save_temps())
                    ent_temps.bind("<Return>", _make_save_temps())

                    btn_del = tk.Button(f_line, text="✕", fg="red", bd=0, font=("Arial", 8),
                                        command=lambda n=nom_p: self.delete_proto_confirm(n, popup))
                    btn_del.pack(side="right")

            # --- AJOUT AU CATALOGUE ---
            f_new = ttk.LabelFrame(popup, text=f"➕ Nouveau protocole pour {type_m}", padding=10)
            f_new.pack(fill="x", padx=20, pady=10)
            ttk.Label(f_new, text="Nom :").grid(row=0, column=0)
            ent_n = ttk.Entry(f_new, width=15); ent_n.grid(row=0, column=1, padx=5)
            ttk.Label(f_new, text="Temps (s) :").grid(row=1, column=0)
            ent_t = ttk.Entry(f_new, width=10); ent_t.grid(row=1, column=1, padx=5)

            def add_p():
                if ent_n.get() and ent_t.get().isdigit():
                    self.config_manager.ajouter_protocole_global(ent_n.get(), int(ent_t.get()), type_m)
                    popup.destroy(); self.ouvrir_popup_machine()
            
            ttk.Button(f_new, text="Ajouter au catalogue", command=add_p).grid(row=2, column=0, columnspan=2, pady=5)

            # --- FIABILITÉ (TMEP / TMR) ---
            f_fiab = ttk.LabelFrame(popup, text="🔧 Fiabilité & pannes (loi exponentielle)", padding=10)
            f_fiab.pack(fill="x", padx=20, pady=(0, 5))

            ttk.Label(f_fiab, text="TMEP — Temps moyen entre pannes (h) :").grid(row=0, column=0, sticky="w")
            ent_tmep = ttk.Entry(f_fiab, width=10)
            ent_tmep.insert(0, m_data.get("tmep", 0))
            ent_tmep.grid(row=0, column=1, padx=5, pady=2)
            ttk.Label(f_fiab, text="0 = pas de pannes", foreground="gray").grid(row=0, column=2, padx=4)

            ttk.Label(f_fiab, text="TMR — Temps moyen de réparation (h) :").grid(row=1, column=0, sticky="w")
            ent_tmr = ttk.Entry(f_fiab, width=10)
            ent_tmr.insert(0, m_data.get("tmr", 0))
            ent_tmr.grid(row=1, column=1, padx=5, pady=2)

            _tmep_v = m_data.get("tmep", 0) or 0
            _tmr_v  = m_data.get("tmr",  0) or 0
            if _tmep_v > 0 and _tmr_v > 0:
                _dispo = _tmep_v / (_tmep_v + _tmr_v) * 100
                _c = "#27ae60" if _dispo >= 90 else "#e67e22" if _dispo >= 75 else "#e74c3c"
                _txt = f"→ Disponibilité théorique : {_dispo:.1f} %   (TMEP={_tmep_v:.1f} h / TMR={_tmr_v:.1f} h)"
            else:
                _c, _txt = "#27ae60", "→ Disponibilité théorique : 100 % (pannes désactivées)"
            ttk.Label(f_fiab, text=_txt, foreground=_c, font=("Segoe UI", 9, "bold")).grid(
                row=2, column=0, columnspan=3, sticky="w", pady=(5, 0))

            # ── Présence du technicien ─────────────────────────────────────
            f_tech = ttk.LabelFrame(popup, text="👤 Présence du technicien", padding=10)
            f_tech.pack(fill="x", padx=20, pady=(0, 5))

            var_tech_poste = tk.BooleanVar(
                value=m_data.get("tech_requis_poste", False))
            cb_tech = ttk.Checkbutton(
                f_tech,
                text="Technicien requis à poste pendant toute la durée du traitement",
                variable=var_tech_poste)
            cb_tech.grid(row=0, column=0, sticky="w")
            ttk.Label(
                f_tech,
                text="(Paillasse manuelle : le tech reste bloqué, accumule de la fatigue\n"
                     "et peut commettre des erreurs analytiques en fin d’analyse)",
                foreground="gray", justify="left"
            ).grid(row=1, column=0, sticky="w", padx=20)

            def save():
                m_data["capacite"] = int(ent_cap.get())
                m_data["file_max"] = int(ent_file_max.get())
                m_data["seuil"] = int(ent_seuil.get())
                try:
                    new_larg = max(1, int(ent_larg.get()))
                    new_haut = max(1, int(ent_haut.get()))
                except ValueError:
                    new_larg = m_data.get("largeur_cases", 1)
                    new_haut = m_data.get("hauteur_cases", 1)
                m_data["largeur_cases"] = new_larg
                m_data["hauteur_cases"] = new_haut
                m_data["protocoles"] = {p: catalog.get(p, {}) for p, v in self.check_vars.items() if v.get()}
                m_data["tech_requis_poste"] = var_tech_poste.get()
                try:
                    tmep_val = float(ent_tmep.get())
                    tmr_val  = float(ent_tmr.get())
                    if tmep_val > 0 and tmr_val > 0:
                        m_data["tmep"] = tmep_val
                        m_data["tmr"]  = tmr_val
                    else:
                        m_data.pop("tmep", None)
                        m_data.pop("tmr",  None)
                        m_data.pop("panne_proba", None)
                        m_data.pop("temps_reparation_min", None)
                        m_data.pop("temps_reparation_max", None)
                except ValueError:
                    pass
                self.config_manager.sauvegarder()
                # Redessiner avec les nouvelles dimensions
                if self.selected_machine:
                    self.canvas.delete(f"obj_{self.selected_machine}")
                    mx = self.config_manager.data["machines"][self.selected_machine]["coords"]["x"]
                    my = self.config_manager.data["machines"][self.selected_machine]["coords"]["y"]
                    self.dessiner_bloc_machine(mx, my, self.selected_machine, type_m, new_larg, new_haut)
                popup.destroy()

            ttk.Button(frame_bas, text="💾 SAUVER MACHINE", command=save, padding=10).pack()

        # --- CAS 2 : L'ENTRÉE ---
        elif type_m == "ENTREE":
            # ── Fréquence & variabilité ──────────────────────────────────────────
            f_e = ttk.LabelFrame(popup, text="Paramètres d'arrivée", padding=15)
            f_e.pack(fill="x", padx=20, pady=(20, 5))

            ttk.Label(f_e, text="Fréquence de base (min entre 2 tubes) :").grid(row=0, column=0, sticky="w")
            ent_freq = ttk.Entry(f_e, width=8)
            ent_freq.insert(0, m_data.get("frequence", 5))
            ent_freq.grid(row=0, column=1, padx=5, pady=3, sticky="w")

            ttk.Label(f_e, text="Variabilité Gamma k\n(1=aléatoire, 5=régulier) :").grid(row=1, column=0, sticky="w")
            ent_gamma = ttk.Entry(f_e, width=8)
            ent_gamma.insert(0, m_data.get("gamma_k", 2.0))
            ent_gamma.grid(row=1, column=1, padx=5, pady=3, sticky="w")

            ttk.Label(f_e, text="Heure de démarrage (0-23) :").grid(row=2, column=0, sticky="w")
            ent_hdebut = ttk.Entry(f_e, width=8)
            ent_hdebut.insert(0, m_data.get("heure_debut", 7.0))
            ent_hdebut.grid(row=2, column=1, padx=5, pady=3, sticky="w")

            # ── Profil horaire ─────────────────────────────────────────────────
            f_p_outer = ttk.LabelFrame(popup, text="Profil horaire  (heure → facteur d'intensité)", padding=5)
            f_p_outer.pack(fill="both", expand=True, padx=20, pady=5)

            # Canvas scrollable pour contenir le tableau
            _canvas = tk.Canvas(f_p_outer, height=220, highlightthickness=0)
            _sb = ttk.Scrollbar(f_p_outer, orient="vertical", command=_canvas.yview)
            _canvas.configure(yscrollcommand=_sb.set)
            _sb.pack(side="right", fill="y")
            _canvas.pack(side="left", fill="both", expand=True)

            f_p = ttk.Frame(_canvas)
            _cwin = _canvas.create_window((0, 0), window=f_p, anchor="nw")

            def _resize_cwin(event):
                _canvas.itemconfig(_cwin, width=event.width)
            _canvas.bind("<Configure>", _resize_cwin)

            def _update_scroll(event=None):
                _canvas.configure(scrollregion=_canvas.bbox("all"))
            f_p.bind("<Configure>", _update_scroll)

            def _on_wheel(event):
                _canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            _canvas.bind("<MouseWheel>", _on_wheel)
            f_p.bind("<MouseWheel>", _on_wheel)

            ttk.Label(f_p, text="Heure", font=("Segoe UI", 8, "bold"), width=8).grid(row=0, column=0)
            ttk.Label(f_p, text="Facteur", font=("Segoe UI", 8, "bold"), width=8).grid(row=0, column=1)
            ttk.Label(f_p, text="", width=4).grid(row=0, column=2)

            profil_defaut = [
                [0.0, 0.1], [6.0, 0.3], [7.0, 0.8], [8.0, 1.5], [9.0, 1.8],
                [10.0, 1.4], [11.0, 1.1], [12.0, 0.6], [13.0, 0.7], [14.0, 1.2],
                [15.0, 1.0], [16.0, 0.7], [17.0, 0.4], [18.0, 0.2], [20.0, 0.1], [24.0, 0.1]
            ]
            profil_courant = [list(p) for p in m_data.get("profil_horaire", profil_defaut)]

            # Liste de paires (StringVar heure, StringVar facteur) + lignes d'UI
            lignes_profil = []

            def ajouter_ligne(h="12.0", f="1.0"):
                row_idx = len(lignes_profil) + 1
                var_h = tk.StringVar(value=str(h))
                var_f = tk.StringVar(value=str(f))
                e_h = ttk.Entry(f_p, textvariable=var_h, width=8)
                e_f = ttk.Entry(f_p, textvariable=var_f, width=8)
                e_h.grid(row=row_idx, column=0, padx=2, pady=1)
                e_f.grid(row=row_idx, column=1, padx=2, pady=1)
                btn_del = ttk.Button(f_p, text="✕", width=3,
                                     command=lambda r=(e_h, e_f, var_h, var_f): supprimer_ligne(r))
                btn_del.grid(row=row_idx, column=2, padx=2)
                lignes_profil.append((var_h, var_f, e_h, e_f, btn_del))

            def supprimer_ligne(refs):
                e_h, e_f, var_h, var_f = refs
                for i, (vh, vf, eh, ef, btn) in enumerate(lignes_profil):
                    if vh is var_h:
                        eh.destroy(); ef.destroy(); btn.destroy()
                        lignes_profil.pop(i)
                        break

            for h, f in profil_courant:
                ajouter_ligne(h, f)

            # Bouton «Ajouter» hors de la zone défilante, toujours visible
            ttk.Button(f_p_outer, text="＋ Ajouter un point", command=ajouter_ligne).pack(pady=3)

            # ── Bouton Sauvegarder – ancré en bas, toujours visible ─────────────
            def save_entree():
                try:
                    m_data["frequence"] = float(ent_freq.get())
                    m_data["gamma_k"] = float(ent_gamma.get())
                    m_data["heure_debut"] = float(ent_hdebut.get())
                    pts = []
                    for var_h, var_f, *_ in lignes_profil:
                        try:
                            pts.append([float(var_h.get()), float(var_f.get())])
                        except ValueError:
                            pass
                    pts.sort(key=lambda p: p[0])
                    if not pts:
                        messagebox.showwarning("Erreur", "Le profil horaire ne peut pas être vide.")
                        return
                    m_data["profil_horaire"] = pts
                    self.config_manager.sauvegarder()
                    popup.destroy()
                except ValueError:
                    messagebox.showwarning("Erreur", "Valeurs numériques invalides.")

            frm_bas = ttk.Frame(popup)
            frm_bas.pack(side=tk.BOTTOM, fill="x", padx=20, pady=(2, 15))
            ttk.Button(frm_bas, text="💾 SAUVER L'ENTRÉE", command=save_entree).pack(pady=6)

        # --- CAS 3 : TECH_OFFICE → rediriger vers la fenêtre RH ---
        elif type_m == "TECH_OFFICE":
            popup.destroy()
            FenetreRH(self.parent, self.config_manager,
                      refresh_callback=self._refresh_plan_machines)
            return

        # --- placeholder inaccessible (évite les variables non définies) ---
        if False:
            pass

        # --- CAS 4 : REPOS ---
        elif type_m == "REPOS":
            ttk.Label(
                popup,
                text="🛌  Zone de repos",
                font=("Segoe UI", 12, "bold"),
            ).pack(pady=(20, 4))
            ttk.Label(
                popup,
                text="Ce marqueur définit l'endroit où les techniciens\n"
                     "se rendent pendant leur pause déjeuner.\n\n"
                     "Déplacez-le sur le plan pour le repositionner.\n"
                     "Les coordonnées sont sauvegardées automatiquement.",
                justify="center",
                wraplength=260,
            ).pack(pady=10, padx=20)
            ttk.Button(popup, text="Fermer", command=popup.destroy).pack(pady=8)

        # --- CAS 5 : SORTIE et autres ---
        else:
            ttk.Label(popup, text="Zone de validation finale (Sortie)").pack(pady=20)
            ttk.Button(popup, text="Fermer", command=popup.destroy).pack()

    def delete_proto_confirm(self, nom, parent_popup):
        if messagebox.askyesno("Supprimer", f"Effacer {nom} du catalogue global ?"):
            self.config_manager.supprimmer_protocole_global(nom)
            parent_popup.destroy()
            self.ouvrir_popup_machine()
                
    def charger_details_machine(self):
        """Remplit le formulaire à droite avec les infos de la machine cliquée"""
        if not self.selected_machine: return
        
        # On récupère les données dans le JSON via le manager
        machines = self.config_manager.get_machines()
        if self.selected_machine in machines:
            m_data = machines[self.selected_machine]
            
            # On met à jour les champs de saisie
            self.ent_nom.delete(0, tk.END)
            self.ent_nom.insert(0, self.selected_machine)
            self.combo_type.set(m_data["type"])
            
            # On change le titre du panneau pour confirmer la sélection
            print(f"Interface mise à jour pour : {self.selected_machine}")

    def charger_config_existante(self):
        """Reconstruit le labo à partir du JSON"""
        # 1. Le Sol
        sol_data = self.config_manager.data.get("sol", {})
        for cle, type_s in sol_data.items():
            c, r = map(int, cle.split("_"))
            old_mode = self.mode # Sauvegarde le mode actuel
            self.mode = type_s
            self.peindre_case(c, r)
            self.mode = old_mode
            
        # 2. Les Machines (on ne dessine PAS les TECH_OFFICE sur le plan)
        machines = self.config_manager.get_machines()
        for nom, m in machines.items():
            if m.get("type") == "TECH_OFFICE":
                continue
            if not m.get("type") or not m.get("coords"):
                continue
            if m.get("en_attente_placement"):
                continue  # sera dessiné dans la zone de dépôt
            self.dessiner_bloc_machine(
                m["coords"]["x"], m["coords"]["y"], nom, m["type"],
                m.get("largeur_cases"), m.get("hauteur_cases"))

        # 3. Machines en attente de placement (ajoutées par l'IA)
        self._dessiner_zone_staging()

    def supprimer_selection(self):
        """Supprime la machine sélectionnée du JSON et du Canvas"""
        if not self.selected_machine:
            messagebox.showwarning("Attention", "Veuillez d'abord sélectionner une machine sur le plan.")
            return
        
        confirm = messagebox.askyesno("MAGsim", f"Voulez-vous vraiment supprimer {self.selected_machine} ?")
        if confirm:
            # 1. On l'efface de la mémoire (JSON)
            self.config_manager.supprimer_machine(self.selected_machine)
            
            # 2. On l'efface du dessin (Canvas)
            # Rappel : toutes nos machines ont le tag 'obj_NomDeLaMachine'
            self.canvas.delete(f"obj_{self.selected_machine}")
            
            # 3. On vide la sélection actuelle
            print(f"🧹 Visuel : {self.selected_machine} effacé du plan.")
            self.selected_machine = None
            self.ent_nom.delete(0, tk.END)

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
        except:
            pass

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