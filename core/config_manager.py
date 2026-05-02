import json
import os


class ConfigManager:
    def __init__(self, filepath="data/config_mag.json"):
        self.filepath = filepath
        self.data = self.charger_config()

    def charger_config(self):
        """Charge le JSON et initialise les sections manquantes."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Sécurité : on s'assure que toutes les clés vitales existent
                    if "machines" not in data: data["machines"] = {}
                    if "sol" not in data: data["sol"] = {}
                    if "catalog_protocoles" not in data: data["catalog_protocoles"] = {}
                    if "types_tubes" not in data: data["types_tubes"] = {}
                    return data
            except:
                print("Erreur de lecture JSON. Création d'une config neuve.")
        
        return {
            "nom_projet": "Nouveau Projet MAGsim",
            "machines": {},
            "sol": {},
            "catalog_protocoles": {},
            "types_tubes": {},
        }

    def sauvegarder(self):
        """Enregistre les données dans le fichier JSON."""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

    # --- GESTION DES MACHINES ---
    def ajouter_modifier_machine(self, nom, type_m, x, y, capacite, protocoles_actifs, file_max=None, seuil=1):
        self.data["machines"][nom] = {
            "type": type_m,
            "coords": {"x": x, "y": y},
            "capacite": capacite,
            "file_max": file_max if file_max is not None else capacite,
            "seuil": seuil,
            "protocoles": protocoles_actifs
        }
        self.sauvegarder()

    def supprimer_machine(self, nom):
        if nom in self.data["machines"]:
            del self.data["machines"][nom]
            self.sauvegarder()

    def get_machines(self):
        return self.data.get("machines", {})

    # --- GESTION DU CATALOGUE DE PROTOCOLES (NOUVEAU) ---
    def ajouter_protocole_global(self, nom, temps, type_compatible):
        """Ajoute un protocole associé à un type de machine spécifique."""
        if "catalog_protocoles" not in self.data:
            self.data["catalog_protocoles"] = {}
        
        self.data["catalog_protocoles"][nom] = {
            "temps": temps,
            "type_compatible": type_compatible
        }
        self.sauvegarder()

    def modifier_protocole_global(self, nom, nouveau_temps):
        """Modifie le temps d'un protocole dans le catalogue et dans toutes les machines qui l'utilisent."""
        if nom in self.data["catalog_protocoles"]:
            self.data["catalog_protocoles"][nom]["temps"] = nouveau_temps
        # Propager dans les machines
        for m in self.data.get("machines", {}).values():
            if nom in m.get("protocoles", {}):
                m["protocoles"][nom]["temps"] = nouveau_temps
        self.sauvegarder()

    def supprimmer_protocole_global(self, nom):
        """Supprime un protocole du catalogue."""
        if nom in self.data["catalog_protocoles"]:
            del self.data["catalog_protocoles"][nom]
            self.sauvegarder()

    def get_catalog_protocoles(self):
        """Retourne le catalogue de tous les protocoles définis."""
        return self.data.get("catalog_protocoles", {})

    # --- GESTION DU SOL ---
    def sauver_tuile_sol(self, col, row, type_sol):
        cle = f"{col}_{row}"
        if type_sol == "FLOOR":
            if cle in self.data["sol"]: del self.data["sol"][cle]
        else:
            self.data["sol"][cle] = type_sol
        self.sauvegarder()

    # --- GESTION DES TYPES DE TUBES (Procédures) ---
    def ajouter_type_tube(self, nom, couleur, workflow,
                          pct_urgent=0.0, taille_lot_min=1, taille_lot_max=1,
                          duree_validite_min=0):
        """Ajoute/modifie un type de tube avec sa procédure."""
        if "types_tubes" not in self.data:
            self.data["types_tubes"] = {}
        existant = self.data["types_tubes"].get(nom, {})
        existant.update({
            "couleur":            couleur,
            "workflow":           workflow,
            "pct_urgent":         pct_urgent,
            "taille_lot_min":     taille_lot_min,
            "taille_lot_max":     taille_lot_max,
            "duree_validite_min": duree_validite_min,
        })
        # Nettoyer l'ancien champ priorite s'il subsiste
        existant.pop("priorite", None)
        self.data["types_tubes"][nom] = existant
        self.sauvegarder()

    def supprimer_type_tube(self, nom):
        """Supprime un type de tube du catalogue."""
        if nom in self.data.get("types_tubes", {}):
            del self.data["types_tubes"][nom]
            self.sauvegarder()

    def get_types_tubes(self):
        """Retourne tous les types de tubes définis."""
        return self.data.get("types_tubes", {})

    def get_type_tube(self, nom):
        """Retourne les infos d'un type de tube spécifique."""
        return self.data.get("types_tubes", {}).get(nom, None)

    def extraire_consommables_json(self) -> dict:
        """Retourne les consommables encore présents dans le JSON (migration unique)."""
        return self.data.pop("consommables", {})

    # ── GESTION DES FOURNISSEURS (blocs sources externes) ─────────────────
    def get_fournisseurs(self) -> dict:
        """Charge et retourne tous les fournisseurs depuis data/fournisseurs/.

        Les fournisseurs sont triés par nom de fichier pour un ordre stable.
        Retourne un dict {id: config_dict}.
        """
        dossier = os.path.join(os.path.dirname(self.filepath), "fournisseurs")
        if not os.path.isdir(dossier):
            return {}
        result = {}
        for fname in sorted(os.listdir(dossier)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(dossier, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    fconf = json.load(f)
                fid = fconf.get("id", fname[:-5])
                result[fid] = fconf
            except Exception as e:
                print(f"[CONFIG] Erreur lecture fournisseur {fname}: {e}")
        return result

    def sauvegarder_fournisseur(self, fournisseur: dict):
        """Sauvegarde un fournisseur dans son fichier JSON dédié."""
        dossier = os.path.join(os.path.dirname(self.filepath), "fournisseurs")
        os.makedirs(dossier, exist_ok=True)
        fid  = fournisseur.get("id", "inconnu")
        path = os.path.join(dossier, f"{fid}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fournisseur, f, indent=4, ensure_ascii=False)

    # ── GESTION DES NAVETTES ──────────────────────────────────────────────
    def get_navettes(self) -> dict:
        """Charge et retourne toutes les navettes depuis data/navettes/."""
        dossier = os.path.join(os.path.dirname(self.filepath), "navettes")
        if not os.path.isdir(dossier):
            return {}
        result = {}
        for fname in sorted(os.listdir(dossier)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(dossier, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    nconf = json.load(f)
                nid = nconf.get("id", fname[:-5])
                result[nid] = nconf
            except Exception as e:
                print(f"[CONFIG] Erreur lecture navette {fname}: {e}")
        return result

    def get_navette_principale(self) -> dict:
        """Retourne la première navette disponible, ou une config par défaut."""
        navettes = self.get_navettes()
        if navettes:
            return next(iter(navettes.values()))
        return {
            "id": "defaut", "nom": "Navette (défaut)",
            "capacite_max": 20, "mode_depart": "hybride",
            "frequence_depart_min": 30, "priorite_urgents": True,
            "pixels_par_minute": 40,
            "position_labo_canvas": {"x": 710, "y": 390},
        }

    def sauvegarder_navette(self, navette: dict):
        """Sauvegarde une navette dans son fichier JSON dédié."""
        dossier = os.path.join(os.path.dirname(self.filepath), "navettes")
        os.makedirs(dossier, exist_ok=True)
        nid  = navette.get("id", "navette")
        path = os.path.join(dossier, f"{nid}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(navette, f, indent=4, ensure_ascii=False)

    # ── GESTION DES ZONES ────────────────────────────────────────────────
    def get_zones(self) -> list:
        """Charge et retourne les zones depuis data/zones.json."""
        path = os.path.join(os.path.dirname(self.filepath), "zones.json")
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("zones", [])
        except Exception as e:
            print(f"[CONFIG] Erreur lecture zones.json: {e}")
            return []

    def sauvegarder_zones(self, zones: list):
        """Sauvegarde la liste des zones dans data/zones.json."""
        path = os.path.join(os.path.dirname(self.filepath), "zones.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"zones": zones}, f, indent=4, ensure_ascii=False)