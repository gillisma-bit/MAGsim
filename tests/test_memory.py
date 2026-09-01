import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai_memory import (sauvegarder_exemple, sauvegarder_resume_session,
                             construire_section_memoire, nb_exemples, charger)
from core.ai_assistant import Conversation

NOM_LABO = "Nouveau Projet MAGsim"

# 1. Sauvegarder un exemple approuve
sauvegarder_exemple("Marc est fatigue", "Voici ce que je recommande...", NOM_LABO)
assert nb_exemples(NOM_LABO) == 1, "exemple non sauvegarde"
print("Sauvegarde exemple: OK")

# 2. Sauvegarder une session
msgs = [
    {"role": "user",      "content": "Marc part a la retraite"},
    {"role": "assistant", "content": "Bien note, qui le remplace ?"},
]
sauvegarder_resume_session(msgs, ["machines.b1.nom: Marc -> Paul"], NOM_LABO)
mem = charger()
assert len(mem["sessions"]) == 1, "session non sauvegardee"
print("Sauvegarde session: OK")

# 3. Section memoire generee
section = construire_section_memoire(NOM_LABO)
assert "Marc est fatigue" in section
assert "Marc part a la retraite" in section
print("Section memoire: OK")

# 4. Injection dans le prompt systeme
with open("data/config_mag.json", encoding="utf-8") as f:
    cfg = json.load(f)
conv = Conversation(model="mistral")
conv.initialiser(cfg)
assert "Marc est fatigue" in conv._system,     "exemple absent du prompt"
assert "Marc part a la retraite" in conv._system, "session absente du prompt"
print(f"Memoire dans prompt systeme: OK ({len(conv._system)} caracteres)")

# Nettoyage
os.remove("data/memoire_assistant.json")
print("Tous les tests passes.")
