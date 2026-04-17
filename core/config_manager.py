import json
import os

from core.consommable import Consommable


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
                    if "consommables" not in data: data["consommables"] = {}
                    return data
            except:
                print("Erreur de lecture JSON. Création d'une config neuve.")
        
        return {
            "nom_projet": "Nouveau Projet MAGsim",
            "machines": {},
            "sol": {},
            "catalog_protocoles": {},
            "types_tubes": {},
            "consommables": {},
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
                          pct_urgent=0.0, taille_lot_min=1, taille_lot_max=1):
        """Ajoute/modifie un type de tube avec sa procédure."""
        if "types_tubes" not in self.data:
            self.data["types_tubes"] = {}
        existant = self.data["types_tubes"].get(nom, {})
        existant.update({
            "couleur":        couleur,
            "workflow":       workflow,
            "pct_urgent":     pct_urgent,
            "taille_lot_min": taille_lot_min,
            "taille_lot_max": taille_lot_max,
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

    # --- GESTION DES CONSOMMABLES ---
    def ajouter_consommable(self, id: str, nom: str, categorie: str, service: str,
                            unite_mesure: str, cout_unitaire: float = 0.0,
                            description: str = "") -> Consommable:
        """Crée ou remplace un consommable dans la liste."""
        c = Consommable(id, nom, categorie, service, unite_mesure, cout_unitaire, description)
        if "consommables" not in self.data:
            self.data["consommables"] = {}
        self.data["consommables"][id] = c.to_dict()
        self.sauvegarder()
        return c

    def supprimer_consommable(self, id: str):
        """Supprime un consommable par son identifiant."""
        if id in self.data.get("consommables", {}):
            del self.data["consommables"][id]
            self.sauvegarder()

    def get_consommables(self) -> dict[str, Consommable]:
        """Retourne tous les consommables sous forme de dict {id: Consommable}."""
        return {
            id: Consommable.from_dict(id, data)
            for id, data in self.data.get("consommables", {}).items()
        }

    def get_consommables_par_service(self, service: str) -> dict[str, Consommable]:
        """Retourne uniquement les consommables d'un service donné (CTS, CP, PG)."""
        return {
            id: c
            for id, c in self.get_consommables().items()
            if c.service == service
        }

    def get_consommable(self, id: str):
        """Retourne un consommable spécifique ou None s'il n'existe pas."""
        data = self.data.get("consommables", {}).get(id)
        return Consommable.from_dict(id, data) if data else None