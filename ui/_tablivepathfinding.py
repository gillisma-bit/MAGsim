"""Mixin _TabLivePathfinding pour TabLive — extrait de ui/tab_live.py.

Ces méthodes utilisent `self.xxx` défini dans TabLive.__init__.
"""
import math
import heapq
import simpy


class _TabLivePathfinding:
    """Mixin : ne pas instancier directement."""

    def trouver_case_libre_proche(self, target_x, target_y, rayon=55, from_x=0, from_y=0):
        """Trouve la case libre adjacente (1 case max) la plus proche du technicien."""
        meilleure_pos = None
        meilleure_distance_totale = float('inf')
        
        # Chercher dans un rayon d'1 case autour de la cible (cases directement adjacentes)
        for x in range(int(target_x - rayon), int(target_x + rayon) + 1, 50):
            for y in range(int(target_y - rayon), int(target_y + rayon) + 1, 50):
                if self.est_libre(x, y):
                    # Distance depuis la position actuelle du tech
                    dist_depart = math.sqrt((x - from_x)**2 + (y - from_y)**2)
                    # Distance de la case à la cible (favoriser les cases les plus proches)
                    dist_arrivee = math.sqrt((x - target_x)**2 + (y - target_y)**2)
                    distance_totale = dist_depart + dist_arrivee * 2  # pénaliser l'éloignement de la cible
                    
                    if distance_totale < meilleure_distance_totale:
                        meilleure_distance_totale = distance_totale
                        meilleure_pos = (x, y)
        
        if meilleure_pos:
            return meilleure_pos
        else:
            # Fallback : retourner la cible même si pas libre
            return (target_x, target_y)

    def _init_sol_cache(self):
        """Initialise le cache du sol et calcule le périmètre du labo.

        Appelé à chaque démarrage/reset de simulation.  Le périmètre est
        déduit automatiquement de la boîte englobante du dict `sol` (marge
        +1 case de chaque côté pour ne pas couper les bordures).

        Override manuel possible dans config_mag.json :
          "labo_bounds": {"col_min": 0, "col_max": 25, "row_min": 0, "row_max": 23}
        """
        self._sol_cache = self.config_manager.data.get("sol", {})

        # Calculer les cases bloquées par les machines (obstacles A*)
        # Les machines spéciales (ENTREE, SORTIE, TECH_OFFICE, REPOS) ne bloquent pas
        _SPECIAUX_CACHE = {"ENTREE", "SORTIE", "TECH_OFFICE", "REPOS"}
        _CELL = 50
        self._machine_cells = set()
        try:
            for _nom, _m in self.config_manager.get_machines().items():
                if _m.get("type") in _SPECIAUX_CACHE:
                    continue
                _cx = _m["coords"]["x"]
                _cy = _m["coords"]["y"]
                _larg = _m.get("largeur_cases", 1)
                _haut = _m.get("hauteur_cases", 1)
                _col0 = round(_cx / _CELL - _larg / 2)
                _row0 = round(_cy / _CELL - _haut / 2)
                for _dc in range(_larg):
                    for _dr in range(_haut):
                        self._machine_cells.add((_col0 + _dc, _row0 + _dr))
        except Exception:
            pass

        _override = self.config_manager.data.get("labo_bounds", {})
        if _override:
            self._lab_col_min = int(_override.get("col_min", 0))
            self._lab_col_max = int(_override.get("col_max", 60))
            self._lab_row_min = int(_override.get("row_min", 0))
            self._lab_row_max = int(_override.get("row_max", 40))
        elif self._sol_cache:
            _keys = self._sol_cache.keys()
            _cols = [int(k.split("_")[0]) for k in _keys]
            _rows = [int(k.split("_")[1]) for k in _keys]
            # Marge +1 pour que les cases de bordure restent accessibles
            self._lab_col_min = max(0, min(_cols) - 1)
            self._lab_col_max = max(_cols) + 1
            self._lab_row_min = max(0, min(_rows) - 1)
            self._lab_row_max = max(_rows) + 1
        else:
            # Fallback : canvas entier (comportement historique si sol vide)
            self._lab_col_min, self._lab_col_max = 0, 60
            self._lab_row_min, self._lab_row_max = 0, 40

    def trouver_chemin_astar(self, start_x, start_y, goal_x, goal_y):
        """Calcule un chemin A* en pixels en évitant COUNTER et WALL.

        Utilise un dict came_from pour le backtracking : O(M log M) au lieu de
        O(M²) — la version précédente stockait path+[nœud] dans chaque entrée
        du heap, créant une copie de liste à chaque expansion.

        Le périmètre du labo borne l'espace de recherche : aucun nœud hors de
        la boîte englobante du dict `sol` n'est jamais expansé.  Sans cette
        borne, le canvas 3000×2000 px → 60×40 = 2400 cases seraient
        potentiellement explorées (cases hors labo absentes de sol = walkable
        par défaut).  Avec la borne, le worst-case est limité aux ~528 cases
        du labo réel, soit ~78 % de réduction de l'espace de recherche.

        La borne est calculée une seule fois depuis `sol` à l'initialisation du
        cache.  Override possible via `labo_bounds` dans config_mag.json :
          "labo_bounds": {"col_min": 0, "col_max": 23, "row_min": 0, "row_max": 21}
        """
        CELL = 50
        # Toujours appeler _init_sol_cache pour garantir que _machine_cells est à jour
        if self._sol_cache is None or not self._machine_cells and self.config_manager.get_machines():
            self._init_sol_cache()
        sol = self._sol_cache

        sc, sr = int(start_x // CELL), int(start_y // CELL)
        gc, gr = int(goal_x // CELL), int(goal_y // CELL)

        def walkable(col, row):
            # La case d'arrivée est toujours accessible (centre de machine dans un comptoir)
            if (col, row) == (gc, gr):
                return True
            # La case de départ est toujours accessible (tech déjà là)
            if (col, row) == (sc, sr):
                return True
            # Hors périmètre labo → jamais walkable
            if not (self._lab_col_min <= col <= self._lab_col_max
                    and self._lab_row_min <= row <= self._lab_row_max):
                return False
            cle = f"{col}_{row}"
            if cle in sol and sol[cle] in ("COUNTER", "WALL"):
                return False
            # Cases occupées par des machines : bloquées
            if (col, row) in self._machine_cells:
                return False
            return True

        # Si la cellule de départ est bloquée, chercher la plus proche libre
        if not walkable(sc, sr):
            for dr in range(-3, 4):
                for dc in range(-3, 4):
                    if walkable(sc + dc, sr + dr):
                        sc, sr = sc + dc, sr + dr
                        break
                else:
                    continue
                break

        # Si départ == arrivée, on est déjà là
        if sc == gc and sr == gr:
            return []

        SQRT2 = math.sqrt(2)

        def h(c, r):
            # Heuristique octile — admissible avec déplacement diagonal coût √2
            dx, dy = abs(c - gc), abs(r - gr)
            return max(dx, dy) + (SQRT2 - 1) * min(dx, dy)

        # Heap : (f, g, col, row) — chemin reconstruit via came_from
        open_set = [(h(sc, sr), 0.0, sc, sr)]
        came_from = {(sc, sr): None}   # nœud → parent
        g_score   = {(sc, sr): 0.0}
        closed    = set()

        while open_set:
            f, g, col, row = heapq.heappop(open_set)
            if (col, row) in closed:
                continue
            closed.add((col, row))

            if col == gc and row == gr:
                # Backtracking O(chemin) — aucune copie pendant la recherche
                path = []
                cur = (col, row)
                while cur is not None:
                    path.append(cur)
                    cur = came_from[cur]
                path.reverse()
                # Convertir en pixels (centre de cellule), sans le nœud de départ
                return [(c * CELL + CELL // 2, r * CELL + CELL // 2) for c, r in path[1:]]

            for dc, dr in [(0, 1), (0, -1), (1, 0), (-1, 0),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)]:
                nc, nr = col + dc, row + dr
                if (nc, nr) in closed or not walkable(nc, nr):
                    continue
                # Empêcher le coupage de coins : les deux cases adjacentes doivent être libres
                if dc != 0 and dr != 0:
                    if not walkable(col + dc, row) or not walkable(col, row + dr):
                        continue
                ng = g + (SQRT2 if dc != 0 and dr != 0 else 1)
                if ng < g_score.get((nc, nr), float('inf')):
                    g_score[(nc, nr)] = ng
                    came_from[(nc, nr)] = (col, row)
                    heapq.heappush(open_set, (ng + h(nc, nr), ng, nc, nr))

        # Aucun chemin trouvé — chercher la case walkable la plus proche du but
        # plutôt que d'aller en ligne droite (qui traverserait les obstacles)
        meilleure = None
        meilleure_dist = float('inf')
        for _dr in range(-4, 5):
            for _dc in range(-4, 5):
                _nc, _nr = gc + _dc, gr + _dr
                if walkable(_nc, _nr) or (_nc, _nr) == (gc, gr):
                    _d = abs(_dc) + abs(_dr)
                    if _d < meilleure_dist:
                        meilleure_dist = _d
                        meilleure = (_nc * CELL + CELL // 2, _nr * CELL + CELL // 2)
        if meilleure:
            return [meilleure]
        return []  # Vraiment inaccessible — le tech ne bouge pas

    def deplacer_vers(self, tech, target_x, target_y, interruptible=False):
        """Déplace le technicien `tech` vers une destination en suivant un chemin A*.
        Si interruptible=True, stoppe le mouvement dès qu'une output_queue n'est plus vide
        et positionne tech.mouvement_interrompu = True.
        """
        tech.mouvement_interrompu = False
        vitesse = tech.calculer_vitesse(self.env.now, self.heure_debut_sim)
        tolerance = 10

        chemin = self.trouver_chemin_astar(tech.x, tech.y, target_x, target_y)
        if not chemin:
            return  # Déjà à destination

        if self.headless:
            # Mode accéléré : calculer le temps de trajet en une seule fois, sans boucle pixel
            path_len = math.sqrt((chemin[0][0]-tech.x)**2 + (chemin[0][1]-tech.y)**2)
            for i in range(1, len(chemin)):
                path_len += math.sqrt((chemin[i][0]-chemin[i-1][0])**2 + (chemin[i][1]-chemin[i-1][1])**2)
            tech.distance_parcourue_px += path_len
            temps_trajet = max(path_len / vitesse * 0.05, 0.001)
            yield self.env.timeout(temps_trajet)
            tech.x, tech.y = target_x, target_y
            return

        for wp_x, wp_y in chemin:
            vitesse = tech.calculer_vitesse(self.env.now, self.heure_debut_sim)  # recalcul par waypoint
            while self.running:
                dx = wp_x - tech.x
                dy = wp_y - tech.y
                dist = math.sqrt(dx**2 + dy**2)

                if dist < tolerance:
                    tech.x = wp_x
                    tech.y = wp_y
                    # Vérifier la priorité à chaque waypoint (pas en plein mouvement)
                    if interruptible and any(self.output_queues.get(n) for n in self.output_queues):
                        tech.mouvement_interrompu = True
                        return
                    break

                pas = min(vitesse, dist)
                tech.distance_parcourue_px += pas
                tech.x += (dx / dist) * pas
                tech.y += (dy / dist) * pas

                if self.canvas.winfo_exists() and tech.canvas_id:
                    self.canvas.coords(tech.canvas_id,
                                      tech.x-10, tech.y-10,
                                      tech.x+10, tech.y+10)
                    if tech.label_bienetre_id:
                        self.canvas.coords(tech.label_bienetre_id, tech.x, tech.y - 18)
                    self._refresh_label_tubes(tech)
                    for tube in tech.carried_tubes:
                        if tube.get("id"):
                            self.canvas.coords(tube["id"],
                                              tech.x-6, tech.y-6,
                                              tech.x+6, tech.y+6)

                yield self.env.timeout(0.05)

        # Ajuster la position finale exacte (uniquement si non interrompu)
        if not tech.mouvement_interrompu:
            tech.x = target_x
            tech.y = target_y
            if self.canvas.winfo_exists() and tech.canvas_id:
                self.canvas.coords(tech.canvas_id,
                                  tech.x-10, tech.y-10,
                                  tech.x+10, tech.y+10)
                if tech.label_bienetre_id:
                    self.canvas.coords(tech.label_bienetre_id, tech.x, tech.y - 18)
                self._refresh_label_tubes(tech)
                for tube in tech.carried_tubes:
                    if tube.get("id"):
                        self.canvas.coords(tube["id"],
                                          tech.x-6, tech.y-6,
                                          tech.x+6, tech.y+6)
