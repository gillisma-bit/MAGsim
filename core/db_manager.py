"""Gestionnaire de base de données SQLite pour les données métier de MAGsim.

Ce module gère les données qui évoluent fréquemment et nécessitent des
requêtes : consommables, (et à terme protocoles enrichis, coûts, etc.).

La configuration du laboratoire (machines, sol, plan) reste dans le JSON.
"""

import sqlite3
import os
from contextlib import contextmanager

from core.consommable import Consommable


DB_PATH = "data/magsim.db"


class DBManager:
    """Gestionnaire SQLite pour les données métier.

    Utilisation
    -----------
    db = DBManager()
    db.ajouter_consommable("EDTA_K2", "Réactif EDTA K2", "reactif",
                            "CTS", "mL", 0.12, "Anticoagulant")
    liste = db.get_consommables()
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._initialiser_tables()

    # ------------------------------------------------------------------
    # Connexion
    # ------------------------------------------------------------------
    @contextmanager
    def _connexion(self):
        """Fournit une connexion avec gestion automatique des transactions."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row          # accès par nom de colonne
        conn.execute("PRAGMA journal_mode=WAL") # résiste mieux aux interruptions
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Initialisation du schéma
    # ------------------------------------------------------------------
    def _initialiser_tables(self):
        """Crée les tables si elles n'existent pas encore."""
        with self._connexion() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS consommables (
                    id            TEXT PRIMARY KEY,
                    nom           TEXT NOT NULL,
                    categorie     TEXT NOT NULL CHECK(categorie IN ('reactif','diluant','objet')),
                    service       TEXT NOT NULL CHECK(service IN ('CTS','CP','PG')),
                    unite_mesure  TEXT NOT NULL CHECK(unite_mesure IN ('mL','µL','unité')),
                    cout_unitaire REAL NOT NULL DEFAULT 0.0,
                    description   TEXT NOT NULL DEFAULT ''
                )
            """)
            # Table de lien : un protocole utilise N consommables avec une quantité
            conn.execute("""
                CREATE TABLE IF NOT EXISTS protocole_consommables (
                    protocole_id      TEXT NOT NULL,
                    consommable_id    TEXT NOT NULL,
                    quantite          REAL NOT NULL DEFAULT 0.0,
                    PRIMARY KEY (protocole_id, consommable_id),
                    FOREIGN KEY (consommable_id) REFERENCES consommables(id)
                )
            """)
            # Journal persistant des épisodes de stress (zone VIGILANCE/CRITIQUE
            # du CoordonnateurStress) — un épisode s'ouvre à l'entrée en
            # VIGILANCE ou CRITIQUE et se ferme au retour en STABLE.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes_stress (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    zone_max      TEXT NOT NULL CHECK(zone_max IN ('VIGILANCE','CRITIQUE')),
                    t_debut       REAL NOT NULL,
                    t_fin         REAL,
                    tension_max   REAL NOT NULL,
                    date_debut    TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

    # ------------------------------------------------------------------
    # CRUD — Consommables
    # ------------------------------------------------------------------
    def ajouter_consommable(self, id: str, nom: str, categorie: str, service: str,
                            unite_mesure: str, cout_unitaire: float = 0.0,
                            description: str = "") -> Consommable:
        """Crée ou remplace un consommable (INSERT OR REPLACE)."""
        # Valider via le modèle avant d'écrire
        c = Consommable(id, nom, categorie, service, unite_mesure, cout_unitaire, description)
        with self._connexion() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO consommables
                    (id, nom, categorie, service, unite_mesure, cout_unitaire, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (c.id, c.nom, c.categorie, c.service,
                  c.unite_mesure, c.cout_unitaire, c.description))
        return c

    def supprimer_consommable(self, id: str):
        """Supprime un consommable par son identifiant."""
        with self._connexion() as conn:
            conn.execute("DELETE FROM consommables WHERE id = ?", (id,))

    def get_protocoles_utilisant(self, consommable_id: str) -> list[str]:
        """Retourne la liste des IDs de protocoles qui utilisent ce consommable."""
        with self._connexion() as conn:
            rows = conn.execute(
                "SELECT protocole_id FROM protocole_consommables WHERE consommable_id = ?",
                (consommable_id,)
            ).fetchall()
        return [r["protocole_id"] for r in rows]

    def get_consommable(self, id: str):
        """Retourne un consommable spécifique ou None."""
        with self._connexion() as conn:
            row = conn.execute(
                "SELECT * FROM consommables WHERE id = ?", (id,)
            ).fetchone()
        return Consommable.from_dict(row["id"], dict(row)) if row else None

    def get_consommables(self) -> list[Consommable]:
        """Retourne tous les consommables triés par nom."""
        with self._connexion() as conn:
            rows = conn.execute(
                "SELECT * FROM consommables ORDER BY nom"
            ).fetchall()
        return [Consommable.from_dict(r["id"], dict(r)) for r in rows]

    def get_consommables_par_service(self, service: str) -> list[Consommable]:
        """Retourne les consommables d'un service donné (CTS, CP, PG)."""
        with self._connexion() as conn:
            rows = conn.execute(
                "SELECT * FROM consommables WHERE service = ? ORDER BY nom",
                (service,)
            ).fetchall()
        return [Consommable.from_dict(r["id"], dict(r)) for r in rows]

    def get_consommables_par_categorie(self, categorie: str) -> list[Consommable]:
        """Retourne les consommables d'une catégorie donnée (reactif, diluant, objet)."""
        with self._connexion() as conn:
            rows = conn.execute(
                "SELECT * FROM consommables WHERE categorie = ? ORDER BY nom",
                (categorie,)
            ).fetchall()
        return [Consommable.from_dict(r["id"], dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Journal des épisodes de stress
    # ------------------------------------------------------------------
    def ouvrir_episode_stress(self, zone: str, tension: float, t_debut: float) -> int:
        """Ouvre un nouvel épisode (entrée en VIGILANCE ou CRITIQUE). Retourne son id."""
        with self._connexion() as conn:
            cur = conn.execute("""
                INSERT INTO episodes_stress (zone_max, t_debut, tension_max)
                VALUES (?, ?, ?)
            """, (zone, t_debut, tension))
            return cur.lastrowid

    def mettre_a_jour_episode_stress(self, episode_id: int, zone: str, tension: float):
        """Met à jour la zone la plus haute atteinte et la tension max d'un épisode en cours.

        L'appelant est responsable de ne passer que la zone la plus sévère déjà
        observée (ex. ne jamais rétrograder CRITIQUE vers VIGILANCE au sein du
        même épisode) — ce module reste une couche de persistance simple.
        """
        with self._connexion() as conn:
            conn.execute("""
                UPDATE episodes_stress
                SET zone_max = ?, tension_max = MAX(tension_max, ?)
                WHERE id = ?
            """, (zone, tension, episode_id))

    def cloturer_episode_stress(self, episode_id: int, t_fin: float):
        """Ferme un épisode de stress (retour en zone STABLE)."""
        with self._connexion() as conn:
            conn.execute(
                "UPDATE episodes_stress SET t_fin = ? WHERE id = ?",
                (t_fin, episode_id)
            )

    def get_episodes_stress(self, limit: int = 200) -> list[dict]:
        """Retourne les derniers épisodes de stress, du plus récent au plus ancien."""
        with self._connexion() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes_stress ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Migration depuis JSON (usage unique au premier démarrage)
    # ------------------------------------------------------------------
    def migrer_depuis_json(self, consommables_json: dict):
        """Importe les consommables existants du JSON vers SQLite.

        À appeler une seule fois. N'écrase pas les entrées déjà présentes.
        """
        with self._connexion() as conn:
            for id, data in consommables_json.items():
                conn.execute("""
                    INSERT OR IGNORE INTO consommables
                        (id, nom, categorie, service, unite_mesure, cout_unitaire, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    id,
                    data["nom"],
                    data["categorie"],
                    data["service"],
                    data["unite_mesure"],
                    data.get("cout_unitaire", 0.0),
                    data.get("description", ""),
                ))
