"""Coordinateur de stress — surveillance de l'enveloppe de stabilité du labo.

Architecture
------------
Le CoordonnateurStress tourne comme un process SimPy autonome (toutes les
``intervalle_min`` minutes simulées). Il compare la charge actuelle du labo
à une *baseline horaire* dérivée du profil Gamma d'arrivées, puis classe
l'état du système dans l'une des trois zones :

    STABLE     (tension < SEUIL_VIGILANCE)   → mathématique pure, IA dort
    VIGILANCE  (SEUIL_VIGILANCE ≤ t < SEUIL_CRITIQUE)  → surveiller
    CRITIQUE   (tension ≥ SEUIL_CRITIQUE)    → ajuster les poids de scoring

Le module est sans dépendance SimPy / Tkinter : il peut être testé en isolation.
La boucle SimPy elle-même est définie dans ``ui/tab_live.py``.

Termes
------
tension : float
    Ratio charge_actuelle / charge_baseline_horaire.
    1.0 = charge normale pour cette heure.  > 1.5 = surcharge critique.
zone : str
    "STABLE" | "VIGILANCE" | "CRITIQUE"
poids : dict
    Multiplicateurs injectés dans _score_priorite() pour hausser la pression
    sur les tubes urgents / vieux quand le labo est sous stress.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import json
import threading


# ─────────────────────────────────────────────────────────────────────────────
# Seuils flottants (ajustables)
# ─────────────────────────────────────────────────────────────────────────────
SEUIL_VIGILANCE = 1.20   # 20 % au-dessus de la normale → vigilance
SEUIL_CRITIQUE  = 1.50   # 50 % au-dessus              → action corrective

# Poids de scoring par zone (multiplicateurs de _score_priorite)
POIDS_PAR_ZONE = {
    # zone       : (mult_urgence, mult_validite, mult_age)
    "STABLE"    : (1.0,  1.0,  1.0),
    "VIGILANCE" : (1.5,  1.5,  1.0),   # sensibilité accrue aux tubes vieillissants
    "CRITIQUE"  : (3.0,  2.5,  1.0),   # urgents passent en tête absolue
}

# Seuils d'escalade adaptatifs (ratio de validité consommée) par zone
SEUILS_ESCALADE_PAR_ZONE = {
    "STABLE"    : (0.65, 0.85),   # défaut : N1 à 65 %, N2 à 85 %
    "VIGILANCE" : (0.55, 0.75),   # légèrement abaissés
    "CRITIQUE"  : (0.45, 0.65),   # on escalade beaucoup plus tôt
}


# ─────────────────────────────────────────────────────────────────────────────
# Structures de données
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SnapshotStress:
    """Instantané d'une évaluation de tension."""
    t: float                  # temps SimPy (minutes)
    heure_reelle: float       # heure du jour (0.0 – 23.99)
    tension: float
    zone: str
    entry_queue_len: int
    total_en_attente: int     # entry + toutes machine_queues
    nb_urgents: int
    facteur_horaire: float    # facteur du profil à cette heure
    baseline: float           # tubes attendus pendant l'intervalle à cette heure
    poids: tuple              # (mult_urgence, mult_validite, mult_age)


