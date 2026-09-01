"""Tests du journal persistant des épisodes de stress (DBManager).

Couvre l'amélioration #16 : un épisode s'ouvre à l'entrée en VIGILANCE ou
CRITIQUE, ne rétrograde jamais sa zone au sein du même épisode, et se ferme
au retour en STABLE.
"""
import os
import tempfile

import pytest

from core.db_manager import DBManager


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)  # DBManager crée le fichier lui-même
    manager = DBManager(db_path=path)
    yield manager
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass


class TestOuvrirEtFermerEpisode:
    def test_ouvrir_episode_retourne_un_id(self, db):
        episode_id = db.ouvrir_episode_stress(zone="VIGILANCE", tension=1.3, t_debut=120.0)
        assert isinstance(episode_id, int)

    def test_episode_ouvert_apparait_dans_get_episodes(self, db):
        episode_id = db.ouvrir_episode_stress(zone="VIGILANCE", tension=1.3, t_debut=120.0)
        episodes = db.get_episodes_stress()
        assert len(episodes) == 1
        assert episodes[0]["id"] == episode_id
        assert episodes[0]["zone_max"] == "VIGILANCE"
        assert episodes[0]["t_debut"] == 120.0
        assert episodes[0]["t_fin"] is None

    def test_cloturer_episode_enregistre_t_fin(self, db):
        episode_id = db.ouvrir_episode_stress(zone="VIGILANCE", tension=1.3, t_debut=120.0)
        db.cloturer_episode_stress(episode_id, t_fin=180.0)
        episode = db.get_episodes_stress()[0]
        assert episode["t_fin"] == 180.0


class TestMiseAJourEpisode:
    def test_tension_max_augmente_si_plus_severe(self, db):
        episode_id = db.ouvrir_episode_stress(zone="VIGILANCE", tension=1.3, t_debut=0.0)
        db.mettre_a_jour_episode_stress(episode_id, zone="VIGILANCE", tension=1.8)
        episode = db.get_episodes_stress()[0]
        assert episode["tension_max"] == 1.8

    def test_tension_max_ne_redescend_jamais(self, db):
        episode_id = db.ouvrir_episode_stress(zone="CRITIQUE", tension=1.8, t_debut=0.0)
        db.mettre_a_jour_episode_stress(episode_id, zone="CRITIQUE", tension=1.4)
        episode = db.get_episodes_stress()[0]
        assert episode["tension_max"] == 1.8  # 1.4 < 1.8, ignoré

    def test_zone_max_escalade_vers_critique(self, db):
        episode_id = db.ouvrir_episode_stress(zone="VIGILANCE", tension=1.3, t_debut=0.0)
        db.mettre_a_jour_episode_stress(episode_id, zone="CRITIQUE", tension=1.6)
        episode = db.get_episodes_stress()[0]
        assert episode["zone_max"] == "CRITIQUE"


class TestGetEpisodesStress:
    def test_ordre_du_plus_recent_au_plus_ancien(self, db):
        db.ouvrir_episode_stress(zone="VIGILANCE", tension=1.3, t_debut=0.0)
        db.ouvrir_episode_stress(zone="CRITIQUE", tension=1.6, t_debut=100.0)
        episodes = db.get_episodes_stress()
        assert episodes[0]["t_debut"] == 100.0
        assert episodes[1]["t_debut"] == 0.0

    def test_limit_respecte(self, db):
        for i in range(5):
            db.ouvrir_episode_stress(zone="VIGILANCE", tension=1.3, t_debut=float(i))
        episodes = db.get_episodes_stress(limit=2)
        assert len(episodes) == 2

    def test_aucun_episode_liste_vide(self, db):
        assert db.get_episodes_stress() == []
