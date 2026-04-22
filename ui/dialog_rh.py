"""Fenêtre de gestion unifiée du personnel (RH + horaires)."""
import tkinter as tk
from tkinter import ttk, messagebox
import ui.theme as theme

JOURS_ABBR = ["L", "M", "Me", "J", "V", "S", "D"]
JOURS_LONG = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


class FenetreRH:
    """Fenêtre unifiée : liste des techniciens (gauche) + fiche individuelle (droite)."""

    def __init__(self, parent, config_manager, refresh_callback=None):
        self.config_manager  = config_manager
        self.refresh_callback = refresh_callback   # appelé après ajout/suppression tech
        self._tech_key       = None                # clé machine du tech sélectionné

        self.win = tk.Toplevel(parent)
        self.win.title("👥  Gestion du personnel")
        self.win.geometry("1300x760")
        self.win.minsize(1050, 600)
        self.win.resizable(True, True)
        self.win.grab_set()

        self._build_ui()
        self._charger_globaux()
        self._charger_liste()

    # ──────────────────────────────────────────────────────────────────────────
    # Construction de l'interface
    # ──────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Titre ──────────────────────────────────────────────────────────────
        tk.Label(
            self.win,
            text="👥  Gestion du personnel",
            font=theme.FONT_TITLE,
            pady=8,
        ).pack(fill="x", padx=12)
        tk.Frame(self.win, bg="#d5d8dc", height=1).pack(fill="x")

        # ── Corps principal ─────────────────────────────────────────────────────
        corps = tk.Frame(self.win)
        corps.pack(fill="both", expand=True, padx=10, pady=(8, 4))

        # ─── Gauche : liste ──────────────────────────────────────────────────
        frm_g = tk.Frame(corps, width=270)
        frm_g.pack(side=tk.LEFT, fill="y", padx=(0, 6))
        frm_g.pack_propagate(False)

        tk.Label(frm_g, text="Techniciens", font=theme.FONT_SECTION).pack(anchor="w")

        lst_frame = tk.Frame(frm_g)
        lst_frame.pack(fill="both", expand=True)
        vsb = ttk.Scrollbar(lst_frame, orient="vertical")
        vsb.pack(side=tk.RIGHT, fill="y")
        self.lb = tk.Listbox(
            lst_frame,
            yscrollcommand=vsb.set,
            font=("Segoe UI", 10),
            selectbackground="#2980b9",
            selectforeground="white",
            activestyle="none",
            relief="flat",
            borderwidth=1,
        )
        self.lb.pack(side=tk.LEFT, fill="both", expand=True)
        vsb.config(command=self.lb.yview)
        self.lb.bind("<<ListboxSelect>>", self._on_select)

        ttk.Button(frm_g, text="➕  Nouveau technicien", command=self._ajouter).pack(
            fill="x", pady=(8, 2)
        )
        ttk.Button(frm_g, text="🗑  Supprimer", command=self._supprimer).pack(
            fill="x", pady=2
        )

        # ─── Séparateur vertical ───────────────────────────────────────────
        tk.Frame(corps, bg="#d5d8dc", width=1).pack(side=tk.LEFT, fill="y", padx=4)

        # ─── Droite : fiche ────────────────────────────────────────────────
        frm_d = tk.Frame(corps)
        frm_d.pack(side=tk.LEFT, fill="both", expand=True)

        # Canvas + scrollbar pour la fiche (peut être haute)
        canv_d = tk.Canvas(frm_d, highlightthickness=0)
        vsb_d  = ttk.Scrollbar(frm_d, orient="vertical", command=canv_d.yview)
        canv_d.configure(yscrollcommand=vsb_d.set)
        vsb_d.pack(side=tk.RIGHT, fill="y")
        canv_d.pack(side=tk.LEFT, fill="both", expand=True)
        canv_d.bind_all("<MouseWheel>", lambda e: self._on_wheel(e, canv_d))
        self.win.bind("<Destroy>", lambda e: canv_d.unbind_all("<MouseWheel>"))

        self._frm_inner = tk.Frame(canv_d)
        self._cwin_id = canv_d.create_window((0, 0), window=self._frm_inner, anchor="nw")
        self._frm_inner.bind(
            "<Configure>",
            lambda e: canv_d.configure(scrollregion=canv_d.bbox("all")),
        )
        canv_d.bind(
            "<Configure>",
            lambda e: canv_d.itemconfig(self._cwin_id, width=e.width),
        )

        # Message initial
        self._lbl_vide = tk.Label(
            self._frm_inner,
            text="← Sélectionnez un technicien dans la liste",
            foreground="gray",
            font=("Segoe UI", 11, "italic"),
            pady=40,
        )
        self._lbl_vide.pack(expand=True)

        # Formulaire (masqué jusqu'à sélection)
        self._frm_fiche = tk.Frame(self._frm_inner)
        self._build_fiche(self._frm_fiche)

        # ── Bas : paramètres globaux ────────────────────────────────────────
        tk.Frame(self.win, bg="#d5d8dc", height=1).pack(fill="x")
        self._build_globaux()

        # ── Boutons principaux ──────────────────────────────────────────────
        bas = tk.Frame(self.win, pady=6)
        bas.pack(fill="x")
        ttk.Button(bas, text="💾  Sauvegarder les paramètres globaux",
                   command=self._sauver_globaux, padding=7).pack(side=tk.RIGHT, padx=12)
        ttk.Button(bas, text="Fermer", command=self.win.destroy, padding=7).pack(
            side=tk.RIGHT, padx=4
        )

    def _on_wheel(self, event, canvas):
        try:
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # Fiche individuelle
    # ──────────────────────────────────────────────────────────────────────────

    def _build_fiche(self, parent):

        # ── Caractéristiques RH ────────────────────────────────────────────
        f_rh = ttk.LabelFrame(parent, text="👤 Caractéristiques", padding=10)
        f_rh.pack(fill="x", padx=8, pady=(6, 4))
        f_rh.columnconfigure(0, minsize=260, weight=0)
        f_rh.columnconfigure(1, weight=0)
        f_rh.columnconfigure(2, weight=1)

        _descs = [
            "Affiché dans les rapports et indicateurs",
            "×2.0 (novice) → ×0.4 (expert) sur le taux d'erreur",
            "Jeune ↑ vitesse + ↑ erreurs  |  Senior ↓ vitesse + ↓ erreurs",
            "Modulé par expérience · âge · fatigue · heure",
            "Au-dessus de ce % de capacité, la fatigue commence à monter",
            "Incrément par tube livré en surcharge (ex. 0.01)",
            "% de mécontentement effacé chaque nuit de repos (défaut 15 %)",
            "",
        ]
        _labels = [
            "Nom / identifiant :",
            "Expérience (1 = novice  …  5 = expert) :",
            "Âge (années) :",
            "Taux d'erreur de base (0.0 – 1.0) :",
            "Seuil de surcharge (%) :",
            "Taux de montée de fatigue :",
            "Récupération nocturne (%) :",
            "Capacité max tubes portés :",
        ]
        self._ents_fiche = {}
        _keys = ["nom", "experience", "age", "pct", "seuil", "taux", "recup", "cap"]
        for r, (lbl, k, desc) in enumerate(zip(_labels, _keys, _descs)):
            tk.Label(f_rh, text=lbl, font=theme.FONT_BODY, anchor="w").grid(
                row=r, column=0, sticky="w", pady=2, padx=(0, 6)
            )
            ent = ttk.Entry(f_rh, width=12)
            ent.grid(row=r, column=1, sticky="w", padx=(0, 6))
            self._ents_fiche[k] = ent
            if desc:
                tk.Label(f_rh, text=desc, foreground="gray", font=theme.FONT_NOTE,
                         wraplength=320, justify="left").grid(
                    row=r, column=2, sticky="w"
                )

        # ── Position du poste sur le plan ──────────────────────────────────
        r_pos = len(_keys)
        tk.Frame(f_rh, bg="#d5d8dc", height=1).grid(
            row=r_pos, column=0, columnspan=3, sticky="ew", pady=(6, 4)
        )
        tk.Label(f_rh, text="Position du bureau sur le plan :", font=theme.FONT_BODY,
                 anchor="w").grid(row=r_pos + 1, column=0, sticky="w", pady=2, padx=(0, 6))
        frm_pos = tk.Frame(f_rh)
        frm_pos.grid(row=r_pos + 1, column=1, columnspan=2, sticky="w")
        tk.Label(frm_pos, text="X :", font=theme.FONT_BODY).pack(side=tk.LEFT)
        self._ents_fiche["poste_x"] = ttk.Entry(frm_pos, width=7, justify="center")
        self._ents_fiche["poste_x"].pack(side=tk.LEFT, padx=(2, 8))
        tk.Label(frm_pos, text="Y :", font=theme.FONT_BODY).pack(side=tk.LEFT)
        self._ents_fiche["poste_y"] = ttk.Entry(frm_pos, width=7, justify="center")
        self._ents_fiche["poste_y"].pack(side=tk.LEFT, padx=2)
        tk.Label(
            f_rh,
            text="Détermine les distances de trajet en simulation",
            foreground="gray", font=theme.FONT_NOTE,
        ).grid(row=r_pos + 2, column=0, columnspan=3, sticky="w", pady=(0, 4))

        # Aperçu taux d'erreur
        self._lbl_preview = tk.Label(
            parent, text="", font=("Segoe UI", 9, "italic"), foreground="#555"
        )
        self._lbl_preview.pack(anchor="w", padx=14, pady=(2, 0))
        for k in ("experience", "age", "pct"):
            self._ents_fiche[k].bind("<KeyRelease>", self._refresh_preview)

        # ── Horaire individuel ─────────────────────────────────────────────
        f_h = ttk.LabelFrame(parent, text="🗓️ Horaire", padding=10)
        f_h.pack(fill="x", padx=8, pady=(0, 4))

        # Jours
        frm_j = tk.Frame(f_h)
        frm_j.pack(anchor="w", pady=(0, 6))
        tk.Label(frm_j, text="Jours :", font=theme.FONT_BODY).pack(side=tk.LEFT, padx=(0, 8))
        self._var_jours = []
        for j, abbr in enumerate(JOURS_ABBR):
            v = tk.BooleanVar()
            tk.Checkbutton(frm_j, text=abbr, variable=v, font=theme.FONT_BODY).pack(
                side=tk.LEFT, padx=2
            )
            self._var_jours.append(v)

        # Heures + pause sur une ligne
        frm_hp = tk.Frame(f_h)
        frm_hp.pack(anchor="w")
        for lbl, attr, defval in [
            ("Début :", "_ent_hdeb", "8.0"),
            ("Fin :", "_ent_hfin", "16.0"),
            ("Pause deb :", "_ent_pdeb", "12.0"),
            ("→ fin :", "_ent_pfin", "13.0"),
        ]:
            tk.Label(frm_hp, text=lbl, font=theme.FONT_BODY).pack(side=tk.LEFT, padx=(8, 2))
            ent = ttk.Entry(frm_hp, width=7, justify="center")
            ent.insert(0, defval)
            ent.pack(side=tk.LEFT, padx=(0, 4))
            setattr(self, attr, ent)

        # Pool garde + actif
        frm_fl = tk.Frame(f_h)
        frm_fl.pack(anchor="w", pady=(6, 0))
        self._var_pool  = tk.BooleanVar()
        self._var_actif = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm_fl, text="Pool gardes 🔔", variable=self._var_pool).pack(
            side=tk.LEFT, padx=(0, 20)
        )
        ttk.Checkbutton(frm_fl, text="Actif", variable=self._var_actif).pack(side=tk.LEFT)

        # Sauver fiche
        ttk.Button(
            parent, text="💾  Sauver cette fiche", command=self._sauver_fiche, padding=6
        ).pack(anchor="e", padx=8, pady=6)

    # ──────────────────────────────────────────────────────────────────────────
    # Paramètres globaux
    # ──────────────────────────────────────────────────────────────────────────

    def _build_globaux(self):
        frm = tk.Frame(self.win, pady=5, padx=10)
        frm.pack(fill="x")

        # Pauses
        f_p = ttk.LabelFrame(frm, text="🍽️  Pauses déjeuner globales", padding=6)
        f_p.pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 8))
        self._var_rot_auto  = tk.BooleanVar()
        self._var_p_debut   = tk.StringVar(value="12.0")
        self._var_p_duree   = tk.StringVar(value="30")
        ttk.Checkbutton(f_p, text="Rotation automatique", variable=self._var_rot_auto).grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        tk.Label(f_p, text="Créneau début :", font=theme.FONT_BODY).grid(row=1, column=0, sticky="w")
        ttk.Entry(f_p, textvariable=self._var_p_debut, width=7, justify="center").grid(
            row=1, column=1, padx=4
        )
        tk.Label(f_p, text="Durée (min) :", font=theme.FONT_BODY).grid(row=1, column=2, sticky="w")
        ttk.Entry(f_p, textvariable=self._var_p_duree, width=7, justify="center").grid(
            row=1, column=3, padx=4
        )

        # Gardes
        f_g = ttk.LabelFrame(frm, text="🔔  Gardes", padding=6)
        f_g.pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 8))
        self._var_trajet  = tk.StringVar(value="20")
        self._var_forfait = tk.StringVar(value="3")
        self._var_gS      = tk.StringVar(value="Personne")
        self._var_gD      = tk.StringVar(value="Personne")
        self._var_gF      = tk.StringVar(value="Personne")
        tk.Label(f_g, text="Trajet (min) :", font=theme.FONT_BODY).grid(row=0, column=0, sticky="w")
        ttk.Entry(f_g, textvariable=self._var_trajet, width=7, justify="center").grid(
            row=0, column=1, padx=4
        )
        tk.Label(f_g, text="Forfait min (h) :", font=theme.FONT_BODY).grid(row=0, column=2, sticky="w")
        ttk.Entry(f_g, textvariable=self._var_forfait, width=7, justify="center").grid(
            row=0, column=3, padx=4
        )
        for r, (lbl, var) in enumerate([
            ("Samedi :",   self._var_gS),
            ("Dimanche :", self._var_gD),
            ("Fériés :",   self._var_gF),
        ]):
            tk.Label(f_g, text=lbl, font=theme.FONT_BODY).grid(row=1, column=r * 2, sticky="w", pady=(4, 0))
            cb = ttk.Combobox(f_g, textvariable=var, values=["Personne", "Rotation auto"],
                              state="readonly", width=14)
            cb.grid(row=1, column=r * 2 + 1, padx=4, pady=(4, 0))
            setattr(self, f"_cb_g{['S', 'D', 'F'][r]}", cb)

        # Départ simulation
        f_d = ttk.LabelFrame(frm, text="📅  Simulation", padding=6)
        f_d.pack(side=tk.LEFT, fill="x")
        tk.Label(f_d, text="Démarre un :", font=theme.FONT_BODY).pack(anchor="w")
        self._var_jour_debut = tk.StringVar()
        ttk.Combobox(
            f_d, textvariable=self._var_jour_debut, values=JOURS_LONG,
            state="readonly", width=14,
        ).pack(pady=4)

    # ──────────────────────────────────────────────────────────────────────────
    # Chargement des données
    # ──────────────────────────────────────────────────────────────────────────

    def _charger_globaux(self):
        cfg       = self.config_manager.data
        pers      = cfg.get("personnel", {})

        self._var_rot_auto.set(pers.get("pause_rotation_auto", False))
        self._var_p_debut.set(str(pers.get("pause_creneau_debut", 12.0)))
        self._var_p_duree.set(str(int(pers.get("pause_duree_minutes", 30))))
        self._var_trajet.set(str(int(pers.get("garde_trajet_minutes", 20))))
        self._var_forfait.set(str(pers.get("garde_forfait_heures", 3.0)))

        jour_idx = int(pers.get("jour_debut_simulation", 0))
        self._var_jour_debut.set(JOURS_LONG[min(max(jour_idx, 0), 6)])

    def _charger_liste(self, reselect_key=None):
        """Remplit la Listbox depuis la config."""
        cfg      = self.config_manager.data
        machines = cfg.get("machines", {})
        horaires = cfg.get("horaires", {})
        pers     = cfg.get("personnel", {})

        # Mettre à jour les combos gardes avec les noms de techs
        noms = [
            m.get("nom") or k
            for k, m in machines.items()
            if m.get("type") == "TECH_OFFICE"
        ]
        options = ["Personne", "Rotation auto"] + noms
        for attr in ("_cb_gS", "_cb_gD", "_cb_gF"):
            cb = getattr(self, attr)
            cb["values"] = options
        self._var_gS.set(pers.get("garde_samedi",   "Personne"))
        self._var_gD.set(pers.get("garde_dimanche", "Personne"))
        self._var_gF.set(pers.get("garde_feries",   "Personne"))

        self._techs_keys = []
        self.lb.delete(0, tk.END)
        resel_idx = None

        for k, m in machines.items():
            if m.get("type") != "TECH_OFFICE":
                continue
            nom      = m.get("nom") or k
            h        = horaires.get(nom, {})
            hd       = h.get("heure_debut", 7)
            hf       = h.get("heure_fin",   15)
            jours    = h.get("jours", list(range(5)))
            actif    = h.get("actif", True)
            bullet   = "●" if actif else "○"
            j_txt    = "".join(JOURS_ABBR[j] for j in sorted(jours))
            self.lb.insert(tk.END, f"  {bullet}  {nom:<18}  {hd:.0f}h – {hf:.0f}h   [{j_txt}]")
            idx = len(self._techs_keys)
            self._techs_keys.append(k)
            if k == reselect_key:
                resel_idx = idx

        if resel_idx is not None:
            self.lb.selection_set(resel_idx)
            self.lb.see(resel_idx)

    # ──────────────────────────────────────────────────────────────────────────
    # Sélection / affichage de fiche
    # ──────────────────────────────────────────────────────────────────────────

    def _on_select(self, event=None):
        sel = self.lb.curselection()
        if not sel:
            return
        key = self._techs_keys[sel[0]]
        self._tech_key = key
        self._afficher_fiche(key)

    def _afficher_fiche(self, key):
        cfg  = self.config_manager.data
        m    = cfg["machines"].get(key, {})
        nom  = m.get("nom") or key
        h    = cfg.get("horaires", {}).get(nom, {})

        self._lbl_vide.pack_forget()
        self._frm_fiche.pack(fill="both", expand=True)

        coords = m.get("coords", {})
        valeurs = {
            "nom":        nom,
            "experience": m.get("experience", 3),
            "age":        m.get("age", 35),
            "pct":        m.get("pct_erreur_tech", 0.0),
            "seuil":      int(float(m.get("seuil_charge_fatigue", 0.70)) * 100),
            "taux":       m.get("taux_montee_fatigue", 0.01),
            "recup":      int(float(m.get("taux_recuperation_nuit", 0.15)) * 100),
            "cap":        m.get("capacite_max_tubes", 10),
            "poste_x":    int(coords.get("x", 0)),
            "poste_y":    int(coords.get("y", 0)),
        }
        for k, v in valeurs.items():
            ent = self._ents_fiche[k]
            ent.delete(0, tk.END)
            ent.insert(0, str(v))

        jours_actifs = h.get("jours", list(range(5)))
        for j, var in enumerate(self._var_jours):
            var.set(j in jours_actifs)

        for ent, val in [
            (self._ent_hdeb, h.get("heure_debut", 8.0)),
            (self._ent_hfin, h.get("heure_fin",   16.0)),
            (self._ent_pdeb, h.get("pause_debut",  12.0)),
            (self._ent_pfin, h.get("pause_fin",    13.0)),
        ]:
            ent.delete(0, tk.END)
            ent.insert(0, str(val))

        self._var_pool.set(h.get("pool_garde", False))
        self._var_actif.set(h.get("actif", True))
        self._refresh_preview()

    def _refresh_preview(self, *_):
        try:
            _f_exp = {1: 2.0, 2: 1.5, 3: 1.0, 4: 0.70, 5: 0.40}
            exp  = max(1, min(5, int(self._ents_fiche["experience"].get())))
            age  = max(18, min(80, int(self._ents_fiche["age"].get())))
            base = float(self._ents_fiche["pct"].get())
            f_e  = _f_exp.get(exp, 1.0)
            f_a  = (
                1.35 if age <= 28
                else 1.35 - (age - 28) / 12 * 0.35 if age <= 40
                else 1.0  - (age - 40) / 15 * 0.20 if age <= 55
                else max(0.60, 0.80 - (age - 55) / 10 * 0.20)
            )
            pct_eff = min(1.0, base * f_e * f_a)
            self._lbl_preview.config(
                text=f"Aperçu : taux d'erreur effectif ≈ {pct_eff * 100:.2f} %"
                     f"  (expérience {exp}/5 · âge {age} ans · sans fatigue)"
            )
        except (ValueError, TypeError):
            self._lbl_preview.config(text="")

    # ──────────────────────────────────────────────────────────────────────────
    # Sauvegarde
    # ──────────────────────────────────────────────────────────────────────────

    def _sauver_fiche(self):
        if not self._tech_key:
            return
        key = self._tech_key
        cfg = self.config_manager.data
        m   = cfg["machines"].get(key)
        if m is None:
            return
        nom_ancien = m.get("nom") or key

        try:
            nom    = self._ents_fiche["nom"].get().strip() or nom_ancien
            exp    = max(1, min(5, int(self._ents_fiche["experience"].get())))
            age    = max(18, min(80, int(self._ents_fiche["age"].get())))
            pct    = float(self._ents_fiche["pct"].get())
            seuil  = float(self._ents_fiche["seuil"].get()) / 100.0
            taux   = float(self._ents_fiche["taux"].get())
            recup  = max(0.0, min(1.0, float(self._ents_fiche["recup"].get()) / 100.0))
            cap    = max(1, int(self._ents_fiche["cap"].get()))
            poste_x = float(self._ents_fiche["poste_x"].get())
            poste_y = float(self._ents_fiche["poste_y"].get())
            hdeb   = float(self._ent_hdeb.get())
            hfin   = float(self._ent_hfin.get())
            pdeb   = float(self._ent_pdeb.get())
            pfin   = float(self._ent_pfin.get())
        except ValueError:
            messagebox.showwarning("Erreur de saisie", "Valeurs numériques invalides.")
            return

        m.update({
            "nom": nom, "experience": exp, "age": age,
            "pct_erreur_tech": pct, "seuil_charge_fatigue": seuil,
            "taux_montee_fatigue": taux, "taux_recuperation_nuit": recup,
            "capacite_max_tubes": cap,
            "coords": {"x": poste_x, "y": poste_y},
        })

        horaires = cfg.setdefault("horaires", {})
        h_existant = horaires.pop(nom_ancien, {})
        h_existant.update({
            "jours":       [j for j, v in enumerate(self._var_jours) if v.get()],
            "heure_debut": hdeb,
            "heure_fin":   hfin,
            "pause_debut": pdeb,
            "pause_fin":   pfin,
            "pool_garde":  self._var_pool.get(),
            "actif":       self._var_actif.get(),
        })
        horaires[nom] = h_existant

        self.config_manager.sauvegarder()
        self._charger_liste(reselect_key=key)
        messagebox.showinfo("Sauvegardé", f"Fiche de {nom} enregistrée.")

    def _sauver_globaux(self):
        cfg  = self.config_manager.data
        pers = cfg.setdefault("personnel", {})

        try:
            pers["pause_rotation_auto"]  = self._var_rot_auto.get()
            pers["pause_creneau_debut"]  = float(self._var_p_debut.get())
            pers["pause_duree_minutes"]  = int(float(self._var_p_duree.get()))
            pers["garde_trajet_minutes"] = int(float(self._var_trajet.get()))
            pers["garde_forfait_heures"] = float(self._var_forfait.get())
            pers["garde_samedi"]         = self._var_gS.get()
            pers["garde_dimanche"]       = self._var_gD.get()
            pers["garde_feries"]         = self._var_gF.get()
            jd = self._var_jour_debut.get()
            pers["jour_debut_simulation"] = JOURS_LONG.index(jd) if jd in JOURS_LONG else 0
        except ValueError:
            messagebox.showwarning("Erreur de saisie", "Paramètres globaux invalides (nombres attendus).")
            return

        self.config_manager.sauvegarder()
        messagebox.showinfo("Sauvegardé",
                            "Paramètres globaux enregistrés.\n"
                            "Pris en compte au prochain démarrage de simulation.")

    # ──────────────────────────────────────────────────────────────────────────
    # Ajout / suppression de technicien
    # ──────────────────────────────────────────────────────────────────────────

    def _ajouter(self):
        cfg      = self.config_manager.data
        machines = cfg.setdefault("machines", {})

        # Clé unique
        i = 1
        while f"tech_{i}" in machines:
            i += 1
        key = f"tech_{i}"
        nom = f"Technicien {i}"

        machines[key] = {
            "type": "TECH_OFFICE",
            "coords": {"x": 125 + (i % 10) * 50, "y": 875},
            "capacite": 4, "file_max": 4, "seuil": 1,
            "protocoles": {},
            "nom": nom, "experience": 3, "age": 35,
            "pct_erreur_tech": 0.01,
            "seuil_charge_fatigue": 0.70,
            "taux_montee_fatigue": 0.01,
            "taux_recuperation_nuit": 0.15,
            "capacite_max_tubes": 10,
        }
        cfg.setdefault("horaires", {})[nom] = {
            "jours": list(range(5)),
            "heure_debut": 8.0, "heure_fin": 16.0,
            "pause_debut": 12.0, "pause_fin": 13.0,
            "pool_garde": False, "actif": True,
        }
        self.config_manager.sauvegarder()
        if self.refresh_callback:
            self.refresh_callback()
        self._charger_liste(reselect_key=key)
        self._tech_key = key
        self._afficher_fiche(key)

    def _supprimer(self):
        if not self._tech_key:
            messagebox.showwarning("Rien de sélectionné", "Sélectionnez d'abord un technicien.")
            return
        key = self._tech_key
        cfg = self.config_manager.data
        nom = cfg["machines"].get(key, {}).get("nom") or key

        if not messagebox.askyesno(
            "Supprimer ?",
            f"Supprimer définitivement « {nom} » ?\nSon poste sur le plan sera aussi retiré.",
        ):
            return

        cfg["machines"].pop(key, None)
        cfg.get("horaires", {}).pop(nom, None)
        self.config_manager.sauvegarder()

        if self.refresh_callback:
            self.refresh_callback()

        self._tech_key = None
        self._frm_fiche.pack_forget()
        self._lbl_vide.pack(expand=True)
        self._charger_liste()
