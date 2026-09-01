"""Mixin _TabConfigPopup pour TabConfig — extrait de ui/tab_config.py.

Ces méthodes utilisent `self.xxx` défini dans TabConfig.__init__.
"""
import tkinter as tk
from tkinter import ttk


class _TabConfigPopup:
    """Mixin : ne pas instancier directement."""

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
        # Inclut les machines en attente (get_machines_avec_pending)
        toutes = self.config_manager.get_machines_avec_pending()
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

            def _supprimer_depuis_popup_s():
                if messagebox.askyesno("Supprimer", f"Supprimer {self.selected_machine} ?", parent=popup):
                    popup.destroy()
                    self.supprimer_selection()

            tk.Button(frame_bas_s, text="🗑️ Supprimer",
                      bg=theme.BTN_DEL_BG, fg=theme.BTN_DEL_FG,
                      font=theme.FONT_BTN_DEL,
                      activebackground=theme.BTN_DEL_ACT,
                      relief="flat", cursor="hand2",
                      command=_supprimer_depuis_popup_s).pack(side="right", padx=(8, 0))
            ttk.Button(frame_bas_s, text="💾 SAUVER", command=save_stockage, padding=10).pack(side="right")

        elif type_m not in _TYPES_SPECIAUX:
            # --- Bouton SAUVER ancré en bas (avant le contenu pour rester visible) ---
            frame_bas = ttk.Frame(popup)
            frame_bas.pack(side=tk.BOTTOM, fill="x", pady=8, padx=20)

            def _supprimer_depuis_popup():
                if messagebox.askyesno("Supprimer", f"Supprimer {self.selected_machine} ?", parent=popup):
                    popup.destroy()
                    self.supprimer_selection()

            tk.Button(frame_bas, text="🗑️ Supprimer",
                      bg=theme.BTN_DEL_BG, fg=theme.BTN_DEL_FG,
                      font=theme.FONT_BTN_DEL,
                      activebackground=theme.BTN_DEL_ACT,
                      relief="flat", cursor="hand2",
                      command=_supprimer_depuis_popup).pack(side="right", padx=(8, 0))

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

                    btn_del = tk.Button(f_line, text="✕",
                                        fg=theme.BTN_DEL_BG, bd=0,
                                        font=theme.FONT_NOTE,
                                        activeforeground=theme.BTN_DEL_ACT,
                                        cursor="hand2",
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

            ttk.Button(frame_bas, text="💾 SAUVER MACHINE", command=save, padding=10).pack(side="right")

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
