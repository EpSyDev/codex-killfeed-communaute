"""
CodeX KillFeed — Dictionnaire de traductions FR
Utilisé dans embeds.py pour l'affichage

Usage :
    from bot.translations import translate_item, translate_entity
"""

# ─── Placements ───────────────────────────────────────────────────────────────
# Clés = noms bruts du log ADM (après stripped)

ITEM_TRANSLATIONS: dict[str, str] = {
    # Conteneurs
    "Barrel":               "Baril",
    "Barrel_Green":         "Baril Vert",
    "Barrel_Blue":          "Baril Bleu",
    "Barrel_Red":           "Baril Rouge",
    "Barrel_Yellow":        "Baril Jaune",
    "Sea Chest":            "Coffre Marin",
    "Wooden Crate":         "Caisse en Bois",
    "PlasticCase":          "Valise Plastique",
    "GunCase":              "Mallette à Arme",
    "AmmoBox":              "Boîte de Munitions",

    # Pièges
    "Bear Trap":            "Piège à Ours",
    "BearTrap":             "Piège à Ours",
    "LandMine":             "Mine Anti-Personnel",
    "Tripwire":             "Fil Piège",

    # Feux / Cuisson
    "FireplaceBase":        "Feu de Camp",
    "Fireplace":            "Feu de Camp",
    "OvenStone":            "Four en Pierre",
    "BarbecueFire":         "Barbecue",
    "IndoorOven":           "Poêle Intérieur",

    # Base building
    "Fence":                "Clôture",
    "Wall":                 "Mur",
    "Gate":                 "Portail",
    "Watchtower":           "Tour de Guet",
    "Tent":                 "Tente",
    "CarTent":              "Tente Voiture",
    "MediumTent":           "Tente Moyenne",
    "LargeTent":            "Grande Tente",

    # Véhicules posés
    "Flag":                 "Drapeau",
    "FlagKit":              "Kit Drapeau",
}

# ─── Constructions ────────────────────────────────────────────────────────────
# Clés = identifiants de niveau bruts (level_X_base, level_X_wall, etc.)

BUILD_TRANSLATIONS: dict[str, str] = {
    "level_1_base":         "Base Niv.1",
    "level_2_base":         "Base Niv.2",
    "level_3_base":         "Base Niv.3",
    "level_1_wall":         "Mur Niv.1",
    "level_2_wall":         "Mur Niv.2",
    "level_3_wall":         "Mur Niv.3",
    "level_1_roof":         "Toit Niv.1",
    "level_2_roof":         "Toit Niv.2",
    "level_1_gate":         "Portail Niv.1",
    "level_2_gate":         "Portail Niv.2",
    "level_1_floor":        "Plancher Niv.1",
    "level_2_floor":        "Plancher Niv.2",
    "level_1_stairs":       "Escalier Niv.1",
    "level_2_stairs":       "Escalier Niv.2",
}

# ─── Outils de construction ───────────────────────────────────────────────────
TOOL_TRANSLATIONS: dict[str, str] = {
    "Shovel":               "Pelle",
    "Pickaxe":              "Pioche",
    "Hatchet":              "Hache",
    "Hammer":               "Marteau",
    "Screwdriver":          "Tournevis",
    "Pliers":               "Pinces",
}

# ─── Entités PVE ──────────────────────────────────────────────────────────────

# Zombies — prefixes connus DayZ
_ZMB_TYPES: dict[str, str] = {
    "VillagerOld":          "Zombie Villageois",
    "VillagerFemale":       "Zombie Villageoise",
    "VillagerMale":         "Zombie Villageois",
    "Soldier":              "Zombie Soldat",
    "PatrolNormal":         "Zombie Patrouille",
    "PatrolSoldier":        "Zombie Soldat Patrouille",
    "PoliceMan":            "Zombie Policier",
    "PoliceWoman":          "Zombie Policière",
    "FireFighter":          "Zombie Pompier",
    "MedicalStaff":         "Zombie Médecin",
    "Mummy":                "Zombie Momie",
    "Priest":               "Zombie Prêtre",
    "Hunter":               "Zombie Chasseur",
    "Mechanic":             "Zombie Mécanicien",
    "Worker":               "Zombie Ouvrier",
    "Scientist":            "Zombie Scientifique",
    "Refugee":              "Zombie Réfugié",
    "Townsman":             "Zombie Bourgeois",
    "Nurse":                "Zombie Infirmière",
}

