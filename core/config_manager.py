import json
import os


class ConfigManager:
    def __init__(self, filepath="data/config_mag.json"):
        self.filepath = filepath
        self.data = self.charger_config()

    # ------------------------------------------------------------------ #
    #  Normalisation des protocoles                                       #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normaliser_protocoles(machines: dict, catalog: dict) -> None:
        """Corrige en-place les formats incorrects de 'protocoles' dans chaque
        machine.  Formats tolérés (produits par l'IA) :
          - list  → converti en dict vide  (les noms sont perdus, pas de temps)
          - dict  dont les valeurs sont int/float → converti en {"temps": val}
          - dict  dont les valeurs sont str → supprimé (valeur sans sens)
          - dict  dont les valeurs sont dict → inchangé (format attendu)
        Le catalogue 'catalog_protocoles' est utilisé pour compléter les
        informations manquantes (temps, type_compatible).
        """
        for machine in machines.values():
            if not isinstance(machine, dict):
                continue
            raw = machine.get("protocoles")
            # Cas 1 : liste → dict vide
            if isinstance(raw, list):
                machine["protocoles"] = {}
                continue
            # Cas 2 : pas un dict du tout
            if not isinstance(raw, dict):
                machine["protocoles"] = {}
                continue
            # Cas 3 : dict avec valeurs non-dict
            normalized = {}
            for nom, val in raw.items():
                if isinstance(val, dict):
                    normalized[nom] = val          # format correct
                elif isinstance(val, (int, float)):
                    # L'IA a mis le temps directement comme entier
                    entry = {"temps": int(val)}
                    if nom in catalog:
                        entry.setdefault("type_compatible",
                                         catalog[nom].get("type_compatible", ""))
                    normalized[nom] = entry
                else:
                    # str ou autre : on tente de récupérer depuis le catalogue
                    if nom in catalog:
                        normalized[nom] = dict(catalog[nom])
                    # sinon on ignore silencieusement
            machine["protocoles"] = normalized

    # ------------------------------------------------------------------ #
    #  Réparation des employés / horaires                                 #
    # ------------------------------------------------------------------ #
    # Valeurs par défaut d'un TECH_OFFICE créé via l'UI (dialog_rh.py)
    _TECH_DEFAULTS = {
        "type": "TECH_OFFICE",
        "capacite": 4, "file_max": 4, "seuil": 1,
        "protocoles": {},
        "experience": 3, "age": 35,
        "pct_erreur_tech": 0.01,
        "seuil_charge_fatigue": 0.70,
        "taux_montee_fatigue": 0.01,
        "taux_recuperation_nuit": 0.15,
        "capacite_max_tubes": 10,
    }
    _HORAIRE_DEFAULTS = {
        "jours": list(range(5)),
        "heure_debut": 8.0, "heure_fin": 16.0,
        "pause_debut": 12.0, "pause_fin": 13.0,
        "pool_garde": False, "actif": True,
    }

    @staticmethod
    def _coords_tech_libres(machines: dict, index: int) -> dict:
        """Calcule des coords non-occupées pour un nouveau TECH_OFFICE."""
        i = index % 10
        return {"x": 125 + i * 50, "y": 875}

    @classmethod
    def _reparer_employes(cls, data: dict) -> bool:
        """Répare en-place les artefacts IA liés aux employés.

        Stratégie — plutôt que de supprimer, le système **complète** :

        1. Entrée machines sans 'type'/'coords' mais avec des champs
           reconnaissables (nom, experience, age…) → complétée comme
           TECH_OFFICE avec les valeurs par défaut manquantes.
           Sans aucun champ reconnaissable → supprimée (garbage pur).

        2. Horaire orphelin (le nom ne correspond à aucun technicien) →
           une fiche TECH_OFFICE minimale est créée dans 'machines' pour
           que le planning reste actif.

        Retourne True si des réparations ont été effectuées (le fichier
        devra être re-sauvegardé).
        """
        machines = data.get("machines", {})
        horaires = data.get("horaires", {})
        repare   = False

        # ── 1. Compléter les fiches machines incomplètes ──────────────
        _champs_tech = {"nom", "experience", "age", "pct_erreur_tech",
                        "seuil_charge_fatigue", "taux_montee_fatigue",
                        "capacite_max_tubes", "taux_recuperation_nuit"}
        cles_invalides = [
            k for k, v in machines.items()
            if isinstance(v, dict)
            and ("type" not in v or "coords" not in v)
        ]
        for idx, k in enumerate(cles_invalides):
            v = machines[k]
            if not isinstance(v, dict) or not (_champs_tech & set(v.keys())):
                # Aucun champ reconnaissable → suppression
                print(f"[config] Entrée machines non récupérable supprimée : « {k} »")
                del machines[k]
            else:
                # Compléter avec les défauts TECH_OFFICE
                for champ, val in cls._TECH_DEFAULTS.items():
                    v.setdefault(champ, val)
                if "coords" not in v:
                    v["coords"] = cls._coords_tech_libres(machines, idx)
                nom_tech = v.get("nom", k)
                # Créer un horaire si absent
                if nom_tech not in horaires:
                    horaires[nom_tech] = dict(cls._HORAIRE_DEFAULTS)
                    print(f"[config] Horaire créé pour « {nom_tech} » (fiche complétée automatiquement)")
                print(f"[config] Fiche TECH_OFFICE complétée : « {k} » → nom={nom_tech!r}")
                repare = True

        # ── 2. Horaires orphelins → créer la fiche machine ────────────
        noms_techs = {
            v.get("nom", k)
            for k, v in machines.items()
            if isinstance(v, dict) and v.get("type") == "TECH_OFFICE"
        }
        for nom in list(horaires):
            if nom in noms_techs:
                continue
            # Générer une clé unique
            i = 1
            while f"tech_{i}" in machines:
                i += 1
            key = f"tech_{i}"
            fiche = dict(cls._TECH_DEFAULTS)
            fiche["nom"]    = nom
            fiche["coords"] = cls._coords_tech_libres(machines, i)
            machines[key]   = fiche
            noms_techs.add(nom)
            print(f"[config] Fiche TECH_OFFICE créée pour horaire orphelin : "
                  f"« {nom} » → clé={key!r}")
            repare = True

        return repare

    def charger_config(self):
        """Charge le JSON, initialise les sections manquantes et normalise les
        protocoles pour tolérer les formats incorrects générés par l'IA."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Sécurité : on s'assure que toutes les clés vitales existent
                    if "machines" not in data: data["machines"] = {}
                    if "sol" not in data: data["sol"] = {}
                    if "catalog_protocoles" not in data: data["catalog_protocoles"] = {}
                    if "types_tubes" not in data: data["types_tubes"] = {}
                    if "horaires" not in data: data["horaires"] = {}
                    # Normalise les protocoles mal formés (erreurs IA fréquentes)
                    self._normaliser_protocoles(
                        data["machines"], data["catalog_protocoles"])
                    # Répare les fiches incomplètes et les horaires orphelins
                    # (erreurs IA lors de modifications d'employés)
                    repare = self._reparer_employes(data)
                    if repare:
                        # Re-sauvegarder pour que le JSON reflète les réparations
                        try:
                            import os as _os
                            _os.makedirs(_os.path.dirname(self.filepath), exist_ok=True)
                            import json as _json
                            with open(self.filepath, 'w', encoding='utf-8') as fw:
                                _json.dump(data, fw, indent=4, ensure_ascii=False)
                            print("[config] Fichier re-sauvegardé après réparations.")
                        except Exception as e:
                            print(f"[config] Impossible de re-sauvegarder : {e}")
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
        """Retourne les machines valides pour la simulation.
        Exclut les machines avec en_attente_placement=true (ajoutées par l'IA, pas encore placées)."""
        result = {}
        for k, v in self.data.get("machines", {}).items():
            if not isinstance(v, dict) or "type" not in v or "coords" not in v:
                continue
            if v.get("en_attente_placement"):
                continue  # visible dans la zone de dépôt du plan, pas encore dans le labo
            result[k] = v
        return result

    def get_machines_avec_pending(self):
        """Retourne TOUTES les machines y compris celles en attente de placement (pour tab_config)."""
        result = {}
        for k, v in self.data.get("machines", {}).items():
            if not isinstance(v, dict) or "type" not in v or "coords" not in v:
                continue
            result[k] = v
        return result

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