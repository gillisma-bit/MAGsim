"""Mixin _TabLiveMachine pour TabLive — extrait de ui/tab_live.py.

Ces méthodes utilisent `self.xxx` défini dans TabLive.__init__.
"""
import simpy
import random
import ui.theme as theme
from core.sim.priorite import (
    _score_priorite, _inserer_par_priorite,
    _trier_queue_par_priorite, _inserer_par_anciennete,
)


class _TabLiveMachine:
    """Mixin : ne pas instancier directement."""

    def _blink_machine(self, nom_machine):
        """Fait clignoter le point rouge sur la machine tant qu'elle est dans blinking_machines."""
        if self.headless:
            return  # Pas d'animation en mode headless
        ind_id = self.machine_indicators.get(nom_machine)
        if not ind_id:
            return
        visible = True
        while nom_machine in self.blinking_machines and self.running:
            if self.canvas.winfo_exists():
                if visible:
                    self.canvas.itemconfig(ind_id, fill="#e74c3c", outline="#c0392b")
                else:
                    self.canvas.itemconfig(ind_id, fill="", outline="")
            visible = not visible
            yield self.env.timeout(0.5)
        # Éteindre le point à la fin
        if self.canvas.winfo_exists() and ind_id:
            self.canvas.itemconfig(ind_id, fill="", outline="")

    def machine_breakdown_process(self, nom_machine, machine):
        """Processus indépendant modélisant les pannes par loi exponentielle (TMEP/TMR).

        TMEP (Temps Moyen Entre Pannes) et TMR (Temps Moyen de Réparation) sont en HEURES.
        Taux de disponibilité théorique : A = TMEP / (TMEP + TMR).
        Les valeurs sont converties en minutes (×60) pour SimPy (1 unité = 1 min).
        """
        tmep = machine.get("tmep", 0)
        tmr  = machine.get("tmr",  0)
        if not tmep or not tmr or tmep <= 0 or tmr <= 0:
            return

        # Conversion heures → minutes SimPy
        tmep_min = tmep * 60
        tmr_min  = tmr  * 60

        while self.running:
            # Attendre le prochain incident (distribution exponentielle)
            delai_avant_panne = random.expovariate(1.0 / tmep_min)
            yield self.env.timeout(delai_avant_panne)
            if not self.running:
                break

            # --- Déclenchement de la panne ---
            self.panne_machines.add(nom_machine)
            self.stats_history["pannes"].setdefault(nom_machine, []).append(self.env.now)

            repair_event = self.env.event()
            self.machine_repair_events[nom_machine] = repair_event

            if not self.headless and self.canvas.winfo_exists():
                if nom_machine in self.machine_rect_ids:
                    self.canvas.itemconfig(self.machine_rect_ids[nom_machine], fill="#e67e22")
                if nom_machine in self.machine_labels:
                    self.canvas.itemconfig(self.machine_labels[nom_machine], text="⚠ EN PANNE")

            # Attendre la durée de réparation (distribution exponentielle)
            duree_reparation = random.expovariate(1.0 / tmr_min)
            yield self.env.timeout(duree_reparation)
            if not self.running:
                break

            # --- Réparation terminée ---
            self.panne_machines.discard(nom_machine)
            if not repair_event.triggered:
                repair_event.succeed()
            self.machine_repair_events.pop(nom_machine, None)

            if not self.headless and self.canvas.winfo_exists():
                if nom_machine in self.machine_rect_ids:
                    machines_cfg = self.config_manager.get_machines()
                    _typ_rep = machines_cfg.get(nom_machine, {}).get("type", "")
                    _couleurs_rep = {
                        "Centrifugeuse": "#3498db", "Automate": "#e67e22",
                        "Paillasse": "#95a5a6", "Incubateur": "#e91e63",
                        "Réfrigérateur": "#00bcd4", "Laveur de plaque": "#009688",
                        "Lecteur de plaque": "#4caf50", "Bain-marie": "#ff5722",
                        "Agitateur": "#9c27b0", "Microscope": "#607d8b",
                        "Hotte": "#795548", "Congélateur": "#5c6bc0",
                    }
                    _color_rep = _couleurs_rep.get(_typ_rep, "#3498db")
                    self.canvas.itemconfig(self.machine_rect_ids[nom_machine], fill=_color_rep)
                if nom_machine in self.machine_labels:
                    self.canvas.itemconfig(self.machine_labels[nom_machine], text=nom_machine)

    def _trouver_prochaine_machine(self, tube, machines, virtual_queues=None):
        """Délègue à core.sim_utils.trouver_prochaine_machine (logique pure testable)."""
        from core.sim_utils import trouver_prochaine_machine
        return trouver_prochaine_machine(
            tube, machines, self.machine_queues, virtual_queues,
            paillasse_occupee=self.paillasse_analyste,
            reserved_slots=self.machine_slots_reserved,
        )

    def traiter_batch_machine(self, nom_machine, machine, force_batch_size=None):
        # Anti-doublon : _machines_batch_actif gere sans recursion yield-from.
        # Auto-restart via env.process() => nouveau frame plat a chaque batch.
        self._machines_batch_actif.add(nom_machine)
        _respawn = False
        try:
            capacite = machine.get("capacite", 4)
            if force_batch_size is not None:
                capacite = min(capacite, force_batch_size)
            mu, mv, ma = self.coordinateur.poids_courants
            _trier_queue_par_priorite(self.machine_queues[nom_machine], self.env.now, mu, mv, ma)
            batch = self.machine_queues[nom_machine][:capacite]
            del self.machine_queues[nom_machine][:capacite]

            self.blinking_machines.add(nom_machine)
            self.env.process(self._blink_machine(nom_machine))

            if not self.headless and self.canvas.winfo_exists():
                for tube in batch:
                    if tube.get("id"):
                        self.canvas.itemconfig(tube["id"], fill="#2980b9", outline="#1a5276", width=2)

            if not self.headless and nom_machine in self.machine_labels:
                self.canvas.itemconfig(self.machine_labels[nom_machine], text=f"{nom_machine}: Traitement...")

            protocoles = machine.get("protocoles", {})
            etape = next(iter(protocoles), None)
            temps = protocoles[etape].get("temps", 60) if etape else 60

            if self._debug_mode:
                self._debug_entries.append({
                    "ev": "batch_start", "t": self.env.now,
                    "machine": nom_machine, "batch_sz": len(batch),
                    "temps": temps, "q_restante": len(self.machine_queues.get(nom_machine, [])),
                    "nb_batch_actifs": len(self._machines_batch_actif),
                })
                if temps == 0:
                    self._debug_entries.append({
                        "ev": "WARN_TEMPS_ZERO", "t": self.env.now, "machine": nom_machine
                    })

            # ── Rejet prédictif en machine : tubes qui ne peuvent plus finir leur workflow ──
            # Vérifié AVANT le yield pour ne pas occuper la machine inutilement.
            # À ce stade, workflow du tube = étapes APRÈS la machine courante
            # (l'étape courante a déjà été consommée au dépôt par le technicien).
            _mach_cfg_pred = self.config_manager.get_machines()
            _batch_viables = []
            for _tube_pred in batch:
                _dv_pred = _tube_pred.get("duree_validite", 0)
                if _dv_pred > 0:
                    _dl_pred = _tube_pred.get("deadline", 0)
                    _val_rest = (_dl_pred - self.env.now) if _dl_pred > 0 else (
                        _dv_pred - (self.env.now - _tube_pred.get("arrivee", self.env.now)))
                    # temps machine courante (SimPy) + temps étapes restantes
                    _duree_pred = (temps / 10) + self._estimer_duree_workflow(
                        _tube_pred.get("workflow", []), _mach_cfg_pred)
                    if _duree_pred > _val_rest:
                        _tube_pred["perime"] = True
                        self.tubes_perimes += 1
                        self.tubes_degrades += 1
                        if not self.headless and self.canvas.winfo_exists() and _tube_pred.get("id"):
                            self.canvas.itemconfig(_tube_pred["id"],
                                                  fill="#bdc3c7", outline="#e74c3c", width=2)
                            _tid_pred = _tube_pred["id"]
                            self.canvas.after(
                                800,
                                lambda _t=_tid_pred: self.canvas.delete(_t)
                                if self.canvas.winfo_exists() else None)
                        continue
                _batch_viables.append(_tube_pred)
            batch = _batch_viables

            yield self.env.timeout(temps / 10)

            # Accumuler le temps machine SimPy sur chaque tube du batch
            # (utilisé pour calculer le TAT réel : non-machine en 1:1, machine en ×10)
            machine_simpy_elapsed = temps / 10
            for _tb in batch:
                _tb["_machine_temps_simpy"] = (
                    _tb.get("_machine_temps_simpy", 0) + machine_simpy_elapsed
                )

            delai_max = machine.get("delai_max_avant_degrad", None)
            if delai_max is not None:
                batch_valides = []
                for tube in batch:
                    attente_totale = self.env.now - tube.get("arrivee", self.env.now)
                    if attente_totale > delai_max:
                        self.tubes_degrades += 1
                        if not self.headless and self.canvas.winfo_exists() and tube.get("id"):
                            self.canvas.itemconfig(tube["id"], fill="#95a5a6", outline="#7f8c8d", width=1)
                            tid = tube["id"]
                            self.canvas.after(800, lambda t=tid: self.canvas.delete(t) if self.canvas.winfo_exists() else None)
                    else:
                        batch_valides.append(tube)
                batch = batch_valides

            if nom_machine in self.panne_machines:
                repair_ev = self.machine_repair_events.get(nom_machine)
                if repair_ev is not None and not repair_ev.triggered:
                    yield repair_ev

            if not self.headless and self.canvas.winfo_exists():
                for tube in batch:
                    if tube.get("id"):
                        self.canvas.itemconfig(tube["id"],
                                              fill=tube.get("couleur", "#27ae60"),
                                              outline="#27ae60", width=2)

            if nom_machine not in self.output_queues:
                self.output_queues[nom_machine] = []
            self.output_queues[nom_machine].extend(batch)

            self.blinking_machines.discard(nom_machine)

            if self.machine_queues.get(nom_machine):
                _respawn = True

        finally:
            # SimPy est single-threaded : pas de yield entre discard et add
            # => aucune fenetre d ouverture pour un doublon.
            self._machines_batch_actif.discard(nom_machine)
            if _respawn:
                if self._debug_mode:
                    self._debug_entries.append({
                        "ev": "respawn", "t": self.env.now, "machine": nom_machine,
                        "q_restante": len(self.machine_queues.get(nom_machine, [])),
                    })
                self._machines_batch_actif.add(nom_machine)
                self.env.process(self.traiter_batch_machine(nom_machine, machine))
