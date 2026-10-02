"use strict";
// Official source identities and original-byte hashes: title-art/sources.json.
window.DropRateTitleArt = (() => {
  const data = {
  "games": {
    "POKEMON_TCG": {
      "file": "pokemon.webp",
      "caption": ""
    },
    "ONE_PIECE_CARD_GAME": {
      "file": "one-piece-white.png",
      "caption": ""
    },
    "DRAGON_BALL_SUPER_MASTERS": {
      "file": "masters.png",
      "caption": ""
    },
    "DRAGON_BALL_SUPER_FUSION_WORLD": {
      "file": "fusion-world.png",
      "caption": ""
    },
    "NARUTO_KAYOU": {
      "file": "naruto.svg",
      "caption": "KAYOU"
    },
    "NARUTO_BANDAI_LEGACY": {
      "file": "naruto.svg",
      "caption": "BANDAI LEGACY"
    }
  },
  "sets": [
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "30th Celebration"
      ],
      "title": "30th Celebration",
      "file": "pokemon-30th-celebration.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Mega Evolution—Pitch Black",
        "Pitch Black"
      ],
      "title": "Mega Evolution—Pitch Black",
      "file": "pokemon-mega-evolution-pitch-black.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Mega Evolution—Chaos Rising",
        "Chaos Rising"
      ],
      "title": "Mega Evolution—Chaos Rising",
      "file": "pokemon-mega-evolution-chaos-rising.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Mega Evolution—Perfect Order",
        "Perfect Order"
      ],
      "title": "Mega Evolution—Perfect Order",
      "file": "pokemon-mega-evolution-perfect-order.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Mega Evolution—Ascended Heroes",
        "Ascended Heroes"
      ],
      "title": "Mega Evolution—Ascended Heroes",
      "file": "pokemon-mega-evolution-ascended-heroes.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Mega Evolution—Phantasmal Flames",
        "Phantasmal Flames"
      ],
      "title": "Mega Evolution—Phantasmal Flames",
      "file": "pokemon-mega-evolution-phantasmal-flames.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Mega Evolution"
      ],
      "title": "Mega Evolution",
      "file": "pokemon-mega-evolution.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—Journey Together",
        "Journey Together"
      ],
      "title": "Scarlet & Violet—Journey Together",
      "file": "pokemon-scarlet-violet-journey-together.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—Prismatic Evolutions",
        "Prismatic Evolutions"
      ],
      "title": "Scarlet & Violet—Prismatic Evolutions",
      "file": "pokemon-scarlet-violet-prismatic-evolutions.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—Surging Sparks",
        "Surging Sparks"
      ],
      "title": "Scarlet & Violet—Surging Sparks",
      "file": "pokemon-scarlet-violet-surging-sparks.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—Stellar Crown",
        "Stellar Crown"
      ],
      "title": "Scarlet & Violet—Stellar Crown",
      "file": "pokemon-scarlet-violet-stellar-crown.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—Shrouded Fable",
        "Shrouded Fable"
      ],
      "title": "Scarlet & Violet—Shrouded Fable",
      "file": "pokemon-scarlet-violet-shrouded-fable.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—Twilight Masquerade",
        "Twilight Masquerade"
      ],
      "title": "Scarlet & Violet—Twilight Masquerade",
      "file": "pokemon-scarlet-violet-twilight-masquerade.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—Temporal Forces",
        "Temporal Forces"
      ],
      "title": "Scarlet & Violet—Temporal Forces",
      "file": "pokemon-scarlet-violet-temporal-forces.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—Paldean Fates",
        "Paldean Fates"
      ],
      "title": "Scarlet & Violet—Paldean Fates",
      "file": "pokemon-scarlet-violet-paldean-fates.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—Paradox Rift",
        "Paradox Rift"
      ],
      "title": "Scarlet & Violet—Paradox Rift",
      "file": "pokemon-scarlet-violet-paradox-rift.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—151",
        "151"
      ],
      "title": "Scarlet & Violet—151",
      "file": "pokemon-scarlet-violet-151.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—Obsidian Flames",
        "Obsidian Flames"
      ],
      "title": "Scarlet & Violet—Obsidian Flames",
      "file": "pokemon-scarlet-violet-obsidian-flames.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet—Paldea Evolved",
        "Paldea Evolved"
      ],
      "title": "Scarlet & Violet—Paldea Evolved",
      "file": "pokemon-scarlet-violet-paldea-evolved.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Scarlet & Violet"
      ],
      "title": "Scarlet & Violet",
      "file": "pokemon-scarlet-violet.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Crown Zenith"
      ],
      "title": "Crown Zenith",
      "file": "pokemon-crown-zenith.jpg"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Sword & Shield—Silver Tempest",
        "Silver Tempest"
      ],
      "title": "Sword & Shield—Silver Tempest",
      "file": "pokemon-sword-shield-silver-tempest.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Sword & Shield—Lost Origin",
        "Lost Origin"
      ],
      "title": "Sword & Shield—Lost Origin",
      "file": "pokemon-sword-shield-lost-origin.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Pokémon GO",
        "Pokemon GO"
      ],
      "title": "Pokémon GO",
      "file": "pokemon-pok-mon-go.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Sword & Shield—Astral Radiance",
        "Astral Radiance"
      ],
      "title": "Sword & Shield—Astral Radiance",
      "file": "pokemon-sword-shield-astral-radiance.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Sword & Shield—Brilliant Stars",
        "Brilliant Stars"
      ],
      "title": "Sword & Shield—Brilliant Stars",
      "file": "pokemon-sword-shield-brilliant-stars.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Sword & Shield—Fusion Strike",
        "Fusion Strike"
      ],
      "title": "Sword & Shield—Fusion Strike",
      "file": "pokemon-sword-shield-fusion-strike.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Celebrations"
      ],
      "title": "Celebrations",
      "file": "pokemon-celebrations.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Sword & Shield—Evolving Skies",
        "Evolving Skies"
      ],
      "title": "Sword & Shield—Evolving Skies",
      "file": "pokemon-sword-shield-evolving-skies.png"
    },
    {
      "system": "POKEMON_TCG",
      "language": "English",
      "names": [
        "Sword & Shield—Chilling Reign",
        "Chilling Reign"
      ],
      "title": "Sword & Shield—Chilling Reign",
      "file": "pokemon-sword-shield-chilling-reign.png"
    },
    {
      "system": "ONE_PIECE_CARD_GAME",
      "language": "English",
      "names": [
        "Carrying on His Will",
        "CARRYING ON HIS WILL [OP-13]",
        "BOOSTER PACK -CARRYING ON HIS WILL- [OP-13]"
      ],
      "title": "Carrying on His Will",
      "file": "op13-en.webp",
      "codes": [
        "OP13",
        "OP-13"
      ],
      "provider_ids": {
        "Punk Records": [
          "569113"
        ]
      }
    },
    {
      "system": "ONE_PIECE_CARD_GAME",
      "language": "Japanese",
      "names": [
        "受け継がれる意志",
        "受け継がれる意志【OP-13】"
      ],
      "title": "受け継がれる意志",
      "file": "op13-ja.webp",
      "codes": [
        "OP13",
        "OP-13"
      ],
      "provider_ids": {
        "Punk Records": [
          "550113"
        ]
      }
    }
  ]
};
  // BEGIN TCGDEX SET LOGOS
  const providerSets = {
  "English": {
    "base1": {
      "title": "Base Set",
      "url": "https://assets.tcgdex.net/en/base/base1/logo.webp"
    },
    "base2": {
      "title": "Jungle",
      "url": "https://assets.tcgdex.net/en/base/base2/logo.webp"
    },
    "basep": {
      "title": "Wizards Black Star Promos",
      "url": "https://assets.tcgdex.net/en/base/basep/logo.webp"
    },
    "base3": {
      "title": "Fossil",
      "url": "https://assets.tcgdex.net/en/base/base3/logo.webp"
    },
    "base4": {
      "title": "Base Set 2",
      "url": "https://assets.tcgdex.net/en/base/base4/logo.webp"
    },
    "base5": {
      "title": "Team Rocket",
      "url": "https://assets.tcgdex.net/en/base/base5/logo.webp"
    },
    "gym1": {
      "title": "Gym Heroes",
      "url": "https://assets.tcgdex.net/en/gym/gym1/logo.webp"
    },
    "gym2": {
      "title": "Gym Challenge",
      "url": "https://assets.tcgdex.net/en/gym/gym2/logo.webp"
    },
    "neo1": {
      "title": "Neo Genesis",
      "url": "https://assets.tcgdex.net/en/neo/neo1/logo.webp"
    },
    "neo2": {
      "title": "Neo Discovery",
      "url": "https://assets.tcgdex.net/en/neo/neo2/logo.webp"
    },
    "si1": {
      "title": "Southern Islands",
      "url": "https://assets.tcgdex.net/en/neo/si1/logo.webp"
    },
    "neo3": {
      "title": "Neo Revelation",
      "url": "https://assets.tcgdex.net/en/neo/neo3/logo.webp"
    },
    "neo4": {
      "title": "Neo Destiny",
      "url": "https://assets.tcgdex.net/en/neo/neo4/logo.webp"
    },
    "lc": {
      "title": "Legendary Collection",
      "url": "https://assets.tcgdex.net/en/lc/lc/logo.webp"
    },
    "ecard1": {
      "title": "Expedition Base Set",
      "url": "https://assets.tcgdex.net/en/ecard/ecard1/logo.webp"
    },
    "ecard2": {
      "title": "Aquapolis",
      "url": "https://assets.tcgdex.net/en/ecard/ecard2/logo.webp"
    },
    "ecard3": {
      "title": "Skyridge",
      "url": "https://assets.tcgdex.net/en/ecard/ecard3/logo.webp"
    },
    "ex1": {
      "title": "Ruby & Sapphire",
      "url": "https://assets.tcgdex.net/en/ex/ex1/logo.webp"
    },
    "ex2": {
      "title": "Sandstorm",
      "url": "https://assets.tcgdex.net/en/ex/ex2/logo.webp"
    },
    "np": {
      "title": "Nintendo Black Star Promos",
      "url": "https://assets.tcgdex.net/en/pop/np/logo.webp"
    },
    "ex3": {
      "title": "Dragon",
      "url": "https://assets.tcgdex.net/en/ex/ex3/logo.webp"
    },
    "ex4": {
      "title": "Team Magma vs Team Aqua",
      "url": "https://assets.tcgdex.net/en/ex/ex4/logo.webp"
    },
    "ex5": {
      "title": "Hidden Legends",
      "url": "https://assets.tcgdex.net/en/ex/ex5/logo.webp"
    },
    "ex6": {
      "title": "FireRed & LeafGreen",
      "url": "https://assets.tcgdex.net/en/ex/ex6/logo.webp"
    },
    "pop1": {
      "title": "POP Series 1",
      "url": "https://assets.tcgdex.net/en/pop/pop1/logo.webp"
    },
    "ex7": {
      "title": "Team Rocket Returns",
      "url": "https://assets.tcgdex.net/en/ex/ex7/logo.webp"
    },
    "ex8": {
      "title": "Deoxys",
      "url": "https://assets.tcgdex.net/en/ex/ex8/logo.webp"
    },
    "ex9": {
      "title": "Emerald",
      "url": "https://assets.tcgdex.net/en/ex/ex9/logo.webp"
    },
    "pop2": {
      "title": "POP Series 2",
      "url": "https://assets.tcgdex.net/en/pop/pop2/logo.webp"
    },
    "ex10": {
      "title": "Unseen Forces",
      "url": "https://assets.tcgdex.net/en/ex/ex10/logo.webp"
    },
    "ex11": {
      "title": "Delta Species",
      "url": "https://assets.tcgdex.net/en/ex/ex11/logo.webp"
    },
    "ex12": {
      "title": "Legend Maker",
      "url": "https://assets.tcgdex.net/en/ex/ex12/logo.webp"
    },
    "pop3": {
      "title": "POP Series 3",
      "url": "https://assets.tcgdex.net/en/pop/pop3/logo.webp"
    },
    "ex13": {
      "title": "Holon Phantoms",
      "url": "https://assets.tcgdex.net/en/ex/ex13/logo.webp"
    },
    "pop4": {
      "title": "POP Series 4",
      "url": "https://assets.tcgdex.net/en/pop/pop4/logo.webp"
    },
    "ex14": {
      "title": "Crystal Guardians",
      "url": "https://assets.tcgdex.net/en/ex/ex14/logo.webp"
    },
    "ex15": {
      "title": "Dragon Frontiers",
      "url": "https://assets.tcgdex.net/en/ex/ex15/logo.webp"
    },
    "ex16": {
      "title": "Power Keepers",
      "url": "https://assets.tcgdex.net/en/ex/ex16/logo.webp"
    },
    "pop5": {
      "title": "POP Series 5",
      "url": "https://assets.tcgdex.net/en/pop/pop5/logo.webp"
    },
    "dpp": {
      "title": "DP Black Star Promos",
      "url": "https://assets.tcgdex.net/en/dp/dpp/logo.webp"
    },
    "dp1": {
      "title": "Diamond & Pearl",
      "url": "https://assets.tcgdex.net/en/dp/dp1/logo.webp"
    },
    "dp2": {
      "title": "Mysterious Treasures",
      "url": "https://assets.tcgdex.net/en/dp/dp2/logo.webp"
    },
    "pop6": {
      "title": "POP Series 6",
      "url": "https://assets.tcgdex.net/en/pop/pop6/logo.webp"
    },
    "dp3": {
      "title": "Secret Wonders",
      "url": "https://assets.tcgdex.net/en/dp/dp3/logo.webp"
    },
    "dp4": {
      "title": "Great Encounters",
      "url": "https://assets.tcgdex.net/en/dp/dp4/logo.webp"
    },
    "pop7": {
      "title": "POP Series 7",
      "url": "https://assets.tcgdex.net/en/pop/pop7/logo.webp"
    },
    "dp5": {
      "title": "Majestic Dawn",
      "url": "https://assets.tcgdex.net/en/dp/dp5/logo.webp"
    },
    "dp6": {
      "title": "Legends Awakened",
      "url": "https://assets.tcgdex.net/en/dp/dp6/logo.webp"
    },
    "pop8": {
      "title": "POP Series 8",
      "url": "https://assets.tcgdex.net/en/pop/pop8/logo.webp"
    },
    "dp7": {
      "title": "Stormfront",
      "url": "https://assets.tcgdex.net/en/dp/dp7/logo.webp"
    },
    "pl1": {
      "title": "Platinum",
      "url": "https://assets.tcgdex.net/en/pl/pl1/logo.webp"
    },
    "pop9": {
      "title": "POP Series 9",
      "url": "https://assets.tcgdex.net/en/pop/pop9/logo.webp"
    },
    "pl2": {
      "title": "Rising Rivals",
      "url": "https://assets.tcgdex.net/en/pl/pl2/logo.webp"
    },
    "pl3": {
      "title": "Supreme Victors",
      "url": "https://assets.tcgdex.net/en/pl/pl3/logo.webp"
    },
    "pl4": {
      "title": "Arceus",
      "url": "https://assets.tcgdex.net/en/pl/pl4/logo.webp"
    },
    "ru1": {
      "title": "Pokémon Rumble",
      "url": "https://assets.tcgdex.net/en/pl/ru1/logo.webp"
    },
    "hgss1": {
      "title": "HeartGold SoulSilver",
      "url": "https://assets.tcgdex.net/en/hgss/hgss1/logo.webp"
    },
    "hgssp": {
      "title": "HGSS Black Star Promos",
      "url": "https://assets.tcgdex.net/en/hgss/hgssp/logo.webp"
    },
    "hgss2": {
      "title": "Unleashed",
      "url": "https://assets.tcgdex.net/en/hgss/hgss2/logo.webp"
    },
    "hgss3": {
      "title": "Undaunted",
      "url": "https://assets.tcgdex.net/en/hgss/hgss3/logo.webp"
    },
    "hgss4": {
      "title": "Triumphant",
      "url": "https://assets.tcgdex.net/en/hgss/hgss4/logo.webp"
    },
    "col1": {
      "title": "Call of Legends",
      "url": "https://assets.tcgdex.net/en/col/col1/logo.webp"
    },
    "bw1": {
      "title": "Black & White",
      "url": "https://assets.tcgdex.net/en/bw/bw1/logo.webp"
    },
    "bwp": {
      "title": "BW Black Star Promos",
      "url": "https://assets.tcgdex.net/en/bw/bwp/logo.webp"
    },
    "bw2": {
      "title": "Emerging Powers",
      "url": "https://assets.tcgdex.net/en/bw/bw2/logo.webp"
    },
    "bw3": {
      "title": "Noble Victories",
      "url": "https://assets.tcgdex.net/en/bw/bw3/logo.webp"
    },
    "bw4": {
      "title": "Next Destinies",
      "url": "https://assets.tcgdex.net/en/bw/bw4/logo.webp"
    },
    "bw5": {
      "title": "Dark Explorers",
      "url": "https://assets.tcgdex.net/en/bw/bw5/logo.webp"
    },
    "bw6": {
      "title": "Dragons Exalted",
      "url": "https://assets.tcgdex.net/en/bw/bw6/logo.webp"
    },
    "dv1": {
      "title": "Dragon Vault",
      "url": "https://assets.tcgdex.net/en/bw/dv1/logo.webp"
    },
    "bw7": {
      "title": "Boundaries Crossed",
      "url": "https://assets.tcgdex.net/en/bw/bw7/logo.webp"
    },
    "bw8": {
      "title": "Plasma Storm",
      "url": "https://assets.tcgdex.net/en/bw/bw8/logo.webp"
    },
    "bw9": {
      "title": "Plasma Freeze",
      "url": "https://assets.tcgdex.net/en/bw/bw9/logo.webp"
    },
    "bw10": {
      "title": "Plasma Blast",
      "url": "https://assets.tcgdex.net/en/bw/bw10/logo.webp"
    },
    "xyp": {
      "title": "XY Black Star Promos",
      "url": "https://assets.tcgdex.net/en/xy/xyp/logo.webp"
    },
    "bw11": {
      "title": "Legendary Treasures",
      "url": "https://assets.tcgdex.net/en/bw/bw11/logo.webp"
    },
    "xy0": {
      "title": "Kalos Starter Set",
      "url": "https://assets.tcgdex.net/en/xy/xy0/logo.webp"
    },
    "xy1": {
      "title": "XY",
      "url": "https://assets.tcgdex.net/en/xy/xy1/logo.webp"
    },
    "xy2": {
      "title": "Flashfire",
      "url": "https://assets.tcgdex.net/en/xy/xy2/logo.webp"
    },
    "xy3": {
      "title": "Furious Fists",
      "url": "https://assets.tcgdex.net/en/xy/xy3/logo.webp"
    },
    "xy4": {
      "title": "Phantom Forces",
      "url": "https://assets.tcgdex.net/en/xy/xy4/logo.webp"
    },
    "xy5": {
      "title": "Primal Clash",
      "url": "https://assets.tcgdex.net/en/xy/xy5/logo.webp"
    },
    "dc1": {
      "title": "Double Crisis",
      "url": "https://assets.tcgdex.net/en/xy/dc1/logo.webp"
    },
    "xy6": {
      "title": "Roaring Skies",
      "url": "https://assets.tcgdex.net/en/xy/xy6/logo.webp"
    },
    "xy7": {
      "title": "Ancient Origins",
      "url": "https://assets.tcgdex.net/en/xy/xy7/logo.webp"
    },
    "xy8": {
      "title": "BREAKthrough",
      "url": "https://assets.tcgdex.net/en/xy/xy8/logo.webp"
    },
    "xy9": {
      "title": "BREAKpoint",
      "url": "https://assets.tcgdex.net/en/xy/xy9/logo.webp"
    },
    "g1": {
      "title": "Generations",
      "url": "https://assets.tcgdex.net/en/xy/g1/logo.webp"
    },
    "xy10": {
      "title": "Fates Collide",
      "url": "https://assets.tcgdex.net/en/xy/xy10/logo.webp"
    },
    "xy11": {
      "title": "Steam Siege",
      "url": "https://assets.tcgdex.net/en/xy/xy11/logo.webp"
    },
    "xy12": {
      "title": "Evolutions",
      "url": "https://assets.tcgdex.net/en/xy/xy12/logo.webp"
    },
    "sm1": {
      "title": "Sun & Moon",
      "url": "https://assets.tcgdex.net/en/sm/sm1/logo.webp"
    },
    "smp": {
      "title": "SM Black Star Promos",
      "url": "https://assets.tcgdex.net/en/sm/smp/logo.webp"
    },
    "sm2": {
      "title": "Guardians Rising",
      "url": "https://assets.tcgdex.net/en/sm/sm2/logo.webp"
    },
    "sm3": {
      "title": "Burning Shadows",
      "url": "https://assets.tcgdex.net/en/sm/sm3/logo.webp"
    },
    "sm4": {
      "title": "Crimson Invasion",
      "url": "https://assets.tcgdex.net/en/sm/sm4/logo.webp"
    },
    "sm5": {
      "title": "Ultra Prism",
      "url": "https://assets.tcgdex.net/en/sm/sm5/logo.webp"
    },
    "sm6": {
      "title": "Forbidden Light",
      "url": "https://assets.tcgdex.net/en/sm/sm6/logo.webp"
    },
    "sm7": {
      "title": "Celestial Storm",
      "url": "https://assets.tcgdex.net/en/sm/sm7/logo.webp"
    },
    "sm8": {
      "title": "Lost Thunder",
      "url": "https://assets.tcgdex.net/en/sm/sm8/logo.webp"
    },
    "sm9": {
      "title": "Team Up",
      "url": "https://assets.tcgdex.net/en/sm/sm9/logo.webp"
    },
    "det1": {
      "title": "Detective Pikachu",
      "url": "https://assets.tcgdex.net/en/sm/det1/logo.webp"
    },
    "sm10": {
      "title": "Unbroken Bonds",
      "url": "https://assets.tcgdex.net/en/sm/sm10/logo.webp"
    },
    "sm11": {
      "title": "Unified Minds",
      "url": "https://assets.tcgdex.net/en/sm/sm11/logo.webp"
    },
    "sm115": {
      "title": "Hidden Fates",
      "url": "https://assets.tcgdex.net/en/sm/sm115/logo.webp"
    },
    "sm12": {
      "title": "Cosmic Eclipse",
      "url": "https://assets.tcgdex.net/en/sm/sm12/logo.webp"
    },
    "swshp": {
      "title": "SWSH Black Star Promos",
      "url": "https://assets.tcgdex.net/en/swsh/swshp/logo.webp"
    },
    "swsh1": {
      "title": "Sword & Shield",
      "url": "https://assets.tcgdex.net/en/swsh/swsh1/logo.webp"
    },
    "swsh2": {
      "title": "Rebel Clash",
      "url": "https://assets.tcgdex.net/en/swsh/swsh2/logo.webp"
    },
    "swsh3": {
      "title": "Darkness Ablaze",
      "url": "https://assets.tcgdex.net/en/swsh/swsh3/logo.webp"
    },
    "fut2020": {
      "title": "Pokémon Futsal 2020",
      "url": "https://assets.tcgdex.net/en/swsh/fut2020/logo.webp"
    },
    "swsh3.5": {
      "title": "Champion's Path",
      "url": "https://assets.tcgdex.net/en/swsh/swsh3.5/logo.webp"
    },
    "swsh4": {
      "title": "Vivid Voltage",
      "url": "https://assets.tcgdex.net/en/swsh/swsh4/logo.webp"
    },
    "swsh4.5": {
      "title": "Shining Fates",
      "url": "https://assets.tcgdex.net/en/swsh/swsh4.5/logo.webp"
    },
    "swsh5": {
      "title": "Battle Styles",
      "url": "https://assets.tcgdex.net/en/swsh/swsh5/logo.webp"
    },
    "swsh6": {
      "title": "Chilling Reign",
      "url": "https://assets.tcgdex.net/en/swsh/swsh6/logo.webp"
    },
    "swsh7": {
      "title": "Evolving Skies",
      "url": "https://assets.tcgdex.net/en/swsh/swsh7/logo.webp"
    },
    "cel25": {
      "title": "Celebrations",
      "url": "https://assets.tcgdex.net/en/swsh/cel25/logo.webp"
    },
    "swsh8": {
      "title": "Fusion Strike",
      "url": "https://assets.tcgdex.net/en/swsh/swsh8/logo.webp"
    },
    "swsh9": {
      "title": "Brilliant Stars",
      "url": "https://assets.tcgdex.net/en/swsh/swsh9/logo.webp"
    },
    "swsh10": {
      "title": "Astral Radiance",
      "url": "https://assets.tcgdex.net/en/swsh/swsh10/logo.webp"
    },
    "swsh10.5": {
      "title": "Pokémon GO",
      "url": "https://assets.tcgdex.net/en/swsh/swsh10.5/logo.webp"
    },
    "swsh11": {
      "title": "Lost Origin",
      "url": "https://assets.tcgdex.net/en/swsh/swsh11/logo.webp"
    },
    "swsh12": {
      "title": "Silver Tempest",
      "url": "https://assets.tcgdex.net/en/swsh/swsh12/logo.webp"
    },
    "swsh12.5": {
      "title": "Crown Zenith",
      "url": "https://assets.tcgdex.net/en/swsh/swsh12.5/logo.webp"
    },
    "sv01": {
      "title": "Scarlet & Violet",
      "url": "https://assets.tcgdex.net/en/sv/sv01/logo.webp"
    },
    "sv02": {
      "title": "Paldea Evolved",
      "url": "https://assets.tcgdex.net/en/sv/sv02/logo.webp"
    },
    "sv03": {
      "title": "Obsidian Flames",
      "url": "https://assets.tcgdex.net/en/sv/sv03/logo.webp"
    },
    "sv03.5": {
      "title": "151",
      "url": "https://assets.tcgdex.net/en/sv/sv03.5/logo.webp"
    },
    "sv04": {
      "title": "Paradox Rift",
      "url": "https://assets.tcgdex.net/en/sv/sv04/logo.webp"
    },
    "sv04.5": {
      "title": "Paldean Fates",
      "url": "https://assets.tcgdex.net/en/sv/sv04.5/logo.webp"
    },
    "sv06": {
      "title": "Twilight Masquerade",
      "url": "https://assets.tcgdex.net/en/sv/sv06/logo.webp"
    },
    "sv06.5": {
      "title": "Shrouded Fable",
      "url": "https://assets.tcgdex.net/en/sv/sv06.5/logo.webp"
    },
    "sv07": {
      "title": "Stellar Crown",
      "url": "https://assets.tcgdex.net/en/sv/sv07/logo.webp"
    },
    "P-A": {
      "title": "Promos-A",
      "url": "https://assets.tcgdex.net/en/tcgp/P-A/logo.webp"
    },
    "A1": {
      "title": "Genetic Apex",
      "url": "https://assets.tcgdex.net/en/tcgp/A1/logo.webp"
    },
    "sv08": {
      "title": "Surging Sparks",
      "url": "https://assets.tcgdex.net/en/sv/sv08/logo.webp"
    },
    "A1a": {
      "title": "Mythical Island",
      "url": "https://assets.tcgdex.net/en/tcgp/A1a/logo.webp"
    },
    "sv08.5": {
      "title": "Prismatic Evolutions",
      "url": "https://assets.tcgdex.net/en/sv/sv08.5/logo.webp"
    },
    "A2": {
      "title": "Space-Time Smackdown",
      "url": "https://assets.tcgdex.net/en/tcgp/A2/logo.webp"
    },
    "A2a": {
      "title": "Triumphant Light",
      "url": "https://assets.tcgdex.net/en/tcgp/A2a/logo.webp"
    },
    "A2b": {
      "title": "Shining Revelry",
      "url": "https://assets.tcgdex.net/en/tcgp/A2b/logo.webp"
    },
    "sv09": {
      "title": "Journey Together",
      "url": "https://assets.tcgdex.net/en/sv/sv09/logo.webp"
    },
    "A3": {
      "title": "Celestial Guardians",
      "url": "https://assets.tcgdex.net/en/tcgp/A3/logo.webp"
    },
    "sv10": {
      "title": "Destined Rivals",
      "url": "https://assets.tcgdex.net/en/sv/sv10/logo.webp"
    },
    "sv10.5b": {
      "title": "Black Bolt",
      "url": "https://assets.tcgdex.net/en/sv/sv10.5b/logo.webp"
    },
    "sv10.5w": {
      "title": "White Flare",
      "url": "https://assets.tcgdex.net/en/sv/sv10.5w/logo.webp"
    },
    "A4": {
      "title": "Wisdom of Sea and Sky",
      "url": "https://assets.tcgdex.net/en/tcgp/A4/logo.webp"
    },
    "A4a": {
      "title": "Secluded Springs",
      "url": "https://assets.tcgdex.net/en/tcgp/A4a/logo.webp"
    },
    "me01": {
      "title": "Mega Evolution",
      "url": "https://assets.tcgdex.net/en/me/me01/logo.webp"
    },
    "B1": {
      "title": "Mega Rising",
      "url": "https://assets.tcgdex.net/en/tcgp/B1/logo.webp"
    },
    "me02": {
      "title": "Phantasmal Flames",
      "url": "https://assets.tcgdex.net/en/me/me02/logo.webp"
    },
    "B2": {
      "title": "Fantastical Parade",
      "url": "https://assets.tcgdex.net/en/tcgp/B2/logo.webp"
    },
    "me02.5": {
      "title": "Ascended Heroes",
      "url": "https://assets.tcgdex.net/en/me/me02.5/logo.webp"
    },
    "me03": {
      "title": "Perfect Order",
      "url": "https://assets.tcgdex.net/en/me/me03/logo.webp"
    },
    "me04": {
      "title": "Chaos Rising",
      "url": "https://assets.tcgdex.net/en/me/me04/logo.webp"
    },
    "me05": {
      "title": "Pitch Black",
      "url": "https://assets.tcgdex.net/en/me/me05/logo.webp"
    }
  },
  "Japanese": {}
};
  // END TCGDEX SET LOGOS
  const normalize = value => String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
  const game = system => data.games[system] || null;
  const set = row => data.sets.find(item => item.system === row.system_code && item.language === row.language && (
    item.names.some(name => normalize(name) === normalize(row.set_name)) ||
    (item.codes || []).includes(row.set_id) ||
    (item.provider_ids?.[row.provider] || []).includes(row.set_id)
  )) || (row.system_code === "POKEMON_TCG" && row.provider === "TCGdex" &&
    Object.hasOwn(providerSets[row.language] || {}, row.set_id)
      ? providerSets[row.language][row.set_id] : null);
  return {game, set};
})();
