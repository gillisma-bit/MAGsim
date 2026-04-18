import tkinter as tk
from tkinter import ttk, messagebox, colorchooser

class TabConfig:
    def __init__(self, parent, config_manager):
        self.parent = parent
        self.config_manager = config_manager
        self.selected_machine = None
        
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
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)

    def setup_ui_elements(self):
        ttk.Label(self.edit_frame, text="🏗️ ÉDITEUR MAGsim", font=("Segoe UI", 12, "bold")).pack(pady=(0, 10))
        
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
        ttk.Label(f_echelle, text="1 case =", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")
        self.ent_mpc = ttk.Entry(f_echelle, width=6)
        ent_mpc_val = self.config_manager.data.get("personnel", {}).get("metres_par_case", 3.0)
        self.ent_mpc.insert(0, ent_mpc_val)
        self.ent_mpc.grid(row=0, column=1, padx=4)
        ttk.Label(f_echelle, text="mètres", font=("Segoe UI", 9)).grid(row=0, column=2, sticky="w")
        ttk.Button(f_echelle, text="✓ Appliquer",
                   command=self._sauver_echelle).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(f_echelle, text="(1 case = 50 px)",
                  foreground="gray", font=("Segoe UI", 8)).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))

        ttk.Separator(self.edit_frame).pack(fill="x", pady=15)

        # GESTION DES PROCÉDURES
        ttk.Label(self.edit_frame, text="🔬 PROCÉDURES", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Button(self.edit_frame, text="⚙️ Gérer les procédures de tubes", command=self.ouvrir_editeur_workflows).pack(fill="x", pady=5)

        ttk.Separator(self.edit_frame).pack(fill="x", pady=15)

        # AJOUT MACHINE
        ttk.Label(self.edit_frame, text="📦 MACHINE", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.ent_nom = ttk.Entry(self.edit_frame)
        self.ent_nom.pack(fill="x", pady=5)
        
        self.combo_type = ttk.Combobox(self.edit_frame, values=["Centrifugeuse", "Automate", "Paillasse", "ENTREE", "SORTIE", "TECH_OFFICE"])
        self.combo_type.pack(fill="x", pady=5)
        self.combo_type.set("Centrifugeuse")

        ttk.Button(self.edit_frame, text="📍 Placer au centre", command=lambda: self.set_mode("PLACE_MACHINE")).pack(fill="x", pady=10)

        # Bouton Supprimer (en rouge pour la sécurité)
        self.btn_suppr = tk.Button(self.edit_frame, text="🗑️ Supprimer la sélection", 
                                   bg="#ec4a38", fg="white", font=("Segoe UI", 9, "bold"),
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
        else:
            self.selectionner_objet(x_c, y_c)

    def on_canvas_drag(self, event):
        if self.mode in ["COUNTER", "WALL", "FLOOR"]:
            x = self.canvas.canvasx(event.x)
            y = self.canvas.canvasy(event.y)
            self.peindre_case(int(x // self.grid_size), int(y // self.grid_size))

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

    def placer_machine_centree(self, col, row):
        nom = self.ent_nom.get().strip()
        if not nom:
            messagebox.showwarning("Erreur", "Veuillez entrer un nom pour la machine.")
            return
        cx = (col * self.grid_size) + (self.grid_size // 2)
        cy = (row * self.grid_size) + (self.grid_size // 2)
        type_m = self.combo_type.get()
        self.dessiner_bloc_machine(cx, cy, nom, type_m)
        self.config_manager.ajouter_modifier_machine(nom, type_m, cx, cy, 4, {})
        self.set_mode("SELECT")

    def dessiner_bloc_machine(self, x, y, nom, type_m):
        # Palette de couleurs par type
        couleurs = {
            "Centrifugeuse": "#3498db", # Bleu
            "Automate": "#e67e22",      # Orange
            "ENTREE": "#2ecc71",        # Vert (Source)
            "SORTIE": "#e74c3c",        # Rouge (Puits)
            "Paillasse": "#95a5a6",     # Gris
            "TECH_OFFICE": "#95a5a6"    # Gris pour bureau tech
        }
        color = couleurs.get(type_m, "#34495e")
        
        size = self.grid_size * 0.8 / 2
        tag = f"obj_{nom}"
        
        self.canvas.create_rectangle(x-size, y-size, x+size, y+size, 
                                     fill=color, outline="white", width=2, tags=("machine", tag))
        self.canvas.create_text(x, y, text=nom[:3], fill="white", font=("Arial", 8, "bold"), tags=("machine", tag))

    def selectionner_objet(self, x, y):
        items = self.canvas.find_overlapping(x-2, y-2, x+2, y+2)
        self.selected_machine = None
        for item in items:
            tags = self.canvas.gettags(item)
            for t in tags:
                if t.startswith("obj_"):
                    self.selected_machine = t.replace("obj_", "")
                    # OUVERTURE DU POPUP
                    self.ouvrir_popup_machine()
                    return

    def ouvrir_popup_machine(self):
        m_data = self.config_manager.get_machines()[self.selected_machine]
        type_m = m_data['type']
        
        popup = tk.Toplevel(self.parent)
        popup.title(f"Config : {self.selected_machine}")
        popup.geometry("550x700")
        popup.grab_set()

        ttk.Label(popup, text=f"⚙️ {type_m.upper()} : {self.selected_machine}", 
                  font=("Segoe UI", 12, "bold")).pack(pady=10)

        # --- CAS 1 : LES MACHINES DE TRAITEMENT ---
        if type_m in ["Centrifugeuse", "Automate", "Paillasse"]:
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
                popup.destroy()

            ttk.Button(popup, text="💾 SAUVER MACHINE", command=save, padding=10).pack(pady=10)

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
            frm_bas.pack(fill="x", padx=20, pady=(2, 15))
            ttk.Button(frm_bas, text="💾 SAUVER L'ENTRÉE", command=save_entree).pack(pady=6)

        # --- CAS 3 : TECH_OFFICE ---
        elif type_m == "TECH_OFFICE":
            ttk.Label(popup, text=f"Bureau : {self.selected_machine}", font=("Segoe UI", 11, "bold")).pack(pady=(15, 5))

            # ── Cadre principal ──────────────────────────────────────────────────
            f_t = ttk.LabelFrame(popup, text="👤 Caractéristiques du technicien", padding=12)
            f_t.pack(fill="x", padx=20, pady=10)

            # Nom / identifiant
            ttk.Label(f_t, text="Nom / identifiant :").grid(row=0, column=0, sticky="w", pady=3)
            ent_nom = ttk.Entry(f_t, width=20)
            ent_nom.insert(0, m_data.get("nom", ""))
            ent_nom.grid(row=0, column=1, padx=5)
            ttk.Label(f_t, text="Affiché dans les rapports et indicateurs de bien-être",
                      foreground="gray").grid(row=0, column=2, padx=6)

            # Expérience
            ttk.Label(f_t, text="Expérience (1 = novice  …  5 = expert) :").grid(
                row=1, column=0, sticky="w", pady=3)
            ent_exp = ttk.Entry(f_t, width=8)
            ent_exp.insert(0, m_data.get("experience", 3))
            ent_exp.grid(row=1, column=1, padx=5)
            ttk.Label(f_t, text="Multiplie les erreurs : ×2.0 → ×0.4",
                      foreground="gray").grid(row=1, column=2, padx=6)

            # Âge
            ttk.Label(f_t, text="Âge (années) :").grid(row=2, column=0, sticky="w", pady=3)
            ent_age = ttk.Entry(f_t, width=8)
            ent_age.insert(0, m_data.get("age", 35))
            ent_age.grid(row=2, column=1, padx=5)
            ttk.Label(f_t, text="Jeune ↑ vitesse + ↑ erreurs  |  Senior ↓ vitesse + ↓ erreurs",
                      foreground="gray").grid(row=2, column=2, padx=6)

            # Taux d'erreur de base
            ttk.Label(f_t, text="Taux d'erreur de base (0.0 – 1.0) :").grid(
                row=3, column=0, sticky="w", pady=3)
            ent_pct = ttk.Entry(f_t, width=8)
            ent_pct.insert(0, m_data.get("pct_erreur_tech", 0.0))
            ent_pct.grid(row=3, column=1, padx=5)
            ttk.Label(f_t, text="Modulé par expérience · âge · fatigue · heure du jour",
                      foreground="gray").grid(row=3, column=2, padx=6)

            # Seuil de surcharge (affiché en %)
            ttk.Label(f_t, text="Seuil de surcharge (0 – 100 %) :").grid(
                row=4, column=0, sticky="w", pady=3)
            ent_seuil = ttk.Entry(f_t, width=8)
            ent_seuil.insert(0, int(float(m_data.get("seuil_charge_fatigue", 0.70)) * 100))
            ent_seuil.grid(row=4, column=1, padx=5)
            ttk.Label(f_t, text="Au-dessus de ce % de capacité, la fatigue commence à monter",
                      foreground="gray").grid(row=4, column=2, padx=6)

            # Taux de montée de fatigue
            ttk.Label(f_t, text="Taux de montée de fatigue :").grid(
                row=5, column=0, sticky="w", pady=3)
            ent_taux = ttk.Entry(f_t, width=8)
            ent_taux.insert(0, m_data.get("taux_montee_fatigue", 0.01))
            ent_taux.grid(row=5, column=1, padx=5)
            ttk.Label(f_t, text="Incrément par tube livré en surcharge (ex. 0.01)",
                      foreground="gray").grid(row=5, column=2, padx=6)

            # Taux de récupération nocturne
            ttk.Label(f_t, text="Récupération nocturne (%) :").grid(
                row=6, column=0, sticky="w", pady=3)
            ent_recup = ttk.Entry(f_t, width=8)
            ent_recup.insert(0, int(float(m_data.get("taux_recuperation_nuit", 0.15)) * 100))
            ent_recup.grid(row=6, column=1, padx=5)
            ttk.Label(f_t, text="% du mécontentement effacé chaque nuit de repos (déf. 15 %)",
                      foreground="gray").grid(row=6, column=2, padx=6)

            # Capacité max tubes portés
            ttk.Label(f_t, text="Capacité max (tubes portés simultanément) :").grid(
                row=7, column=0, sticky="w", pady=3)
            ent_cap = ttk.Entry(f_t, width=8)
            ent_cap.insert(0, m_data.get("capacite_max_tubes", 10))
            ent_cap.grid(row=7, column=1, padx=5)

            # ── Section personnel global (charge cible + quarts) ─────────────────
            f_pers = ttk.LabelFrame(popup, text="🗓️ Quarts de travail & charge", padding=12)
            f_pers.pack(fill="x", padx=20, pady=(0, 5))

            personnel = self.config_manager.data.get("personnel", {})

            ttk.Label(f_pers, text="Capacité journalière normale (tubes/jour) :").grid(
                row=0, column=0, sticky="w", pady=3)
            ent_cap_jour = ttk.Entry(f_pers, width=8)
            ent_cap_jour.insert(0, personnel.get("capacite_journaliere_normale", 150))
            ent_cap_jour.grid(row=0, column=1, padx=5)
            ttk.Label(f_pers, text="Référence pour calculer la charge effective",
                      foreground="gray").grid(row=0, column=2, padx=6)

            ttk.Label(f_pers, text="Alerte accumulation entrée (nb tubes) :").grid(
                row=1, column=0, sticky="w", pady=3)
            ent_seuil_acc = ttk.Entry(f_pers, width=8)
            ent_seuil_acc.insert(0, personnel.get("seuil_accumulation_alerte", 20))
            ent_seuil_acc.grid(row=1, column=1, padx=5)
            ttk.Label(f_pers, text="Déclenche la montée de cadence des techs",
                      foreground="gray").grid(row=1, column=2, padx=6)

            # Quarts : tableau lecture / info (édition complète dans un futur dialog dédié)
            quarts = personnel.get("quarts", [])
            if quarts:
                ttk.Label(f_pers, text="Quarts définis :").grid(
                    row=2, column=0, sticky="nw", pady=(6, 2))
                txt_quarts = ""
                for q in quarts:
                    garde_tag = "  [GARDE]" if q.get("garde") else ""
                    techids = ", ".join(q.get("tech_ids", []))
                    txt_quarts += f"• {q['nom']} {q['heure_debut']}h–{q['heure_fin']}h : {techids}{garde_tag}\n"
                ttk.Label(f_pers, text=txt_quarts.strip(), foreground="#555",
                          font=("Segoe UI", 9)).grid(row=2, column=1, columnspan=2,
                                                       sticky="w", padx=5)
            ttk.Label(f_pers, text="(Édition complète des quarts : menu Configuration → Personnel)",
                      foreground="#aaa", font=("Segoe UI", 8, "italic")).grid(
                row=3, column=0, columnspan=3, sticky="w", pady=(2, 0))

            # ── Aperçu indicatif ─────────────────────────────────────────────────
            f_preview = ttk.LabelFrame(popup, text="🔍 Aperçu (expérience 3 · âge 35 · sans fatigue · 9h)",
                                       padding=8)
            f_preview.pack(fill="x", padx=20, pady=(0, 5))
            lbl_preview = ttk.Label(f_preview, text="—", font=("Segoe UI", 9, "italic"))
            lbl_preview.pack()

            def _refresh_preview(*_):
                try:
                    _facteurs_exp = {1: 2.0, 2: 1.5, 3: 1.0, 4: 0.70, 5: 0.40}
                    exp = max(1, min(5, int(ent_exp.get())))
                    age = max(18, min(80, int(ent_age.get())))
                    base = float(ent_pct.get())
                    f_e = _facteurs_exp.get(exp, 1.0)
                    f_a = (1.35 if age <= 28
                           else 1.35 - (age - 28) / 12 * 0.35 if age <= 40
                           else 1.0 - (age - 40) / 15 * 0.20 if age <= 55
                           else max(0.60, 0.80 - (age - 55) / 10 * 0.20))
                    pct_eff = min(1.0, base * f_e * f_a)
                    # Vitesse age
                    if age <= 28:
                        vf = 1.10
                    elif age <= 45:
                        vf = 1.10 - (age - 28) / 17 * 0.15
                    elif age <= 60:
                        vf = 0.95 - (age - 45) / 15 * 0.15
                    else:
                        vf = max(0.70, 0.80 - (age - 60) / 10 * 0.10)
                    v_eff = 8.0 * vf
                    lbl_preview.config(
                        text=f"Taux d'erreur effectif ≈ {pct_eff*100:.2f} %   |   "
                             f"Vitesse ≈ {v_eff:.1f} px/tick   (à 9h, reposé)"
                    )
                except (ValueError, TypeError):
                    lbl_preview.config(text="— valeurs invalides —")

            ent_exp.bind("<KeyRelease>", _refresh_preview)
            ent_age.bind("<KeyRelease>", _refresh_preview)
            ent_pct.bind("<KeyRelease>", _refresh_preview)
            _refresh_preview()

            # ── Sauvegarde ───────────────────────────────────────────────────────
            def save_tech():
                try:
                    nom = ent_nom.get().strip()
                    exp = max(1, min(5, int(ent_exp.get())))
                    age = max(18, min(80, int(ent_age.get())))
                    pct = float(ent_pct.get())
                    seuil = float(ent_seuil.get()) / 100.0
                    taux = float(ent_taux.get())
                    recup_nuit = max(0.0, min(1.0, float(ent_recup.get()) / 100.0))
                    cap_max = max(1, int(ent_cap.get()))
                    m_data["nom"] = nom
                    m_data["experience"] = exp
                    m_data["age"] = age
                    m_data["pct_erreur_tech"] = pct
                    m_data["seuil_charge_fatigue"] = seuil
                    m_data["taux_montee_fatigue"] = taux
                    m_data["taux_recuperation_nuit"] = recup_nuit
                    m_data["capacite_max_tubes"] = cap_max
                    # Sauvegarder les paramètres personnel globaux
                    if "personnel" not in self.config_manager.data:
                        self.config_manager.data["personnel"] = {}
                    cap_jour = max(1, int(ent_cap_jour.get()))
                    seuil_acc = max(1, int(ent_seuil_acc.get()))
                    self.config_manager.data["personnel"]["capacite_journaliere_normale"] = cap_jour
                    self.config_manager.data["personnel"]["seuil_accumulation_alerte"] = seuil_acc
                    self.config_manager.sauvegarder()
                    popup.destroy()
                except ValueError:
                    messagebox.showwarning("Erreur de saisie", "Valeurs numériques invalides.")

            ttk.Button(popup, text="💾 SAUVER TECHNICIEN", command=save_tech,
                       padding=10).pack(pady=12)

        # --- CAS 4 : SORTIE ---
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
            
        # 2. Les Machines
        machines = self.config_manager.get_machines()
        for nom, m in machines.items():
            self.dessiner_bloc_machine(m["coords"]["x"], m["coords"]["y"], nom, m["type"])

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
        popup.geometry("700x600")
        popup.grab_set()

        ttk.Label(popup, text="🧪 Définissez les procédures pour chaque type de tube", 
                  font=("Segoe UI", 12, "bold")).pack(pady=10)

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

        # --- BOUTONS DE SAUVEGARDE ---
        frame_save = ttk.Frame(popup)
        frame_save.pack(fill="x", pady=10)
        ttk.Button(frame_save, text="💾 SAUVER", command=lambda: self.sauver_workflow()).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_save, text="Fermer", command=popup.destroy).pack(side=tk.LEFT, padx=5)

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
        except ValueError:
            messagebox.showwarning("Erreur", "Valeurs numériques invalides (lot / urgence).")
            return

        self.config_manager.ajouter_type_tube(
            nom_type, couleur, etapes,
            pct_urgent=pct_urgent,
            taille_lot_min=lot_min,
            taille_lot_max=lot_max
        )
        messagebox.showinfo("Succès", f"Procédure '{nom_type}' sauvegardée !")