# Animaux
ANIMAL_TRANSLATIONS: dict[str, str] = {
    "Wolf":                 "Loup",
    "Bear":                 "Ours",
    "Boar":                 "Sanglier",
    "Deer":                 "Cerf",
    "Cow":                  "Vache",
    "Hen":                  "Poule",
    "Pig":                  "Cochon",
    "Goat":                 "Chèvre",
    "Rabbit":               "Lapin",
    "Fox":                  "Renard",
    "BrownBear":            "Ours Brun",
}

# Classnames des logs ADM : Animal_<Espèce>[F][_Variante] → clé = espèce latine.
# Inclut les animaux ajoutés par Nasdara (1.30) : chiens, mouflon, varan.
ANIMAL_SPECIES: dict[str, str] = {
    "CanisLupus":           "Loup",
    "UrsusArctos":          "Ours Brun",
    "SusScrofa":            "Sanglier",
    "SusDomesticus":        "Cochon",
    "CervusElaphus":        "Cerf",
    "CapreolusCapreolus":   "Chevreuil",
    "RangiferTarandus":     "Renne",
    "BosTaurus":            "Vache",
    "GallusGallusDomesticus": "Poule",
    "CapraHircus":          "Chèvre",
    "OvisAries":            "Mouton",
    "OvisGmelini":          "Mouflon",
    "LepusEuropaeus":       "Lièvre",
    "VulpesVulpes":         "Renard",
    "CanisFamiliaris":      "Chien",
    "VaranusGriseus":       "Varan",
}

# Causes environnementales
ENV_TRANSLATIONS: dict[str, str] = {
    "FallDamage":           "Chute",
    "FallDamageHealth":     "Chute",
    "FireDamage":           "Brûlures",
    "Bleeding":             "Saignement",
    "Dehydration":          "Déshydratation",
    "Starvation":           "Famine",
    "LandMineExplosion":    "Mine Anti-Personnel",
    "FlashGrenade_Ammo":    "Grenade Flash",
    "Grenade_Ammo":         "Grenade",
    "RGD5Grenade_Ammo":     "Grenade RGD-5",
    "M67Grenade_Ammo":      "Grenade M67",
    "Infected":             "Infecté",
    "Bleedout":             "Hémorragie",
    "Unconscious":          "Inconscient",
    "Regained consciousness": "Reprise de conscience",
}

# ─── Fonctions publiques ──────────────────────────────────────────────────────

def translate_item(raw: str) -> str:
    """Traduit un nom d'objet placé (placement event)."""
    if not raw:
        return raw
    clean = raw.strip()
    return ITEM_TRANSLATIONS.get(clean, clean)


def translate_build(raw: str) -> str:
    """Traduit un identifiant de construction (level_2_base → Base Niv.2)."""
    if not raw:
        return raw
    clean = raw.strip().lower()
    return BUILD_TRANSLATIONS.get(clean, raw.strip())


def translate_tool(raw: str) -> str:
    """Traduit un outil de construction."""
    if not raw:
        return raw
    return TOOL_TRANSLATIONS.get(raw.strip(), raw.strip())


def translate_entity(raw: str) -> str:
    """
    Traduit une entité PVE (zombie, animal, environnement).
    Gère les prefixes complexes type ZmbF_VillagerOld_Green.
    """
    if not raw:
        return raw
    clean = raw.strip()

    # Environnement direct
    if clean in ENV_TRANSLATIONS:
        return ENV_TRANSLATIONS[clean]

    # Animal direct
    if clean in ANIMAL_TRANSLATIONS:
        return ANIMAL_TRANSLATIONS[clean]

    # Animal classname : Animal_CanisLupus_Grey, Animal_CervusElaphusF…
    if clean.lower().startswith("animal_"):
        species = clean.split("_")[1]
        for key in sorted(ANIMAL_SPECIES, key=len, reverse=True):
            if species.startswith(key):
                return ANIMAL_SPECIES[key]
        return "Animal"

    # Zombie — format : ZmbF_TypeVariant_Skin ou ZmbM_TypeVariant_Skin
    if clean.lower().startswith(("zmbf_", "zmbm_", "zmb_")):
        # Extraire la partie type : ZmbF_VillagerOld_Green → VillagerOld
        parts = clean.split("_")
        if len(parts) >= 2:
            type_key = parts[1]  # ex: "VillagerOld", "PatrolNormal"
            # Chercher correspondance partielle
            for key, label in _ZMB_TYPES.items():
                if type_key.lower().startswith(key.lower()):
                    return label
        return "Zombie Infecté"  # fallback générique

    # Infected générique (PC)
    if clean.lower() == "infected":
        return "Infecté"

    # Fallback — retourne brut
    return clean
