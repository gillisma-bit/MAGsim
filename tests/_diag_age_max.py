"""Script de diagnostic : simulation headless 2 jours, analyse age max tube."""
import sys, simpy
sys.path.insert(0, r"f:\code python\MAGsim")

from core.config_manager import ConfigManager
from core.technician import TechnicianState
from core.stats_aggregator import StatsAggregator
from ui.tab_live import TabLive

cm = ConfigManager()

class FakeCanvas:
    def winfo_exists(self): return False
    def itemconfig(self, *a, **kw): pass
    def coords(self, *a, **kw): pass
    def create_oval(self, *a, **kw): return None
    def create_rectangle(self, *a, **kw): return None
    def create_text(self, *a, **kw): return None
    def after(self, *a, **kw): pass
    def delete(self, *a): pass

class FakeParent:
    def after(self, *a, **kw): pass

tab = TabLive.__new__(TabLive)
tab.parent = FakeParent()
tab.config_manager = cm
tab.headless = True
tab.canvas = FakeCanvas()
tab.running = False
tab.technicians = []
tab.entry_queue = []
tab.machine_queues = {}
tab.output_queues = {}
tab.blinking_machines = set()
tab.panne_machines = set()
tab.machine_repair_events = {}
tab.paillasse_analyste = set()
tab.tubes_sortis = 0
tab.tubes_rejetes = 0
tab.tubes_degrades = 0
tab.tubes_perimes = 0
tab.transit_times_raw = []
tab.heure_debut_sim = 7.0
tab.stats_tubes_total = 0
tab.prochaine_arrivee = 0
tab.machine_rect_ids = {}
tab.machine_indicators = {}
tab.machine_labels = {}
tab.machine_labels_queue = {}
tab.machine_labels_output = {}
tab.mode_sans_arret_maladie = True
tab._sol_cache = {}
tab.types_tubes = cm.data.get("types_tubes", {})
tab.stats_history = {
    "time": [], "entry": [], "queues": {}, "output": {}, "busy": {},
    "transit_time_avg": [], "transit_time_rolling": [], "transit_time_pending_max": [],
    "rejetes": [], "degrades": [], "arrivees_par_heure": {},
    "distances_tech": {}, "bienetre": {}, "events_arret_maladie": [],
}
tab.aggregator = StatsAggregator()

env = simpy.Environment()
tab.env = env
tab.running = True

machines = cm.get_machines()
tech_offices = [(k, m) for k, m in machines.items() if m["type"] == "TECH_OFFICE"]
horaires_cfg = cm.data.get("horaires", {})

print(f"Nb techs TECH_OFFICE: {len(tech_offices)}")
for k, m in tech_offices:
    nom = m.get("nom") or k
    h = horaires_cfg.get(nom, {})
    print(f"  {nom}: jours={h.get('jours','?')}, {h.get('heure_debut','?')}h-{h.get('heure_fin','?')}h, actif={h.get('actif',True)}")

env.process(tab.tube_generation())
env.process(tab.stats_collector())

for idx, (office_key, office) in enumerate(tech_offices):
    nom = office.get("nom") or office_key
    ox = office["coords"]["x"]
    oy = office["coords"]["y"]
    tech = TechnicianState(ox, oy, canvas_id=None, index=idx)
    tech.nom = nom
    tech.office_x = ox
    tech.office_y = oy
    tech.age = int(office.get("age", 35))
    tech.experience = int(office.get("experience", 3))
    tech.pct_erreur_tech = float(office.get("pct_erreur_tech", 0.0))
    tech.seuil_charge_fatigue = float(office.get("seuil_charge_fatigue", 0.7))
    tech.taux_montee_fatigue = float(office.get("taux_montee_fatigue", 0.01))
    tech.taux_recuperation_nuit = float(office.get("taux_recuperation_nuit", 0.15))
    tech.capacite_max_tubes = int(office.get("capacite_max_tubes", 10))
    tab.technicians.append(tech)
    env.process(tab.technician_process(tech))

DUREE = 2880  # 2 jours
env.run(until=DUREE)
tab.running = False

pend = [v for v in tab.stats_history["transit_time_pending_max"] if v is not None]
times = tab.stats_history["time"]

print(f"\n=== Résultats 2 jours ({DUREE} min) ===")
if pend:
    pic = max(pend)
    print(f"Age max tube en attente : {pic:.0f} min = {pic/60:.1f} h")
    print(f"Age moyen (toute la serie) : {sum(pend)/len(pend):.0f} min")
    # Afficher la série par tranches de 240 min (4h)
    tranches = {}
    for t_val, p_val in zip(times[:len(pend)], pend):
        tr = int(t_val // 240)
        tranches.setdefault(tr, []).append(p_val)
    print("\nEvolution par tranche de 4h (age max, min):")
    for tr in sorted(tranches):
        h_debut = tr * 4
        print(f"  t={h_debut:4d}-{h_debut+4:4d}h  max={max(tranches[tr]):6.0f} min ({max(tranches[tr])/60:.1f}h)")
else:
    print("Pas de données pending_max")

print(f"\nTubes sortis: {tab.tubes_sortis}")
print(f"Entry queue restante: {len(tab.entry_queue)}")
if tab.entry_queue:
    ages = sorted([DUREE - t.get("arrivee", DUREE) for t in tab.entry_queue], reverse=True)
    print(f"Ages top 10 (min): {[round(a) for a in ages[:10]]}")
    # Par heure d'arrivée
    from collections import Counter
    heures_arr = Counter(int((t.get("arrivee", 0) / 60 + 7) % 24) for t in tab.entry_queue)
    print(f"Tubes bloqués par heure d'arrivée: {dict(sorted(heures_arr.items()))}")
