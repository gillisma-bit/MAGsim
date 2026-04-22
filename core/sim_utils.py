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
                return float("inf")   # machine pleine
            score = cap - current     # fill-first : on remplit la machine la plus proche du seuil
            # Malus fort si la paillasse a déjà un analyste : préférer une paillasse libre
            # pour éviter qu'un tech soit bloqué à poste pendant que l'autre reste inoccupée.
            if m.get("tech_requis_poste", False) and nom in _po:
                score += 1000
            return score

        scores = [((nom, m), _score((nom, m))) for nom, m in candidats]
        scores_valides = [item for item in scores if item[1] != float("inf")]
        if not scores_valides:
            return None, None, None   # toutes pleines → reporter le tube

        best_nom, best_m = min(scores_valides, key=lambda x: x[1])[0]
        return best_m, best_nom, etape
    return None, None, None
