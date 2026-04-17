"""Modèle de données pour les produits consommables — logique pure, sans dépendance Tkinter."""


class Consommable:
    """Représente un produit consommable utilisé lors des tests.

    Attributs
    ---------
    id : str
        Identifiant unique (clé dans le JSON).
    nom : str
        Nom du produit (ex. : "Réactif EDTA", "Filtre 0.22 µm").
    categorie : str
        Type de consommable : "reactif" | "diluant" | "objet".
    service : str
        Service propriétaire de la liste :
        "CTS"  → Centre de Tests Spécialisés
        "CP"   → Centre de Prélèvements
        "PG"   → Pharmacogénomique
    unite_mesure : str
        Unité utilisée lors d'un test : "mL" | "µL" | "unité".
    cout_unitaire : float
        Coût par unité (mL ou unité selon unite_mesure).
    description : str
        Information complémentaire facultative.
    """

    CATEGORIES = ["reactif", "diluant", "objet"]

    SERVICES = {
        "CTS": "Centre de Tests Spécialisés",
        "CP":  "Centre de Prélèvements",
        "PG":  "Pharmacogénomique",
    }

    UNITES = ["mL", "µL", "unité"]

    def __init__(self, id: str, nom: str, categorie: str, service: str,
                 unite_mesure: str, cout_unitaire: float = 0.0, description: str = ""):
        if categorie not in self.CATEGORIES:
            raise ValueError(f"Catégorie invalide : '{categorie}'. Valeurs acceptées : {self.CATEGORIES}")
        if service not in self.SERVICES:
            raise ValueError(f"Service invalide : '{service}'. Valeurs acceptées : {list(self.SERVICES.keys())}")
        if unite_mesure not in self.UNITES:
            raise ValueError(f"Unité invalide : '{unite_mesure}'. Valeurs acceptées : {self.UNITES}")

        self.id = id
        self.nom = nom
        self.categorie = categorie
        self.service = service
        self.unite_mesure = unite_mesure
        self.cout_unitaire = float(cout_unitaire)
        self.description = description

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """Sérialise le consommable pour sauvegarde JSON."""
        return {
            "nom":           self.nom,
            "categorie":     self.categorie,
            "service":       self.service,
            "unite_mesure":  self.unite_mesure,
            "cout_unitaire": self.cout_unitaire,
            "description":   self.description,
        }

    @classmethod
    def from_dict(cls, id: str, data: dict) -> "Consommable":
        """Reconstruit un Consommable depuis un dictionnaire JSON."""
        return cls(
            id=id,
            nom=data["nom"],
            categorie=data["categorie"],
            service=data["service"],
            unite_mesure=data["unite_mesure"],
            cout_unitaire=data.get("cout_unitaire", 0.0),
            description=data.get("description", ""),
        )

    def __repr__(self) -> str:
        return (f"Consommable(id={self.id!r}, nom={self.nom!r}, "
                f"categorie={self.categorie!r}, service={self.service!r}, "
                f"unite={self.unite_mesure!r}, cout={self.cout_unitaire})")
