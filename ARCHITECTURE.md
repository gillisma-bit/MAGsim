# MAGsim — Document d'architecture et feuille de route

**Version :** Avril 2026  
**Auteur :** Marc-Antoine Gillis  
**Dépôt :** https://github.com/gillisma-bit/MAGsim

---

## Table des matières

1. [Vision du projet](#1-vision-du-projet)
2. [Architecture actuelle](#2-architecture-actuelle)
3. [Couche logique métier (core/)](#3-couche-logique-métier-core)
4. [Couche interface (ui/)](#4-couche-interface-ui)
5. [Flux complet d'un tube](#5-flux-complet-dun-tube)
6. [Choix de codage expliqués](#6-choix-de-codage-expliqués)
7. [Tests](#7-tests)
8. [Vision long terme — Jumeau numérique hiérarchique](#8-vision-long-terme--jumeau-numérique-hiérarchique)
9. [Feuille de route](#9-feuille-de-route)

---

## 1. Vision du projet

MAGsim est un **simulateur de jumeau numérique de laboratoire médical**. L'objectif final dépasse la modélisation d'un seul laboratoire : il s'agit de simuler l'ensemble d'un établissement de santé en faisant interagir plusieurs services.

### Métaphore biologique (vision architecturale cible)

```
CORPS (Hôpital)
├── ORGANE : Centre de Tests Spécialisés (CTS)
│   ├── CELLULE : Centrifugeuse
│   ├── CELLULE : Automate biochimie
│   └── CELLULE : Paillasse technicien
├── ORGANE : Centre de Prélèvements (CP)
├── ORGANE : Pharmacogénomique (PG)
└── ORGANE : Bloc chirurgical
     └── → génère des prescriptions de tubes
```

Chaque **cellule** est modélisée en détail. Quand la confiance dans la modélisation est établie (validation par données réelles), elle est remplacée par une **boîte noire** (surrogate model) qui expose uniquement des paramètres d'entrée/sortie. Les organes communiquent ensuite via des **nœuds** (files d'attente inter-services, transport pneumatique, coursiers).

Le **tube de prélèvement** est le fil conducteur de toute la simulation : il naît dans le bloc chirurgical avec une prescription, traverse les organes selon son workflow, et la simulation se termine quand tous les résultats requis sont disponibles pour la décision clinique.

---

## 2. Architecture actuelle

### Stack technique

| Composant | Technologie | Justification |
|-----------|-------------|---------------|
| Interface | Python / Tkinter | Déploiement simple, pas de serveur requis |
| Moteur de simulation | SimPy 4 | Simulation à événements discrets, léger, pur Python |
| Persistance configuration | JSON | Config humainement lisible, versionnée avec git |
| Persistance données métier | SQLite | Transactions robustes, requêtes SQL, sans serveur |
| Visualisation | matplotlib | Graphiques intégrés à Tkinter |
| Pathfinding | A* (heapq) | Navigation sur grille avec obstacles |

### Structure des fichiers

```
MAGsim/
├── main.py                    ← Point d'entrée, MAGsimApp
├── core/                      ← Logique pure, sans dépendance UI
│   ├── config_manager.py      ← Persistance JSON (labo, machines, workflows)
│   ├── db_manager.py          ← Persistance SQLite (consommables)
│   ├── consommable.py         ← Modèle de données pur
│   ├── technician.py          ← Modèle d'état technicien pur
│   └── sim_utils.py           ← Algorithme de routage testable
├── ui/                        ← Présentation et simulation
│   ├── menu_bar.py            ← Barre de menus (Fichier, Config, Simulation)
│   ├── tab_config.py          ← Éditeur plan + configuration machines
│   ├── tab_live.py            ← Moteur SimPy + animation canvas (~1350 lignes)
│   ├── tab_stats.py           ← Graphiques matplotlib + simulation rapide
│   ├── tab_diagnostic.py      ← Validation de la configuration
│   └── dialog_consommables.py ← CRUD consommables (fenêtre modale)
├── data/
│   ├── config_mag.json        ← Configuration du laboratoire
│   └── magsim.db              ← Base SQLite (générée au démarrage, hors git)
└── tests/
    ├── test_workflow.py        ← Tests unitaires du routage
    └── test_distance_journaliere.py ← Tests du calcul de distance
```

### Principe de séparation

**Règle absolue :** les modules `core/` ne doivent jamais importer Tkinter ni SimPy. Ils contiennent la logique testable en isolation. Les modules `ui/` peuvent utiliser tout ce dont ils ont besoin.

---

## 3. Couche logique métier (core/)

### 3.1 ConfigManager

Gestionnaire unique de `data/config_mag.json`. Toute la configuration du laboratoire passe par lui.

**Structure JSON :**

| Clé | Contenu |
|-----|---------|
| `machines` | `{nom → {type, coords:{x,y}, capacite, file_max, seuil, protocoles, tmep, tmr, delai_max_avant_degrad}}` |
| `sol` | `{"{col}_{row}" → "COUNTER"/"WALL"}` |
| `catalog_protocoles` | `{nom → {temps (min), type_compatible}}` |
| `types_tubes` | `{nom → {couleur, workflow:[], pct_urgent, taille_lot_min, taille_lot_max}}` |

**Choix :** la modification d'un protocole dans le catalogue **propage automatiquement** dans toutes les machines qui l'utilisent (`modifier_protocole_global()`). Ceci évite les incohérences.

### 3.2 DBManager

SQLite pour les données à haute cardinalité (consommables, et à terme protocoles enrichis, coûts).

**Schéma actuel :**

```sql
CREATE TABLE consommables (
    id            TEXT PRIMARY KEY,       -- slug auto-généré
    nom           TEXT NOT NULL,
    categorie     TEXT NOT NULL CHECK(categorie IN ('reactif','diluant','objet')),
    service       TEXT NOT NULL CHECK(service IN ('CTS','CP','PG')),
    unite_mesure  TEXT NOT NULL CHECK(unite_mesure IN ('mL','µL','unité')),
    cout_unitaire REAL NOT NULL DEFAULT 0.0,
    description   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE protocole_consommables (
    protocole_id   TEXT NOT NULL,
    consommable_id TEXT NOT NULL REFERENCES consommables(id),
    quantite       REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (protocole_id, consommable_id)
);
```

**Patterns :** `@contextmanager _connexion()` avec WAL journal (résistance aux interruptions), `PRAGMA foreign_keys=ON`, `conn.row_factory = sqlite3.Row` (accès par nom de colonne). Validation via le modèle `Consommable` avant toute écriture — la base ne peut pas contenir de données invalides.

**Génération des IDs :** automatique depuis le nom (`"Réactif EDTA K2"` → `REACTIF_EDTA_K2`). Suppression dirigée des accents (NFD), majuscules, substitution des caractères non-alphanumériques par `_`. Suffixe numérique `_2`, `_3`... en cas de collision.

### 3.3 Consommable

Modèle de données pur. La validation se fait à la construction (`__init__`). Aucune dépendance extérieure. Expose `to_dict()` et `from_dict()` pour la sérialisation.

**Attributs :** `id`, `nom`, `categorie` (reactif/diluant/objet), `service` (CTS/CP/PG), `unite_mesure` (mL/µL/unité), `cout_unitaire`, `description`.

### 3.4 TechnicianState

Modèle d'état pur d'un technicien. Pas de SimPy, pas de Tkinter. Conçu pour être instancié dans `tab_live.py` mais testable sans lui.

**Paramètres fixes (configurés dans l'UI) :**

| Attribut | Signification |
|----------|---------------|
| `experience` | 1 (novice) à 5 (expert) |
| `age` | Influence vitesse et taux d'erreur |
| `pct_erreur_base` | Taux de base avant modifications |
| `seuil_charge_fatigue` | Ratio tubes_portés/capacite_max au-delà duquel la fatigue monte |
| `taux_montee_fatigue` | Incrément de fatigue par tube livré en surcharge |
| `capacite_max_tubes` | Nombre maximal de tubes portables simultanément |

**État dynamique (calculé en simulation) :**

| Attribut | Signification |
|----------|---------------|
| `fatigue_courante` | [0.0–1.0], monte sous surcharge, redescend à vide |
| `distance_parcourue_px` | Distance cumulée depuis le démarrage |
| `_distance_debut_jour_px` | Snapshot au début du jour courant pour calcul journalier |

**Calcul du taux d'erreur effectif :**

$$\text{pct\_eff} = \min(1.0,\ \text{base} \times f_{\text{exp}} \times f_{\text{age}} \times f_{\text{fatigue}} \times f_{\text{heure}})$$

- $f_{\text{exp}} \in [0.40, 2.0]$ : un expert fait 5× moins d'erreurs qu'un novice
- $f_{\text{age}}$ : juniors (<28 ans) et seniors (>50 ans) ont des profils distincts
- $f_{\text{fatigue}} = 1 + \text{fatigue\_courante} \in [1.0, 2.0]$ : fatigue peut doubler les erreurs
- $f_{\text{heure}} \in [1.0, 1.20]$ : légère hausse en fin de journée

**Calcul de la vitesse :**

$$v = 8.0\ \text{px/tick} \times f_{\text{age}} \times f_{\text{heure}} \times (1 - 0.3 \times \text{fatigue\_courante})$$

### 3.5 sim_utils — Algorithme de routage

`trouver_prochaine_machine(tube, machines, machine_queues, virtual_queues)` est la seule fonction pure de la logique de routage. Elle est testée en isolation.

**Algorithme fill-first :**
1. Peek la première étape du workflow (ne jamais pop ici)
2. Trouver tous les candidats ayant ce protocole configuré
3. Si aucun candidat → pop l'étape (warning), passer à la suivante
4. Calculer le score : `score = capacite - len(queue_actuelle)` — les machines plus remplies ont un score plus bas (fill-first)
5. Si tous les candidats ont leur file_max atteinte → retourner `(None, None, None)` — le tube attend, workflow intact
6. Retourner le candidat au score minimal

**`virtual_queues` :** compteur d'attributions fictives intra-batch pour éviter qu'un seul technicien surcharge une machine en déposant plusieurs tubes simultanément dans la même file.

---

## 4. Couche interface (ui/)

### 4.1 MAGsimApp (main.py)

Point d'entrée. Crée la fenêtre Tkinter, instancie `ConfigManager`, `DBManager`, `MenuBar`, puis les quatre onglets du `ttk.Notebook`.

**Hiérarchie des objets :**
```
root (tk.Tk, zoomed)
 └── MenuBar
 └── ttk.Notebook
      ├── [0] TabConfig(config_manager)
      ├── [1] TabLive(config_manager)
      ├── [2] TabStats(config_manager, tab_live_ref)
      └── [3] TabDiagnostic(config_manager)
```

L'onglet Diagnostic se rafraîchit automatiquement à chaque activation via `<<NotebookTabChanged>>`.

### 4.2 MenuBar

Module autonome. Barre de menus standard avec :
- **Fichier** : Sauvegarder (`Ctrl+S`), Quitter (avec confirmation)
- **Configuration** : Plan, Machines, Personnel, Consommables, Protocoles
- **Simulation** : Lancer (`F5`), Arrêter, Statistiques, Diagnostic
- **Aide** : À propos

Le bouton X de la fenêtre est intercepté par `WM_DELETE_WINDOW` → demande confirmation.

### 4.3 TabConfig

Éditeur de plan (canvas) + panneau d'outils. Modes de dessin : SELECT, COUNTER, WALL, FLOOR, PLACE_MACHINE.

**Popup de configuration de machine — 4 cas :**

| Type | Paramètres |
|------|-----------|
| Centrifugeuse / Automate / Paillasse | capacite, file_max, seuil, protocoles (checkboxes), TMEP/TMR, disponibilité calculée, tech_requis_poste |
| ENTREE | fréquence, gamma_k, heure_début, profil horaire (tableau) |
| TECH_OFFICE | experience, age, pct_erreur, seuil_charge_fatigue, taux_montee_fatigue, capacite_max + aperçu live |
| SORTIE | (aucun paramètre) |

**Éditeur de workflows :** définit les types de tubes avec leur séquence d'étapes (pct_urgent, taille de lot, liste ordonnée des protocoles depuis le catalogue).

### 4.4 TabLive — Moteur principal

C'est le cœur de l'application (~1 350 lignes). Contient le moteur SimPy complet et l'animation canvas.

**Structure de données d'un tube :**
```python
{
    "type":     str,         # nom du type de tube
    "workflow": list[str],   # étapes restantes (modifiable)
    "couleur":  "#rrggbb",
    "arrivee":  float,       # env.now à la création
    "urgent":   bool,
    "id":       int | None   # ID canvas (None en mode headless)
}
```

**Files de contrôle du moteur :**
```python
entry_queue:    list[tube]           # tubes arrivés, non pris en charge
machine_queues: dict[nom → list]     # tubes déposés, en attente de traitement
output_queues:  dict[nom → list]     # tubes traités, prêts à être récupérés
blinking_machines: set[str]          # machines en cours de traitement
panne_machines: set[str]             # machines en panne
machine_repair_events: dict[str → simpy.Event]
```

**Processus SimPy :**

`tube_generation()` — Génère les arrivées :
$$\tau \sim \Gamma(k,\ \mu_{\text{base}} / (k \cdot f_{\text{horaire}}))$$
où $f_{\text{horaire}}$ est interpolé depuis le profil horaire configurable. La config est relue à chaque tirage (hot-reload).

`technician_process(tech)` — Boucle infinie :
1. Priorité 1 : chercher des `output_queues` non vides → récupérer les tubes traités
2. Priorité 2 : chercher dans `entry_queue` → prendre N tubes (limité par les places disponibles en aval)
3. Si rien → attendre 0.5 min (récupération passive de fatigue)

`_livrer_tubes(tech, tubes)` — Algorithme de distribution :
- Pour chaque tube, appel à `trouver_prochaine_machine()`
- Regroupe par machine destination
- Déplacement A* vers chaque machine
- Dépôt : `tube.workflow.pop(0)` confirmé au moment exact du dépôt
- Gestion des tubes reportés (machine pleine) : retry après 2 min

`traiter_batch_machine(nom, machine)` — Traitement :
- `yield timeout(temps / 10)` ← 1 unité SimPy = 1 minute réelle
- Vérification `delai_max_avant_degrad` → tubes dégradés
- Vérification panne en cours → attente de `repair_event`
- Passage dans `output_queues`

`machine_breakdown_process(nom, m)` — Pannes :
$$t_{\text{panne}} \sim \text{Exp}(1/\text{TMEP}),\quad t_{\text{réparation}} \sim \text{Exp}(1/\text{TMR})$$

**Modes de simulation :**

| Mode | Animation | Usage |
|------|-----------|-------|
| LIVE | Canvas + 50 ms/tick | Présentation, observation du comportement |
| TURBO ×10 | Canvas + 10 steps/tick | Exploration rapide |
| Headless | Aucune | TabStats, simulations longues, tests |

### 4.5 TabStats

Lit `tab_live.stats_history` par référence directe. Six graphiques matplotlib optionnels :
1. Files d'attente (avec lignes `file_max` en pointillés)
2. Files de sortie
3. Taux d'occupation (fenêtre glissante 10 %)
4. Temps de transit (moyenne cumulative + glissante 20 tubes)
5. Erreurs cumulées (rejets + dégradations + pannes)
6. Distance journalière par technicien (barres groupées, mètres)

Simulation rapide headless : `threading.Thread(daemon=True)` avec callbacks via `parent.after(0, ...)` pour thread-safety.

### 4.6 TabDiagnostic

Validation automatique de la configuration en 5 sections :
1. Infrastructure (ENTREE, SORTIE, techniciens)
2. Workflows (étapes orphelines, doublons)
3. Machines inutilisées
4. Goulots potentiels : $\text{débit}[\text{étape}] = \sum_{\text{machines}} \text{capacite} / \text{temps\_protocole}$
5. Paramètres incohérents (file_max < capacite, disponibilité faible)

### 4.7 DialogConsommables

Fenêtre modale CRUD. Filtres service × catégorie. Treeview coloré par catégorie + formulaire de saisie. **Suppression protégée :** vérifie `protocole_consommables` avant de permettre la suppression.

---

## 5. Flux complet d'un tube

```
[ENTRÉE] tube_generation()
    ↓ Arrivée Gamma × profil horaire
    ↓ Type de tube aléatoire → workflow:[étape1, étape2, étape3...]
    ↓ pct_mauvais_prelevements ? → rejeté ✗
    ↓ urgent ? → insert(0) : append → entry_queue

[TECH] technician_process()
    ↓ A* vers ENTREE
    ↓ Pickup N tubes (limité par places disponibles en aval)

[ROUTING] _livrer_tubes()
    ↓ trouver_prochaine_machine() → fill-first
    ↓ A* vers machine destination
    ↓ calculer_pct_erreur_effectif() → rejet ? ✗
    ↓ workflow.pop(0) ← dépôt confirmé
    ↓ machine_queues[nom].append(tube)

[MACHINE] traiter_batch_machine()
    ↓ yield timeout(temps / 10)
    ↓ delai_max_avant_degrad ? → dégradé ✗
    ↓ panne ? → yield repair_event
    ↓ output_queues[nom].append(tube)

[RÉPÉTITION pour chaque étape du workflow]

[SORTIE] _livrer_tubes() — workflow vide
    ↓ A* vers SORTIE
    ↓ transit_time = env.now - tube.arrivee
    ↓ tubes_sortis++
```

---

## 6. Choix de codage expliqués

### Pas de SimPy.Resource — files manuelles

**Choix :** Les files (`machine_queues`, `output_queues`) sont des listes Python gérées manuellement, pas des `SimPy.Resource` standard.

**Raison :** `SimPy.Resource` gère un seul slot à la fois. Les machines de laboratoire traitent des **lots** (batch), ont des priorités d'urgence, et leur capacité est configurable. Les files manuelles donnent un contrôle total : seuil d'urgence, taille de lot variable, file_max configurable, inspection directe de l'état.

### Compression du temps ×10

**Choix :** `yield timeout(temps / 10)` — les protocoles sont configurés en minutes réelles mais s'exécutent 10× plus vite.

**Raison :** Les durées réelles (centrifugation : 30 min, automate : 120 min) produiraient une animation trop lente pour être utile. La compression ×10 garde la cohérence relative des durées tout en rendant la simulation observale en quelques minutes.

### Hot-reload de la configuration

**Choix :** `tube_generation()` relit la config ENTREE à chaque tirage.

**Raison :** Permet de modifier la fréquence d'arrivée, le profil horaire et les types de tubes **pendant** la simulation live, sans redémarrer — utile pour les démonstrations et l'exploration de scénarios.

### virtual_queues dans le routage

**Choix :** Compteur d'attributions fictives intra-batch passé à `trouver_prochaine_machine()`.

**Raison :** Sans ce mécanisme, si un technicien porte 5 tubes et que la seule machine disponible a 3 places, les 5 tubes seraient tous routés vers cette machine. Les virtual_queues signalent que 3 places sont "réservées" dès la première attribution, avant même que le dépôt physique soit effectué.

### Snapshot hors-boucle pour la distance journalière

**Choix :** Le snapshot `_distance_debut_jour_px` est mis à jour pour **tous** les techniciens avant le calcul journalier, pas un par un.

**Raison :** Si le snapshot est dans la boucle `for tech in technicians`, le premier technicien a son snapshot mis à jour avant que les autres soient traités, créant des distances cumulatives incorrectes pour Tech 2+. Le code corrigé capture d'abord tous les snapshots, puis calcule.

### Séparation JSON / SQLite

**Choix :** La configuration du laboratoire (structure) reste en JSON ; les données métier (consommables, à terme protocoles enrichis) vont en SQLite.

**Raison :** Le JSON est versionné par git — on peut voir l'évolution de la configuration entre commits. SQLite offre des transactions (pas de corruption partielle), des requêtes SQL, et scale mieux quand les données croissent. Les deux coexistent naturellement.

### Découplage logique/UI

**Choix :** `core/` ne contient aucun import Tkinter ou SimPy.

**Raison :** Testabilité. `test_workflow.py` tourne sans fenêtre. `TechnicianState` peut être instancié en CLI pour calibrer les formules. Ce découplage est aussi la condition pour une future migration vers une interface web : le core reste intact.

---

## 7. Tests

### test_workflow.py

Teste `core.sim_utils.trouver_prochaine_machine()` en isolation totale.

| Classe | Ce qu'elle valide |
|--------|------------------|
| `TestPremièreÉtape` | Routage correct, immutabilité du workflow, workflow vide → None |
| `TestMachinesPlaines` | Toutes pleines → (None,None,None), workflow intact |
| `TestFillFirst` | Score fill-first, virtual_queues bloquent double-attribution |
| `TestÉtapeSansConfigMachine` | Étape orpheline sautée avec warning |
| `TestIntégration` | Séquence complète 3 dépôts, consommation ordonnée du workflow |

### test_distance_journaliere.py

Documente le bug du snapshot hors-boucle et valide sa correction.

| Classe | Ce qu'elle valide |
|--------|------------------|
| `TestBugSnapshotManquant` | 2 techniciens, 3 jours, distances journalières correctes |
| `TestBuggyCodeEchoue` | Prouve que la version buggée produit des cumuls erronés pour Tech 2+ |

```bash
# Lancer les tests
cd "f:\code python\MAGsim"
python -m pytest tests/ -v
```

---

## 8. Vision long terme — Jumeau numérique hiérarchique

### 8.1 Principe des degrés d'abstraction adaptatifs

C'est l'innovation architecturale centrale de MAGsim.

**Phase 1 — Modélisation détaillée (état actuel)**
Chaque cellule (machine) est modélisée avec toute sa complexité : temps de traitement, pannes, capacité, interaction avec les techniciens, dégradation des échantillons.

**Phase 2 — Validation et mesure de confiance**
On mesure le degré de fidélité du modèle par rapport aux données réelles (lorsque disponibles) : RMSE sur le TAT, erreur sur le taux d'occupation, etc.

**Phase 3 — Abstraction (Surrogate Model)**
Quand la confiance dépasse un seuil (ex. RMSE < 5 %), le détail interne de l'organe est remplacé par une **fonction de transfert** apprise :

$$f(\text{flux\_entrant},\ N_{\text{tech}},\ \text{charge}) \rightarrow (\overline{TAT},\ \sigma_{TAT},\ \text{coût})$$

L'organe devient une boîte noire avec des ports d'entrée/sortie. On zoome là où il y a un problème, on dézoom là où la confiance est établie.

### 8.2 Architecture cible multi-niveaux

```
NIVEAU 3 — Corps (Hôpital)
┌──────────────────────────────────────────────────────────┐
│  [Labo CTS] ←──nœud─→ [Bloc chirurgical]                │
│       ↕                        ↕                         │
│  [Pharmacie] ←──nœud─→ [Labo PG]                        │
│                                                          │
│  Nœuds = files SimPy partagées entre organes             │
│          + délai transport (pneumatique, coursier)       │
└──────────────────────────────────────────────────────────┘

NIVEAU 2 — Organe (Laboratoire)
┌──────────────────────────────────────────────────────────┐
│  [Centrifugeuse] → [Paillasse] → [Automate]              │
│                                                          │
│  Modélisé finement jusqu'à validation                    │
│  → Remplacé par SurrogateModel quand confiance OK        │
└──────────────────────────────────────────────────────────┘

NIVEAU 1 — Cellule (Machine)
┌──────────────────────────────────────────────────────────┐
│  SimPy détaillé                                          │
│  Facteur humain (fatigue, expérience, âge)               │
│  Consommables, coûts, pannes                             │
└──────────────────────────────────────────────────────────┘
```

### 8.3 L'objet Specimen — fil conducteur

Le tube de prélèvement doit être modélisé comme un objet traçable end-to-end. Il naît avec une prescription, traverse les organes, et expire quand tous les résultats requis sont disponibles.

**Structure cible de l'objet Specimen :**

```python
class Specimen:
    # Identité
    id: str                      # code-barres / RFID
    patient_id: str
    service_origine: str         # "CHIRURGIE_A3", "URGENCES", etc.
    prescription: list[str]      # analyses requises
    
    # État
    workflow: list[str]          # étapes restantes
    resultats: dict[str, any]    # {analyse: valeur}
    statut: str                  # "EN_TRANSIT" | "EN_TRAITEMENT" | "COMPLET" | "REJETÉ"
    
    # Traçabilité (timeline complète)
    historique: list[dict]       # [{timestamp, organe, cellule, action, technicien}]
    
    # Qualité
    degradation: float           # [0.0–1.0]
    
    # Coûts
    cout_cumule: float           # somme des consommables utilisés
```

### 8.4 Nœuds inter-organes

Chaque connexion entre organes est un nœud avec ses propres caractéristiques :

```python
class NoeudTransport:
    source: str                  # organe source
    destination: str             # organe destination
    mode: str                    # "pneumatique" | "coursier" | "robot"
    delai_moyen: float           # minutes
    sigma_delai: float           # dispersion
    capacite: int                # tubes simultanés en transit
    priorite_urgence: bool       # file urgence séparée
```

---

## 9. Feuille de route

### Phase A — Fonctionnalités métier (en cours, branche-machines)

| Priorité | Tâche | Statut |
|----------|-------|--------|
| ✅ | Modèle Consommable + DBManager SQLite | Complété |
| ✅ | Interface CRUD Consommables | Complété |
| ✅ | Barre de menus + Quitter proprement | Complété |
| 🔄 | Lier consommables aux protocoles avec quantités | Suivant |
| 🔄 | Calculer le coût d'un protocole | Suivant |
| 🔄 | Calculer le coût d'un échantillon complet | Suivant |
| ⬜ | Afficher les coûts dans TabStats | À faire |

### Phase B — Qualité et robustesse

| Priorité | Tâche |
|----------|-------|
| ⬜ | Compléter la couverture de tests (TabLive headless) |
| ⬜ | Tests d'intégration bout-en-bout (arrivée → sortie → stats) |
| ⬜ | Validation Diagnostic plus fine (débit horaire vs capacité) |
| ⬜ | Fusion `branche-machines` → `main` via Pull Request |

### Phase C — Objet Specimen et traçabilité

| Priorité | Tâche |
|----------|-------|
| ⬜ | Créer `core/specimen.py` (objet Specimen complet) |
| ⬜ | Remplacer le dict `tube` par un objet Specimen dans TabLive |
| ⬜ | Historique d'événements par tube (timeline) |
| ⬜ | Requêtes de traçabilité dans DBManager |

### Phase D — Ingestion de données réelles

| Priorité | Tâche |
|----------|-------|
| ⬜ | Importer des données LIS (CSV/Excel) pour calibrer les paramètres |
| ⬜ | Calculer les distributions réelles (TAT, taux d'erreur) depuis l'historique |
| ⬜ | Mesure de confiance du modèle (RMSE vs données réelles) |
| ⬜ | Calibration automatique des paramètres SimPy depuis les données |

### Phase E — Architecture hiérarchique multi-organes

| Priorité | Tâche |
|----------|-------|
| ⬜ | Créer `core/organe.py` (encapsule un laboratoire SimPy) |
| ⬜ | Créer `core/noeud_transport.py` (connexion inter-organes) |
| ⬜ | Créer `core/surrogate_model.py` (boîte noire apprise) |
| ⬜ | Interface de composition d'organes (niveau hôpital) |
| ⬜ | Simulation d'un tube de la chirurgie jusqu'aux résultats complets |

### Phase F — Intelligence artificielle

| Priorité | Tâche |
|----------|-------|
| ⬜ | Détection d'anomalies en temps réel (IsolationForest) |
| ⬜ | Prédiction de charge journalière (Prophet / statsmodels) |
| ⬜ | Optimisation des configurations (Reinforcement Learning — Ray RLlib) |
| ⬜ | Interprétation LLM des résultats de simulation |

### Phase G — Interface web (collaboration étudiants)

| Priorité | Tâche |
|----------|-------|
| ⬜ | API Flask exposant config et résultats |
| ⬜ | Dashboard Plotly Dash (graphiques temps réel) |
| ⬜ | Migration base de données vers PostgreSQL |
| ⬜ | Déploiement réseau local (accès multi-utilisateurs) |

---

## Décisions architecturales à prendre en priorité

1. **Objet Specimen** — Définir sa structure avant d'ajouter des fonctionnalités qui dépend du tube (coûts, traçabilité, multi-organes). C'est le fil conducteur de tout le système.

2. **Merge branche-machines → main** — Créer une Pull Request dès que les coûts sont fonctionnels, pour garder `main` stable et permettre aux étudiants de travailler sur une base saine.

3. **Format d'import LIS** — Définir le format CSV/HL7 d'entrée pour la calibration réelle. C'est la clé de sortie de la simulation purement théorique.
