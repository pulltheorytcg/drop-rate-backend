"""Physical resale applicability, without removing reference catalogue records."""

# Verified against TCGdex /v2/en/series/tcgp, 13 October 2026. Match exact
# provider, game, locale, set ID AND set title. Never classify by A/B prefix.
POCKET_RELEASES = {
    'A1': 'Genetic Apex', 'P-A': 'Promos-A', 'A1a': 'Mythical Island',
    'A2': 'Space-Time Smackdown', 'A2a': 'Triumphant Light',
    'A2b': 'Shining Revelry', 'A3': 'Celestial Guardians',
    'A3a': 'Extradimensional Crisis', 'A3b': 'Eevee Grove',
    'A4': 'Wisdom of Sea and Sky', 'A4a': 'Secluded Springs',
    'B1': 'Mega Rising', 'B1a': 'Crimson Blaze',
    'B2': 'Fantastical Parade', 'B2a': 'Paldean Wonders',
}

# Static SQL literals only; no user-input interpolation.
_POCKET_PAIRS = ','.join("('%s','%s')" % (key, value.replace("'", "''"))
                         for key, value in POCKET_RELEASES.items())
DIGITAL_REFERENCE_SQL = """(r.provider='TCGdex' and r.system_code='POKEMON_TCG'
 and r.language='English' and (r.set_id,s.name) in (""" + _POCKET_PAIRS + '))'
