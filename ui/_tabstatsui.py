"""Mixin _TabStatsUI — extrait de tab_stats.py.

Ces méthodes utilisent `self.xxx` défini dans TabStats.__init__.
"""
import tkinter as tk
from tkinter import ttk
import ui.theme as theme
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

class _TabStatsUI:
    """Mixin : ne pas instancier directement."""

    def _build_ui(self):
        if not HAS_MATPLOTLIB:
            ttk.Label(
                self.parent,
                text="⚠️  matplotlib requis pour cet onglet.\n\nInstallez-le avec : pip install matplotlib",
                font=theme.FONT_TITLE, foreground="#c0392b", justify="center"
            ).pack(expand=True)
            return

        # --- Barre de contrôle LIVE ---
        ctrl = ttk.Frame(self.parent)
        ctrl.pack(fill="x", padx=12, pady=(6, 2))

        ttk.Button(ctrl, text="🔄  Actualiser les graphiques",
                   command=self.refresh).pack(side=tk.LEFT, padx=5)

        ttk.Button(ctrl, text="�  Effacer l'historique",
                   command=self.clear_history).pack(side=tk.LEFT, padx=5)

        ttk.Separator(ctrl, orient="vertical").pack(side=tk.LEFT, fill="y", padx=8, pady=2)

        ttk.Button(ctrl, text="🤖  Assistant IA",
                   command=self._ouvrir_assistant).pack(side=tk.LEFT, padx=5)

        # ── Cases à cocher par graphique ──────────────────────────────────
        checks = ttk.Frame(self.parent)
        checks.pack(fill="x", padx=12, pady=(0, 2))

        ttk.Label(checks, text="Graphiques affichés :",
                  font=theme.FONT_LABEL).pack(side=tk.LEFT, padx=(4, 8))

        self.show_queues = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Files d'attente",
                        variable=self.show_queues,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_output_queues = tk.BooleanVar(value=False)
        ttk.Checkbutton(checks, text="Files de sortie",
                        variable=self.show_output_queues,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_occupation = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Occupation machines",
                        variable=self.show_occupation,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_transit = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Temps de transit",
                        variable=self.show_transit,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_tat_urgents = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="TAT normal vs urgent",
                        variable=self.show_tat_urgents,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_errors = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Erreurs cumulées",
                        variable=self.show_errors,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_bienetre = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Bien-être techniciens",
                        variable=self.show_bienetre,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        self.show_arrivees = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Arrivées / heure",
                        variable=self.show_arrivees,
                        command=self.refresh).pack(side=tk.LEFT, padx=6)

        # --- Barre de simulation accélérée ---
        fast = ttk.LabelFrame(self.parent, text=" ⚡ Simulation accélérée (sans animation) ")
        fast.pack(fill="x", padx=12, pady=(2, 4))

        ttk.Label(fast, text="Durée (jours) :").pack(side=tk.LEFT, padx=(8, 2), pady=4)
        self.ent_duree = ttk.Entry(fast, width=6)
        self.ent_duree.insert(0, "2")
        self.ent_duree.pack(side=tk.LEFT, padx=2)

        ttk.Label(fast, text="  ← ex : 0.5 = demi-journée  |  1 = 1 jour (1440 min)  |  7 = semaine",
                  font=theme.FONT_NOTE, foreground="#777").pack(side=tk.LEFT, padx=4)

        self.btn_fast = ttk.Button(fast, text="▶ Lancer",
                                   command=self.lancer_simulation_rapide)
        self.btn_fast.pack(side=tk.LEFT, padx=4, pady=4)

        self.btn_debug = ttk.Button(fast, text="🐛 DEBUG",
                                    command=self.lancer_debug_rapide, width=10)
        self.btn_debug.pack(side=tk.LEFT, padx=4, pady=4)

        self.btn_stop = ttk.Button(fast, text="⏹ FORCER ARRÊT",
                                   command=self.forcer_arret_sim, width=16)
        self.btn_stop.pack(side=tk.LEFT, padx=4, pady=4)
        self.btn_stop.config(state="disabled")

        self.progress = ttk.Progressbar(fast, mode="determinate", length=200)
        self.progress.pack(side=tk.LEFT, padx=8, pady=4)

        self.lbl_fast_status = ttk.Label(fast, text="", font=theme.FONT_NOTE, foreground="#2c3e50")
        self.lbl_fast_status.pack(side=tk.LEFT, padx=4)

        # --- Zone principale : graphiques (gauche) + panel IA (milieu) + résumé (droite) ---
        main_area = tk.Frame(self.parent)
        main_area.pack(expand=True, fill="both", padx=4, pady=4)
        main_area.columnconfigure(0, weight=1)   # graphes — extensible
        main_area.columnconfigure(1, weight=0)   # séparateur
        main_area.columnconfigure(2, weight=0)   # assistant IA
        main_area.columnconfigure(3, weight=0)   # séparateur
        main_area.columnconfigure(4, weight=0)   # indicateurs
        main_area.rowconfigure(0, weight=1)

        # ── Colonne gauche : matplotlib ───────────────────────────────────────
        container = tk.Frame(main_area)
        container.grid(row=0, column=0, sticky="nsew")

        # La taille sera recalculée à chaque refresh() selon le nombre de graphiques actifs
        self.fig = Figure(figsize=(12, 7), dpi=96, facecolor="#f4f6f9")
        self.canvas_mpl = FigureCanvasTkAgg(self.fig, master=container)

        toolbar = NavigationToolbar2Tk(self.canvas_mpl, container)
        toolbar.update()
        self.canvas_mpl.get_tk_widget().pack(expand=True, fill="both")

        # ── Séparateur ────────────────────────────────────────────────────────
        tk.Frame(main_area, bg="#cccccc", width=1).grid(row=0, column=1, sticky="ns")

        # ── Colonne centrale : assistant IA intégré ───────────────────────────
        self._ia_frame = tk.Frame(main_area, bg="#13131f", width=320)
        self._ia_frame.grid(row=0, column=2, sticky="nsew")
        self._ia_frame.grid_propagate(False)

        # En-tête avec sélecteur de modèle
        ia_header = tk.Frame(self._ia_frame, bg="#13131f")
        ia_header.pack(fill="x")
        tk.Label(ia_header,
                 text="🤖  Assistant IA",
                 font=theme.FONT_SECTION,
                 bg="#13131f", fg="#cba6f7",
                 anchor="w", padx=10, pady=6).pack(side=tk.LEFT)

        self._ia_model_var = tk.StringVar(value="…")
        self._ia_combo = ttk.Combobox(ia_header, textvariable=self._ia_model_var,
                                      width=18, state="readonly",
                                      font=theme.FONT_NOTE)
        self._ia_combo.pack(side=tk.RIGHT, padx=(0, 8), pady=4)
        self._ia_combo.bind("<<ComboboxSelected>>", self._ia_on_model_change)
        tk.Frame(self._ia_frame, bg="#313145", height=1).pack(fill="x")

        # Historique du chat
        chat_area = tk.Frame(self._ia_frame, bg="#1e1e2e")
        chat_area.pack(fill="both", expand=True, padx=0, pady=0)
        chat_area.rowconfigure(0, weight=1)
        chat_area.columnconfigure(0, weight=1)

        self._ia_chat = tk.Text(
            chat_area,
            font=theme.FONT_BODY,
            bg="#1e1e2e", fg="#cdd6f4",
            relief="flat", bd=0,
            wrap="word",
            state="disabled",
            padx=8, pady=6,
            cursor="arrow",
        )
        sb_ia = ttk.Scrollbar(chat_area, orient="vertical", command=self._ia_chat.yview)
        self._ia_chat.configure(yscrollcommand=sb_ia.set)
        sb_ia.grid(row=0, column=1, sticky="ns")
        self._ia_chat.grid(row=0, column=0, sticky="nsew")

        self._ia_chat.tag_config("user",      foreground="#89dceb", font=theme.FONT_LABEL)
        self._ia_chat.tag_config("assistant", foreground="#cdd6f4")
        self._ia_chat.tag_config("system",    foreground="#585b70", font=theme.FONT_NOTE + ("italic",))
        self._ia_chat.tag_config("error",     foreground="#f38ba8")

        # Zone de saisie
        saisie_ia = tk.Frame(self._ia_frame, bg="#181825")
        saisie_ia.pack(fill="x", padx=0, pady=0)
        saisie_ia.columnconfigure(0, weight=1)

        self._ia_saisie = tk.Text(
            saisie_ia,
            font=theme.FONT_BODY,
            bg="#181825", fg="#cdd6f4",
            relief="flat", bd=0,
            height=3,
            padx=8, pady=6,
            wrap="word",
            insertbackground="#cdd6f4",
        )
        self._ia_saisie.grid(row=0, column=0, sticky="ew")
        self._ia_saisie.bind("<Return>", self._ia_on_entree_rapide)
        self._ia_saisie.bind("<Shift-Return>", lambda e: None)

        self._ia_btn_envoyer = tk.Button(
            saisie_ia,
            text="↵",
            font=theme.FONT_LABEL,
            bg="#7c3aed", fg="white",
            relief="flat", bd=0,
            padx=10, pady=4,
            activebackground="#6d28d9",
            cursor="hand2",
            command=self._ia_envoyer,
        )
        self._ia_btn_envoyer.grid(row=0, column=1, sticky="nsew", padx=2, pady=4)

        self._ia_btn_stop = tk.Button(
            saisie_ia,
            text="◼",
            font=theme.FONT_LABEL,
            bg="#e64553", fg="white",
            relief="flat", bd=0,
            padx=8, pady=4,
            activebackground="#c0392b",
            cursor="hand2",
            command=self._ia_stopper,
            state="disabled",
        )
        self._ia_btn_stop.grid(row=0, column=2, sticky="nsew", padx=(0, 2), pady=4)

        tk.Button(
            saisie_ia,
            text="📊",
            font=theme.FONT_BODY,
            bg="#313145", fg="white",
            relief="flat", bd=0,
            padx=6, pady=4,
            activebackground="#45475a",
            cursor="hand2",
            command=self._ia_dialog_sources,
        ).grid(row=0, column=3, sticky="nsew", padx=(0, 2), pady=4)

        # Statut
        self._ia_lbl_statut = tk.Label(
            self._ia_frame,
            text="⬤  Vérification…",
            font=theme.FONT_NOTE,
            bg="#13131f", fg="#585b70",
            anchor="w", padx=8, pady=3,
        )
        self._ia_lbl_statut.pack(fill="x")

        # ── Séparateur ────────────────────────────────────────────────────────
        tk.Frame(main_area, bg="#cccccc", width=1).grid(row=0, column=3, sticky="ns")

        # ── Colonne droite : panneau résumé ───────────────────────────────────
        self._resume_frame = tk.Frame(main_area, bg="#f8f9fa", width=260)
        self._resume_frame.grid(row=0, column=4, sticky="nsew")
        self._resume_frame.grid_propagate(False)   # largeur fixe

        tk.Label(self._resume_frame,
                 text="📊  Indicateurs clés",
                 font=theme.FONT_SECTION,
                 bg="#f8f9fa", fg="#2c3e50",
                 anchor="w", padx=12, pady=8).pack(fill="x")
        tk.Frame(self._resume_frame, bg="#dde1e7", height=1).pack(fill="x")

        # Canvas scrollable pour les cartes
        self._resume_canvas = tk.Canvas(self._resume_frame, bg="#f8f9fa",
                                        highlightthickness=0, width=258)
        sb_res = ttk.Scrollbar(self._resume_frame, orient="vertical",
                               command=self._resume_canvas.yview)
        self._resume_canvas.configure(yscrollcommand=sb_res.set)
        sb_res.pack(side=tk.RIGHT, fill="y")
        self._resume_canvas.pack(side=tk.LEFT, fill="both", expand=True)

        self._resume_inner = tk.Frame(self._resume_canvas, bg="#f8f9fa")
        self._resume_win = self._resume_canvas.create_window(
            (0, 0), window=self._resume_inner, anchor="nw")

        self._resume_inner.bind("<Configure>",
            lambda _: self._resume_canvas.configure(
                scrollregion=self._resume_canvas.bbox("all")))
        self._resume_canvas.bind("<Configure>",
            lambda e: self._resume_canvas.itemconfig(self._resume_win, width=e.width))
        self._resume_canvas.bind("<MouseWheel>",
            lambda e: self._resume_canvas.yview_scroll(-1*(e.delta//120), "units"))

        # Message initial
        self._resume_placeholder = tk.Label(
            self._resume_inner,
            text="Lancez une simulation\npuis cliquez sur\nActualiser.",
            font=theme.FONT_NOTE + ("italic",), bg="#f8f9fa", fg="#999",
            justify="center", pady=20)
        self._resume_placeholder.pack()
