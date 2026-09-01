# MAGsim

**Jumeau numérique de laboratoire médical** — un simulateur de bureau qui modélise l'arrivée de tubes de prélèvement dans un labo, leur traitement par des machines (centrifugeuse, automate...) et le déplacement de techniciens, avec des facteurs humains réalistes (fatigue, expérience, âge, erreurs).

L'ambition dépasse le simulateur d'un seul labo : à terme, simuler un établissement de santé entier, composé de plusieurs « organes » (labo, bloc chirurgical, pharmacie...) reliés entre eux. Voir [`ARCHITECTURE.md`](ARCHITECTURE.md) pour la vision complète et la feuille de route.

## Fonctionnalités

L'application (Tkinter) s'organise en six onglets :

| Onglet | Rôle |
|---|---|
| 🔗 **Réseau** | Positionne le labo et les services externes sur une grille, trace les chemins de transport, dessine des zones de bâtiment. |
| ⚙️ **Configuration** | Plan du labo, machines, catalogue de protocoles, et types de tubes (workflows que suit chaque échantillon). |
| 🚀 **Simulation Live** | Cœur du produit : moteur SimPy — arrivées selon un profil horaire réaliste (loi Gamma), techniciens en pathfinding A*, files et priorités. |
| 📊 **Analyse & Goulots** | Statistiques et graphiques matplotlib — temps de traitement, occupation des machines, détection de goulots. |
| 🔍 **Diagnostic** | Validation automatique de la configuration et insights (couverture horaire, corrélation maladie/attente...). |
| 🤖 **Assistant IA** | Répond en langage naturel à un gestionnaire non technique et propose des patchs de configuration applicables. |

**Modèle métier :** un tube entre dans le labo avec un *type* (ex. « Biochimie », « Urgence ») qui fixe sa couleur, son taux d'urgence et son *workflow*. Un technicien va le chercher et le transporte vers la machine compatible la moins chargée (algorithme fill-first), jusqu'à ce que le workflow soit épuisé et que le tube sorte.

## Stack

| Composant | Techno |
|---|---|
| Interface | Python 3 / Tkinter |
| Moteur de simulation | [SimPy](https://simpy.readthedocs.io/) 4 |
| Configuration du labo | JSON (`data/config_mag.json`), versionné avec git |
| Données métier (consommables) | SQLite (`data/magsim.db`, généré au démarrage, hors git) |
| Graphiques | matplotlib |
| Assistant IA | Ollama (local) ou GitHub Models (cloud, via token Copilot) |
| Voix (prototype, optionnel) | Gradio + faster-whisper + edge-tts |

## Démarrer

Aucun fichier de dépendances n'existe encore ([#4](https://github.com/gillisma-bit/MAGsim/issues/4)) — installez le nécessaire à la main :

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install simpy matplotlib gradio pytest
```

> Sur macOS avec Python installé via Homebrew, Tkinter n'est pas toujours inclus par défaut. Si `import tkinter` échoue, installez le paquet séparément (`brew install python-tk@3.13`, en adaptant la version).

Lancer l'application :

```bash
python3 main.py
```

Lancer les tests (102 tests) :

```bash
pytest tests/
```

## Structure du dépôt

```
MAGsim/
├── main.py                  # Point d'entrée, MAGsimApp
├── core/                    # Logique métier — sans dépendance Tkinter
│   ├── config_manager.py    # Persistance JSON (labo, machines, workflows)
│   ├── db_manager.py        # Persistance SQLite (consommables)
│   ├── technician.py        # Modèle d'état technicien (fatigue, erreurs, vitesse)
│   ├── sim_utils.py         # Algorithme de routage — testable en isolation
│   ├── coordinateur_stress.py  # Détection temps réel des zones STABLE/VIGILANCE/CRITIQUE
│   ├── ai_assistant.py      # Client LLM (Ollama / GitHub Models)
│   └── sim/                 # Refactor en cours — voir avertissement ci-dessous
├── ui/                      # Interface et moteur de simulation
│   ├── tab_reseau.py, tab_config.py, tab_live.py,
│   │   tab_stats.py, tab_diagnostic.py, tab_assistant.py
│   └── dialog_rh.py, tab_horaires.py, menu_bar.py, theme.py
├── data/                    # Configuration et données (JSON + SQLite)
├── tests/                   # 102 tests (pytest)
├── docs/                    # Audit fonctionnel et technique (voir ci-dessous)
├── ARCHITECTURE.md          # Vision, choix de conception, feuille de route
└── gradio_app.py            # Prototype d'interface vocale (indépendant de main.py)
```

## État du projet

Un audit fonctionnel et technique complet a été réalisé le 1er septembre 2026 — lecture intégrale du code, suite de tests exécutée réellement, vérifications multiplateforme :

- 📄 [`docs/AUDIT_2026-09.md`](docs/AUDIT_2026-09.md) — version texte
- 🌐 [Version visuelle de l'audit](https://claude.ai/code/artifact/191179e9-121d-4196-ae77-601d9a1b19c2)

Chaque point de l'audit est aussi suivi comme issue GitHub pour rester actionnable :

- [Points de vigilance technique](https://github.com/gillisma-bit/MAGsim/issues?q=label%3Adette-technique) — dont un point **critique actif** : le refactor `962eeb1` a créé ~6000 lignes de code dupliqué, jamais réellement branchées dans l'application ([#3](https://github.com/gillisma-bit/MAGsim/issues/3)).
- [Améliorations fonctionnelles proposées](https://github.com/gillisma-bit/MAGsim/issues?q=label%3Aamelioration-fonctionnelle)

## Branches

`main` est la branche stable et à jour (réconciliée avec `refactor/architecture` via la [PR #1](https://github.com/gillisma-bit/MAGsim/pull/1)). `branche-machines` est une branche de développement plus ancienne, en retard sur `main`.

## Contribuer

Projet en développement actif, un seul mainteneur ([@gillisma-bit](https://github.com/gillisma-bit)). Avant de contribuer, un coup d'œil à [`ARCHITECTURE.md`](ARCHITECTURE.md) et à la liste des [issues ouvertes](https://github.com/gillisma-bit/MAGsim/issues) donne une bonne idée de l'état réel du code et de ce qui reste à faire.