# ─────────────────────────────────────────────────────────────────────────────
# Logique pure
# ─────────────────────────────────────────────────────────────────────────────
class CoordonnateurStress:
    """Calcule l'état de tension du labo à chaque tick de surveillance.

    Usage dans SimPy (tab_live.py) :
    ──────────────────────────────
        coord = CoordonnateurStress(intervalle_min=15)
        env.process(coord.process(env, tab_live_instance))

    Usage standalone (tests) :
    ──────────────────────────
        coord = CoordonnateurStress()
        snap  = coord.evaluer(t=120, heure_debut_sim=7.0,
                              entry_queue_len=8, machine_queues={...},
                              profil_horaire=[[7,1.0],[11,1.8],...],
                              frequence_base=5.0)
    """

    def __init__(self, intervalle_min: float = 15.0, ia_active: bool = False,
                 cooldown_ia_min: float = 60.0):
        self.intervalle_min    = intervalle_min
        self.ia_active         = ia_active          # True = appels Qwen activés
        self.cooldown_ia_min   = cooldown_ia_min    # min sim entre 2 appels IA
        self.zone_courante     = "STABLE"
        self.tension_courante  = 0.0
        self.poids_courants    = POIDS_PAR_ZONE["STABLE"]
        self.seuils_escalade   = SEUILS_ESCALADE_PAR_ZONE["STABLE"]
        self.batch_urgents_force: bool = False   # True = IA demande batch=1 pour urgents
        self._ia_anticiper_actif: bool = False       # True = ANTICIPER en cours en VIGILANCE
        self.historique: List[SnapshotStress] = []
        self._t_dernier_appel_ia: float = -999999.0  # t SimPy du dernier appel IA
        self._derniere_zone: str = "STABLE"          # zone au tick précédent
        self._profil_horaire: list = []              # profil horaire courant (pour anticipation)
        # Résultat du dernier appel IA (mis à jour dans un thread séparé en mode live)
        self._ia_reponse_pending: Optional[dict] = None
        self._ia_lock = threading.Lock()

    # ── API principale ────────────────────────────────────────────────────────
    def evaluer(
        self,
        t: float,
        heure_debut_sim: float,
        entry_queue_len: int,
        machine_queues: dict,
        profil_horaire: list,
        frequence_base: float,
    ) -> SnapshotStress:
        """Calcule la tension courante et met à jour l'état interne.

        Paramètres
        ----------
        t               : temps SimPy courant (minutes depuis t=0)
        heure_debut_sim : heure réelle à t=0 (ex : 7.0 pour 7h00)
        entry_queue_len : len(entry_queue)
        machine_queues  : {nom: [tubes]} — files machines actives
        profil_horaire  : [[heure, facteur], ...] depuis la config ENTREE
        frequence_base  : inter-arrivée moyenne en minutes (config ENTREE)
        """
        heure_reelle = (heure_debut_sim + t / 60.0) % 24.0
        facteur      = _facteur_horaire(heure_reelle, profil_horaire)
        # Stocker le profil pour que consulter_ia puisse calculer l'anticipation
        self._profil_horaire = profil_horaire

        # Charge totale actuelle
        mq_total     = sum(len(q) for q in machine_queues.values())
        # entry_queue_len peut être une liste (depuis tab_live) ou un entier (tests)
        entry_count  = len(entry_queue_len) if hasattr(entry_queue_len, '__len__') else int(entry_queue_len)
        total        = entry_count + mq_total
        nb_urgents   = sum(1 for tube in _iter_tous_tubes(entry_queue_len, machine_queues)
                          if tube.get("urgent"))

        # Baseline : combien de tubes on s'attend à traiter pendant l'intervalle à cette heure
        # freq_base / facteur = inter-arrivée modulée ; intervalle / inter-arrivée = arrivées attendues
        inter_arrivee_modulee = max(0.5, frequence_base / max(0.01, facteur))
        baseline = max(1.0, self.intervalle_min / inter_arrivee_modulee)

        tension = total / baseline
        zone    = _evaluer_zone(tension)

        # Mise à jour de l'état interne
        self._derniere_zone   = self.zone_courante
        self.tension_courante = tension
        self.zone_courante    = zone
        # Poids, seuils d'escalade et batch_force : si IA active en zone CRITIQUE,
        # préserver les valeurs ajustées par Qwen.
        # En dehors de CRITIQUE (ou si IA inactive), revenir aux valeurs statiques.
        if not self.ia_active or zone == "STABLE":
            # IA inactive ou retour en STABLE : réinitialiser toutes les overrides
            self.poids_courants      = POIDS_PAR_ZONE[zone]
            self.seuils_escalade     = SEUILS_ESCALADE_PAR_ZONE[zone]
            self.batch_urgents_force = False
            self._ia_anticiper_actif = False
        elif zone == "VIGILANCE" and not self._ia_anticiper_actif:
            # VIGILANCE sans anticipation IA active → valeurs statiques
            self.poids_courants      = POIDS_PAR_ZONE[zone]
            self.seuils_escalade     = SEUILS_ESCALADE_PAR_ZONE[zone]
            self.batch_urgents_force = False
        # else (CRITIQUE, ou VIGILANCE avec ANTICIPER) : préserver les overrides IA

        snap = SnapshotStress(
            t=t,
            heure_reelle=heure_reelle,
            tension=round(tension, 3),
            zone=zone,
            entry_queue_len=entry_count,
            total_en_attente=total,
            nb_urgents=nb_urgents,
            facteur_horaire=round(facteur, 3),
            baseline=round(baseline, 2),
            poids=self.poids_courants,
        )
        self.historique.append(snap)
        # Garder les 2 000 derniers snaps pour ne pas saturer la mémoire
        if len(self.historique) > 2000:
            self.historique = self.historique[-2000:]

        return snap

    def reset(self):
        """Remet à zéro pour un nouveau lancement de simulation."""
        self.zone_courante         = "STABLE"
        self.tension_courante      = 0.0
        self.poids_courants        = POIDS_PAR_ZONE["STABLE"]
        self.seuils_escalade       = SEUILS_ESCALADE_PAR_ZONE["STABLE"]
        self.batch_urgents_force   = False
        self._ia_anticiper_actif   = False
        self.historique            = []
        self._t_dernier_appel_ia   = -999999.0
        self._derniere_zone        = "STABLE"
        self._profil_horaire       = []
        with self._ia_lock:
            self._ia_reponse_pending = None

    # ── Appel IA (Qwen local via Ollama) ─────────────────────────────────────
    def consulter_ia(self, snap: SnapshotStress, nb_techs_actifs: int,
                     nb_machines_en_panne: int, headless: bool = False,
                     prospectif: dict | None = None) -> Optional[dict]:
        """Interroge Qwen 2.5 32B pour des ajustements de poids.

        En mode headless (benchmark) : appel synchrone, bloque jusqu'à réponse.
        En mode live : appel dans un thread, résultat appliqué au prochain tick.

        Règles de déclenchement (limitent les appels Qwen) :
        - cooldown : au moins ``cooldown_ia_min`` minutes sim depuis le dernier appel
        - OU : première entrée en zone CRITIQUE (transition)

        Retourne un dict {"mult_urgence": float, "mult_validite": float,
                          "action": str, "justification": str} ou None si échec / cooldown.
        """
        # Garde absolue : jamais d'appel Ollama en mode headless (synchrone, bloquant).
        # Cette vérification est dupliquée dans coordinateur_process pour la lisibilité,
        # mais cette garde-ci protège aussi les appels directs depuis les tests/benchmarks.
        if headless:
            return None

        if not self.ia_active:
            return None

        # Vérifier le cooldown sauf si c'est une transition vers CRITIQUE
        entree_critique = (snap.zone == "CRITIQUE" and self._derniere_zone != "CRITIQUE")
        delai_ecoule    = (snap.t - self._t_dernier_appel_ia) >= self.cooldown_ia_min
        if not entree_critique and not delai_ecoule:
            return None   # trop tôt

        # En VIGILANCE : n'appeler l'IA que si un pic est détecté dans les 2h à venir
        if snap.zone == "VIGILANCE":
            facteur_max_2h = self._facteur_max_prochaines_heures(snap.heure_reelle, nb_heures=2)
            if facteur_max_2h < snap.facteur_horaire * 1.3:
                return None  # pas de pic imminent, pas d'anticipation utile

        # Log explicite avant tout appel réseau (visible dans la console)
        mode = "SYNC/headless" if headless else "ASYNC/thread"
        print(f"[IA-Qwen] Appel {mode} — zone={snap.zone}, t={snap.t:.0f} min sim")

        try:
            import ollama
        except ImportError:
            return None

        # Profil des prochaines heures pour l'anticipation
        prochaines = self._prochaines_heures(snap.heure_reelle, nb_heures=3)
        facteur_max_2h = self._facteur_max_prochaines_heures(snap.heure_reelle, nb_heures=2)
        pic_imminent = facteur_max_2h > snap.facteur_horaire * 1.3

        contexte = {
            "heure": round(snap.heure_reelle, 1),
            "zone": snap.zone,
            "tension": snap.tension,
            "tubes_en_attente": snap.total_en_attente,
            "tubes_urgents": snap.nb_urgents,
            "facteur_horaire_maintenant": snap.facteur_horaire,
            "profil_prochaines_heures": prochaines,
            "pic_imminent": pic_imminent,
            "ratio_pic_vs_maintenant": round(facteur_max_2h / max(0.01, snap.facteur_horaire), 2),
            "baseline_attendue": snap.baseline,
            "techs_actifs": nb_techs_actifs,
            "machines_en_panne": nb_machines_en_panne,
            "poids_actuels": {
                "mult_urgence": snap.poids[0],
                "mult_validite": snap.poids[1],
            },
        }

        # Enrichir avec les données prospectives réelles (tubes déjà en transit/queue)
        if prospectif:
            contexte["prospectif"] = {
                "tubes_attendus_20min": prospectif.get("nb_total", 0),
                "urgents_attendus_20min": prospectif.get("nb_urgents", 0),
                "rush_detecte": prospectif.get("rush_detecte", False),
                "urgence_critique": prospectif.get("urgence_critique", False),
                "par_service": prospectif.get("par_service", {}),
                "charge_workflows": prospectif.get("charge_workflows", {}),
            }

        prompt_systeme = (
            "Tu es le coordinateur IA d'un laboratoire de cardiologie hospitalier. "
            "Tu reçois un instantané de l'état du flux de tubes d'analyse, "
            "incluant le profil de charge des prochaines heures "
            "ET les tubes déjà en transit/queue (données prospectives certaines). "
            "Ton rôle : ajuster les multiplicateurs de priorité pour optimiser le débit "
            "et éviter les péremptions, y compris par anticipation des pics. "
            "Réponds UNIQUEMENT en JSON valide, rien d'autre. "
            "Format exact : "
            '{"mult_urgence": <float 1.0-5.0>, "mult_validite": <float 1.0-5.0>, '
            '"action": "<STABLE|ACCELERER|REDISTRIBUER|ANTICIPER>", '
            '"justification": "<max 20 mots>"}'
            " — ANTICIPER = tubes en transit détectés, agir AVANT leur arrivée."
        )

        prompt_user = (
            f"État du labo : {json.dumps(contexte, ensure_ascii=False)}. "
            "Quels multiplicateurs recommandes-tu ?"
        )

        # Enregistrer le timestamp avant l'appel (même si l'appel échoue,
        # on ne re-sollicite pas Qwen immédiatement)
        self._t_dernier_appel_ia = snap.t

        if headless:
            return self._appel_ollama_sync(prompt_systeme, prompt_user)
        else:
            # Mode live : appel non-bloquant dans un thread
            t = threading.Thread(
                target=self._appel_ollama_async,
                args=(prompt_systeme, prompt_user),
                daemon=True,
            )
            t.start()
            return None  # résultat disponible au prochain tick via _ia_reponse_pending

    def recuperer_reponse_ia(self) -> Optional[dict]:
        """Récupère et efface la dernière réponse IA (mode live, thread-safe)."""
        with self._ia_lock:
            r = self._ia_reponse_pending
            self._ia_reponse_pending = None
        return r

    def _appel_ollama_sync(self, system: str, user: str) -> Optional[dict]:
        import ollama
        try:
            resp = ollama.chat(
                model="qwen2.5:32b",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                options={"temperature": 0.1},
            )
            texte = resp["message"]["content"].strip()
            # Extraire le JSON si le modèle a ajouté du texte autour
            debut = texte.find("{")
            fin   = texte.rfind("}") + 1
            if debut >= 0 and fin > debut:
                return json.loads(texte[debut:fin])
        except Exception as e:
            print(f"[IA] Erreur Ollama : {e}")
        return None

    def _appel_ollama_async(self, system: str, user: str):
        result = self._appel_ollama_sync(system, user)
        if result is not None:
            with self._ia_lock:
                self._ia_reponse_pending = result

    def appliquer_reponse_ia(self, reponse: dict):
        """Applique les poids renvoyés par l'IA en les contraignant dans des bornes sûres."""
        if not reponse:
            return
        mu = float(reponse.get("mult_urgence",  self.poids_courants[0]))
        mv = float(reponse.get("mult_validite", self.poids_courants[1]))
        ma = self.poids_courants[2]
        # Activer le mode batch=1 urgents si l'IA demande d'accélérer
        action = reponse.get("action", "")
        self.batch_urgents_force = (action == "ACCELERER")
        # Bornes : jamais en dessous des valeurs de la zone courante, jamais au-dessus de 5
        # → empêche une réponse STABLE (mu=1.0) d'écraser les poids CRITIQUE (3.0, 2.5)
        zone_min = POIDS_PAR_ZONE.get(self.zone_courante, POIDS_PAR_ZONE["STABLE"])
        mu = max(zone_min[0], min(5.0, mu))
        mv = max(zone_min[1], min(5.0, mv))
        self.poids_courants  = (mu, mv, ma)
        # Seuils d'escalade : ACCELERER → seuils modérément agressifs (escalade un peu plus tôt)
        # REDISTRIBUER → identique à CRITIQUE statique
        # L'effet est discret (+1_000_000 au score) mais sans promouvoir toute la file
        action = reponse.get("action", "")
        if action == "ACCELERER":
            self.seuils_escalade = (0.50, 0.70)   # un peu plus tôt que STABLE (0.65/0.85)
        elif action == "REDISTRIBUER":
            self.seuils_escalade = SEUILS_ESCALADE_PAR_ZONE["CRITIQUE"]  # (0.45, 0.65)
        elif action == "ANTICIPER":
            # Anticipation proactive : on hausse les poids de scoring SANS abaisser
            # les seuils d'escalade → évite de créer massivement des "faux urgents"
            # qui bloqueraient les vrais urgents arrivant ensuite.
            # Effet : les tubes urgents existants montent plus vite dans la file
            # avant le pic, sans surcharger le statut urgent.
            self._ia_anticiper_actif = True
            # Garder les seuils de la zone courante (ne pas les abaisser)
            # S'assurer que mult_validite est au moins au niveau VIGILANCE
            mv = max(mv, POIDS_PAR_ZONE["VIGILANCE"][1])
            self.poids_courants = (mu, mv, ma)

    # ── Accesseurs pratiques ──────────────────────────────────────────────────
    @property
    def mult_urgence(self) -> float:
        return self.poids_courants[0]

    @property
    def mult_validite(self) -> float:
        return self.poids_courants[1]

    @property
    def seuil_escalade_n1(self) -> float:
        return self.seuils_escalade[0]

    @property
    def seuil_escalade_n2(self) -> float:
        return self.seuils_escalade[1]

    def resume_pour_log(self) -> str:
        """Ligne de log compacte pour stats_history."""
        return (
            f"[{self.zone_courante}] tension={self.tension_courante:.2f} "
            f"poids=({self.mult_urgence:.1f},{self.mult_validite:.1f}) "
            f"escalade=({self.seuil_escalade_n1:.0%},{self.seuil_escalade_n2:.0%})"
        )

    # ── Méthodes privées d'anticipation ─────────────────────────────────────────
    def _prochaines_heures(self, heure_reelle: float, nb_heures: int = 3) -> dict:
        """Retourne les facteurs horaires des `nb_heures` prochaines heures."""
        return {
            f"dans_{h}h": round(_facteur_horaire((heure_reelle + h) % 24.0,
                                                  self._profil_horaire), 2)
            for h in range(1, nb_heures + 1)
        }

    def _facteur_max_prochaines_heures(self, heure_reelle: float, nb_heures: int = 2) -> float:
        """Facteur horaire maximum sur les `nb_heures` prochaines heures (pas de 15 min)."""
        pas = 0.25  # échantillonnage toutes les 15 min
        nb_pas = int(nb_heures / pas)
        return max(
            _facteur_horaire((heure_reelle + i * pas) % 24.0, self._profil_horaire)
            for i in range(1, nb_pas + 1)
        ) if self._profil_horaire else 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions utilitaires internes
