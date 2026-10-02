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
  const normalize = value => String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
  const game = system => data.games[system] || null;
  const set = row => data.sets.find(item => item.system === row.system_code && item.language === row.language && (
    item.names.some(name => normalize(name) === normalize(row.set_name)) ||
    (item.codes || []).includes(row.set_id) ||
    (item.provider_ids?.[row.provider] || []).includes(row.set_id)
  )) || null;
  return {game, set};
})();
