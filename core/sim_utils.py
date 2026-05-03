"""Fonctions de logique de simulation — sans dépendance Tkinter.

Extraites de TabLive pour permettre les tests unitaires.
"""


def trouver_prochaine_machine(tube, machines, machine_queues, virtual_queues=None,
                              paillasse_occupee=None):
    """Retourne (machine_dict, nom_machine, etape) pour la prochaine étape du workflow.

    Règle fondamentale : le workflow du tube N'EST JAMAIS modifié sauf si aucune
    machine ne connaît l'étape (erreur de config → l'étape est sautée avec warning).
    Quand toutes les machines capables sont pleines → (None, None, None) : le tube
    est mis en attente, il ne passe PAS à l'étape suivante.

    Paramètres
    ----------
    tube : dict
        Doit contenir la clé "workflow" (liste d'étapes restantes).
    machines : dict
        {nom_machine: machine_dict, ...}  (tel que retourné par config_manager)
    machine_queues : dict
        {nom_machine: [tubes en attente], ...}  — état courant des files réelles.
    virtual_queues : dict, optional
        {nom_machine: nb_tubes_déjà_attribués_dans_ce_batch}
        Permet au caller de tenir compte des tubes déjà assignés avant déplacement.
    paillasse_occupee : set, optional
        Noms des paillasses (tech_requis_poste=True) ayant déjà un analyste.
        Ces machines reçoivent un malus de scoring pour favoriser les paillasses libres,
        évitant qu'un seul analyste soit bloqué pendant que l'autre paillasse reste vide.
    """
    if virtual_queues is None:
        virtual_queues = {}
    if paillasse_occupee is None:
        paillasse_occupee = set()

    while tube["workflow"]:
        etape = tube["workflow"][0]  # peek uniquement — PAS de pop ici
        candidats = [(nom, m) for nom, m in machines.items()
                     if etape in m.get("protocoles", {})]
        if not candidats:
            tube["workflow"].pop(0)
            print(f"[ERREUR] Pas de machine pour l'étape '{etape}', étape ignorée")
            continue

        def _score(p, _mq=machine_queues, _vq=virtual_queues, _po=paillasse_occupee):
            nom, m = p
            cap = m.get("capacite", 4)
            fm  = m.get("file_max", cap)
            current = len(_mq.get(nom, [])) + _vq.get(nom, 0)
            if current >= fm:
                return (2, 9999, 0)   # machine pleine → toujours écartée (sentinel > tout score valide)
            # Stratégie batch-first : slots restants avant déclenchement du cycle
            #   remaining = cap - current  →  0 quand le seuil est atteint, cap quand vide
            #   On trie par (remaining ascendant, cap ascendant) via min() :
            #     - Préfère la machine la plus proche de déclencher son cycle
            #     - À égalité, préfère la machine de plus petite capacité (déclenche avec
            #       moins de tubes → cycle rapide plutôt que grosse centri à moitié vide)
            #   Exemple : ct1 vide cap=4, ct2 vide cap=10, 4 tubes disponibles
            #     tube 1 : ct1 (0, 4, 4)  ct2 (0, 10, 10)  → ct1 gagne (4 < 10)  ✓
            #     tube 2 : ct1 (0, 3, 4)  ct2 (0, 10, 10)  → ct1 gagne             ✓
            #     tube 3 : ct1 (0, 2, 4)  → ct1 gagne                               ✓
            #     tube 4 : ct1 (0, 1, 4)  → ct1 gagne → cycle déclenché !           ✓
            #   Exemple : ct1 à 3/4 (remaining=1), ct2 vide (remaining=10)
            #     → ct1 gagne → on complète d'abord le cycle en cours               ✓
            remaining = max(0, cap - current)
            # Malus si la machine est déjà au seuil de déclenchement (current >= cap) :
            # un tube supplémentaire n'apporterait rien (le cycle est déjà déclenché ou
            # le batch est complet) → reléguer après les machines encore «ouvertes».
            at_cap_malus = 1 if current >= cap else 0
            paillasse_malus = 1 if (m.get("tech_requis_poste", False) and nom in _po) else 0
            return (paillasse_malus, at_cap_malus, remaining, cap)

        scores = [((nom, m), _score((nom, m))) for nom, m in candidats]
        scores_valides = [item for item in scores if item[1][0] < 2]   # exclut les machines pleines
        if not scores_valides:
            return None, None, None   # toutes pleines → reporter le tube

        best_nom, best_m = min(scores_valides, key=lambda x: x[1])[0]
        return best_m, best_nom, etape
    return None, None, None
