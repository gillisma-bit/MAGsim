"""Algorithmes de priorité et d'insertion pour les files de tubes.

Extrait de ui/tab_live.py pour garder les fichiers à taille raisonnable.
Ces fonctions sont purement calculatoires (pas d'état SimPy ni Tkinter).
"""
import bisect


def _score_priorite(tube, now, mult_urgence=1.0, mult_validite=1.0, mult_age=1.0):
    """Score de priorité d'un tube : plus élevé = traiter EN PREMIER.

    Trois composantes additives avec multiplicateurs de stress (injectés par
    le CoordonnateurStress selon la zone STABLE/VIGILANCE/CRITIQUE) :
    1. Urgence (flag booléen)         → +1 000 000 fixe (flag absolu, mu n'amplifie pas)
    2. % de validité consommée (0–1)  → ×    1 000 × mult_validite  (levier IA principal)
    3. Ancienneté brute (minutes)     → ×        1 × mult_age  (tiebreaker)

    mult_urgence sert uniquement à amplifier le score INTRA-URGENTS : un tube
    urgent reste toujours devant un tube non-urgent, mais parmi les urgents
    l'ordre dépend du reste du score × mult_urgence.

    Calcul EDD (Earliest Deadline First) :
      - Si deadline absolue présente (t_generation + duree_validite) :
        pct = 1 - slack/duree_totale  →  reflète l'urgence depuis la CRÉATION
        (plus précis que age/validite qui comptait depuis l'arrivée labo)
      - Sinon fallback : age/validite depuis arrivée labo (tubes sans deadline).
    """
    validite = tube.get("duree_validite", 0)
    deadline = tube.get("deadline", 0)
    if deadline > 0 and validite > 0:
        slack = deadline - now                  # temps restant avant péremption
        pct   = max(0.0, 1.0 - slack / validite)  # 0 à la génération → >1 si périmé
    else:
        age  = now - tube.get("arrivee", now)
        pct  = (age / validite) if validite > 0 else 0.0
    age_abs = now - tube.get("t_generation", tube.get("arrivee", now))
    # Urgents : flag absolu 1_000_000 + score intra-urgents amplifié par mult_urgence
    # Non-urgents : score validité + ancienneté seulement
    if tube.get("urgent"):
        return (1_000_000.0
                + (pct * 1_000.0 * mult_validite + age_abs * mult_age) * mult_urgence)
    else:
        return pct * 1_000.0 * mult_validite + age_abs * mult_age


def _inserer_par_priorite(queue, tube, now, mult_urgence=1.0, mult_validite=1.0, mult_age=1.0):
    """Insère `tube` dans `queue` en ordre décroissant de _score_priorite."""
    score      = _score_priorite(tube, now, mult_urgence, mult_validite, mult_age)
    neg_scores = [-_score_priorite(t, now, mult_urgence, mult_validite, mult_age) for t in queue]
    pos = bisect.bisect_right(neg_scores, -score)
    queue.insert(pos, tube)


def _trier_queue_par_priorite(queue, now, mult_urgence=1.0, mult_validite=1.0, mult_age=1.0):
    """Trie une file en place : score décroissant (plus urgent/vieux en tête)."""
    queue.sort(key=lambda t: -_score_priorite(t, now, mult_urgence, mult_validite, mult_age))


def _inserer_par_anciennete(queue, tube, now=None, mult_urgence=1.0, mult_validite=1.0, mult_age=1.0):
    """Insère `tube` dans `queue` par priorité composite (urgence + validité + ancienneté)."""
    if now is not None:
        _inserer_par_priorite(queue, tube, now, mult_urgence, mult_validite, mult_age)
        return
    # Fallback sans `now` : urgents devant, puis FIFO par arrivée
    if tube.get("urgent"):
        queue.insert(0, tube)
        return
    nb_urgents = sum(1 for t in queue if t.get("urgent"))
    arrivees_normaux = [t.get("arrivee", 0) for t in queue[nb_urgents:]]
    pos = bisect.bisect_left(arrivees_normaux, tube.get("arrivee", 0))
    queue.insert(nb_urgents + pos, tube)
