"""Système de design centralisé pour MAGsim.

Toutes les polices, couleurs et styles ttk sont définis ici.
Modifier une valeur = impacte l'ensemble de l'application.

Inspiration : Fluent Design (Windows 11) pour la typographie,
              palette neutre sombre/clair issue de Catppuccin Mocha.
"""
from tkinter import ttk

# ─────────────────────────────────────────────────────────────────────────────
#  Typographie  (Segoe UI partout — native Windows, lisible à toutes tailles)
# ─────────────────────────────────────────────────────────────────────────────
_F = "Segoe UI"
_M = "Consolas"          # monospace (logs, rapports)

FONT_NOTE    = (_F,  9)               # aide, copyright, légendes grises
FONT_BODY    = (_F, 10)               # texte courant
FONT_LABEL   = (_F, 10, "bold")       # labels de formulaire, colonnes tableau
FONT_SECTION = (_F, 11, "bold")       # titre de section / LabelFrame
FONT_TITLE   = (_F, 13, "bold")       # titre de chaque onglet (une fois)
FONT_TAB     = (_F, 11, "bold")       # onglets du Notebook principal
FONT_MONO    = (_M,  9)               # logs, code, rapports texte
FONT_MONO_S  = (_M, 10)              # rapports avec un peu plus d'espace
FONT_BTN_DEL = (_F,  9, "bold")       # bouton destructif (suppression)

# ─────────────────────────────────────────────────────────────────────────────
#  Palette de couleurs
# ─────────────────────────────────────────────────────────────────────────────

# Arrière-plans
BG_BASE      = "#1e1e2e"   # fond principal des zones sombres
BG_SURFACE   = "#181825"   # fond des panneaux latéraux sombres
BG_OVERLAY   = "#313244"   # survol, sélection
BG_LIGHT     = "#f4f4f8"   # fond des formulaires (onglets clairs)

# Texte
TXT_MAIN     = "#cdd6f4"   # texte principal (sur fond sombre)
TXT_MUTED    = "#6c7086"   # texte secondaire / aide
TXT_DARK     = "#1e1e2e"   # texte sur fond clair
TXT_HEADER   = "#ffffff"   # en-têtes de tableau

# Accents
ACCENT_BLUE  = "#89b4fa"   # liens, sélections
ACCENT_GREEN = "#a6e3a1"   # succès, sortie
ACCENT_RED   = "#f38ba8"   # erreurs, urgences
ACCENT_ORANGE= "#fab387"   # avertissements
ACCENT_PURPLE= "#cba6f7"   # IA assistant

# Header tableau
HEADER_BG    = "#2c3e50"   # fond en-têtes de tableau (inchangé, reconnaissable)
HEADER_FG    = "#ffffff"

# Couleurs fonctionnelles (simulation)
SIM_ENTREE   = "#2ecc71"
SIM_SORTIE   = "#e74c3c"
SIM_TECH     = "#95a5a6"
SIM_MACHINE  = "#3498db"

# Bouton destructif
BTN_DEL_BG   = "#e74c3c"
BTN_DEL_FG   = "#ffffff"
BTN_DEL_ACT  = "#c0392b"

# ─────────────────────────────────────────────────────────────────────────────
#  Application du thème ttk global
# ─────────────────────────────────────────────────────────────────────────────

def appliquer(style: ttk.Style) -> None:
    """Applique l'ensemble des styles ttk à partir d'un objet Style existant.

    À appeler UNE SEULE FOIS depuis main.py après `style.theme_use('clam')`.
    """
    style.theme_use("clam")

    # ── Notebook (onglets principaux) ─────────────────────────────────────────
    style.configure("TNotebook.Tab",
                    font=FONT_TAB,
                    padding=[15, 8])

    # ── Boutons ───────────────────────────────────────────────────────────────
    style.configure("TButton",
                    font=FONT_BODY,
                    padding=[8, 4])

    # ── Labels ────────────────────────────────────────────────────────────────
    style.configure("TLabel",
                    font=FONT_BODY)

    # ── LabelFrame (titres de section) ────────────────────────────────────────
    style.configure("TLabelframe.Label",
                    font=FONT_SECTION)

    # ── Entry & Combobox ──────────────────────────────────────────────────────
    style.configure("TEntry",     font=FONT_BODY)
    style.configure("TCombobox",  font=FONT_BODY)

    # ── Checkbutton / Radiobutton ─────────────────────────────────────────────
    style.configure("TCheckbutton", font=FONT_BODY)
    style.configure("TRadiobutton", font=FONT_BODY)

    # ── Treeview (listes) ─────────────────────────────────────────────────────
    style.configure("Treeview",
                    font=FONT_BODY,
                    rowheight=24)
    style.configure("Treeview.Heading",
                    font=FONT_LABEL)
