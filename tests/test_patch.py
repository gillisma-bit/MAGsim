"""Test rapide de la logique de patch ai_assistant."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai_assistant import extraire_patch, appliquer_patch, texte_sans_patch

PATCH_DEBUT = "```config_patch"
PATCH_FIN   = "```"

reponse_llm = (
    "Marc a maintenant 5 ans d'experience. Je propose :\n\n"
    + PATCH_DEBUT + "\n"
    + '[{"chemin": "machines.b1.experience", "valeur": 5}, '
    + '{"chemin": "machines.b1.nom", "valeur": "Marc"}]\n'
    + PATCH_FIN + "\n\n"
    + "Ces changements seront appliques apres votre confirmation."
)

patch = extraire_patch(reponse_llm)
assert patch is not None, "Patch non extrait"
assert len(patch) == 2, f"Attendu 2 ops, obtenu {len(patch)}"
print("Patch extrait:", patch)

config = {"machines": {"b1": {"nom": "Marc", "experience": 3}}, "sol": {}}
nouveau, desc = appliquer_patch(config, patch)
print("Changements:")
for d in desc:
    print(" ", d)
assert nouveau["machines"]["b1"]["experience"] == 5
assert nouveau["machines"]["b1"]["nom"] == "Marc"
print("Config apres:", nouveau["machines"]["b1"])

texte = texte_sans_patch(reponse_llm)
assert PATCH_DEBUT not in texte, "Bloc patch present dans le texte propre"
print("Texte propre OK:", texte[:60].replace("\n", " "))

# Test chemin interdit
try:
    appliquer_patch(config, [{"chemin": "sol.plan", "valeur": {}}])
    assert False, "Aurait du lever ValueError"
except ValueError as e:
    print("Protection sol OK:", e)

print("\nTous les tests de patch sont passes.")
