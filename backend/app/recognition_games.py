"""Game lines are explicit: sharing a franchise never makes cards interchangeable."""
import re


def collector_key(value):
    text = str(value or '').upper().strip()
    # Keep fraction boundaries and printing symbols (Kayou diamond, SLR +/-).
    # Padding is irrelevant; identifier components and symbols are not.
    return ':'.join(str(int(t)) if t.isdecimal() else t
                    for t in re.findall(r'[A-Z]+|[0-9]+|[/+◇]', text)) + ('-' if text.endswith('-') else '')

SYSTEM_BY_GAME = {
    "Pokemon": "POKEMON_TCG",
    "One Piece": "ONE_PIECE_CARD_GAME",
    "Dragon Ball Super Masters": "DRAGON_BALL_SUPER_MASTERS",
    "Dragon Ball Super Fusion World": "DRAGON_BALL_SUPER_FUSION_WORLD",
    "Naruto Kayou": "NARUTO_KAYOU",
    "Naruto Bandai Legacy": "NARUTO_BANDAI_LEGACY",
    "Naruto Bandai": "NARUTO_BANDAI",
    "Yu-Gi-Oh!": "YUGIOH",
    "Riftbound": "RIFTBOUND",
    "Disney Lorcana": "DISNEY_LORCANA",
}

SOURCE_COVERAGE = {
    "Pokemon": ("TCGdex", "English/Japanese card and set records; physical finishes require review"),
    "One Piece": ("Punk Records", "English/Japanese reference index; promos and parallels remain separate"),
    "Dragon Ball Super Masters": ("Bandai Official", "Official English checklists; front/back images and release references are separate"),
    "Dragon Ball Super Fusion World": ("Bandai Official", "Official English/Japanese checklists; alternate artwork remains separate"),
    "Naruto Kayou": ("Naruto Card Game Archive", "Community references preserve tiers/waves; physical language, edition and finish require review"),
    "Naruto Bandai Legacy": ("Naruto Card Game Archive", "Community legacy references; physical language, edition and finish require review"),
    "Naruto Bandai": (None, "Announced for 2027; released catalogue not yet available"),
    "Yu-Gi-Oh!": ("YGOPRODeck", "Set codes and rarities preserved; edition/artwork assignments require review"),
    "Riftbound": ("Riftcodex", "Reference card and set data; language and physical finish require review"),
    "Disney Lorcana": ("Lorcast", "Card and set records; shared digital art does not establish foil finish"),
}