# ─────────────────────────────────────────────────────────────────────────────
def _facteur_horaire(heure: float, profil: list) -> float:
    """Interpolation linéaire du facteur de flux pour une heure donnée (0–24)."""
    if not profil:
        return 1.0
    profil_sorted = sorted(profil, key=lambda p: p[0])
    for i in range(len(profil_sorted) - 1):
        h0, f0 = profil_sorted[i]
        h1, f1 = profil_sorted[i + 1]
        if h0 <= heure < h1:
            alpha = (heure - h0) / (h1 - h0)
            return max(0.01, f0 + alpha * (f1 - f0))
    return max(0.01, profil_sorted[-1][1])


def _evaluer_zone(tension: float) -> str:
    if tension >= SEUIL_CRITIQUE:
        return "CRITIQUE"
    if tension >= SEUIL_VIGILANCE:
        return "VIGILANCE"
    return "STABLE"



def _iter_tous_tubes(entry_queue_len, machine_queues):
    """Itérateur sur tous les tubes en attente (entry + machines).

    Note : entry_queue_len est un entier, pas la vraie liste — on ne peut pas
    itérer dessus. Cette fonction est appelée avec la vraie entry_queue depuis
    tab_live.py. Le paramètre est gardé générique pour les tests unitaires.
    """
    # Si entry_queue_len est une liste (appelé depuis tab_live), on l'itère
    if hasattr(entry_queue_len, '__iter__'):
        yield from entry_queue_len
    for q in machine_queues.values():
        yield from q
