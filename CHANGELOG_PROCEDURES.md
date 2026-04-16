# 📋 Nouvelle Fonctionnalité : Éditeur de Procédures

## 🎯 Objectif
Créer et gérer les **procédures (workflows) que les tubes doivent suivre** au cours de leur analyse dans le laboratoire.

## ✨ Changements Implémentés

### 1. **Backend (ConfigManager)**
Nouvelles méthodes dans `core/config_manager.py`:
- `ajouter_type_tube(nom, priorite, couleur, workflow)` - Ajouter/modifier un type de tube
- `supprimer_type_tube(nom)` - Supprimer un type
- `get_types_tubes()` - Récupérer tous les types définis
- `get_type_tube(nom)` - Récupérer un type spécifique

### 2. **Interface (TabConfig)**
Nouvel éditeur complètement intégré dans `ui/tab_config.py`:
- 🔘 Bouton **"⚙️ Gérer les procédures de tubes"** dans le panneau de contrôle
- Fenêtre pop-up avec éditeur visuel des procédures

### 3. **Data (JSON)**
Nouvelle section dans `data/config_mag.json`:
```json
"types_tubes": {
    "Biochimie": {
        "priorite": 2,
        "couleur": "#3498db",
        "workflow": ["Centri_Lente", "Analyseur_A"]
    },
    "Hématologie": {...},
    ...
}
```

### 4. **Simulation (TabLive)**
Mise à jour pour charger les procédures depuis la config:
- Les `types_tubes` sont maintenant chargés depuis le JSON
- Fallback vers des valeurs par défaut si aucun type défini
- La simulation utilise les workflows configurés

## 🖥️ Comment Utiliser

### Accéder à l'Éditeur
1. Ouvrir MAGsim
2. Aller à l'onglet **CONFIGURATION**
3. Cliquer sur le bouton **"⚙️ Gérer les procédures de tubes"**

### Créer un Nouveau Type de Tube
1. Cliquer sur **"➕ Nouveau type"**
2. Entrer un nom (ex: "Biochimie", "Urgence", etc.)
3. Configurer:
   - **Priorité**: 1 = urgent, 3 = normal
   - **Couleur**: Code hex (ex: #3498db)
4. Ajouter les étapes du workflow
5. Cliquer **"💾 SAUVER"**

### Configurer les Étapes d'un Workflow
1. Sélectionner un type de tube dans la liste
2. Cliquer **"➕ Ajouter étape"**
3. Sélectionner un protocole/étape disponible
4. Répéter pour chaque étape
5. Cliquer **"💾 SAUVER"**

### Exemple de Procédure
**Type**: Biochimie  
**Priorité**: 2  
**Couleur**: Bleu (#3498db)  
**Workflow**:
1. Centrifugeuse (Centri_Lente) - 600s
2. Analyseur (Analyseur_A) - 120s
3. Sortie

## 📊 Structure des Données

```
types_tubes
├── "Biochimie"
│   ├── priorite: 2
│   ├── couleur: "#3498db"
│   └── workflow: ["Centri_Lente", "Analyseur_A"]
├── "Hématologie"
│   ├── priorite: 2
│   ├── couleur: "#9b59b6"
│   └── workflow: []
└── ...
```

## 🔌 Intégration avec la Simulation
Lors du lancement de la simulation (onglet SIMULATION LIVE):
- Les tubes générés à l'ENTRÉE auront un type aléatoire parmi les types définis
- Chaque tube suivra son workflow spécifique
- Les étapes doivent correspondre à des protocoles disponibles dans les machines

## ⚠️ Remarques Importantes

- Les **protocoles** doivent être définis au préalable dans les machines (voir onglet CONFIGURATION)
- Si une étape du workflow n'existe pas, la simulation l'ignorera
- Les couleurs utilisent le format **hex** (#RRGGBB)
- La **priorité** affecte l'ordre de traitement des tubes

## 🚀 Prochaines Étapes Possibles
- Ajouter des **templates** de procédures pré-définis
- Gérer les **branchements conditionnels** dans les workflows
- Ajouter des **statistiques par type** dans l'onglet d'analyse
