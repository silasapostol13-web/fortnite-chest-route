# Research: the numbers behind the model

Checked 2026-11-24. Every number lives in `route/params.py`. **SOURCED** = someone published it.
**GUESS** = nothing official exists, so I picked a sensible value. Change it there and rerun.

## Chest data (sourced)

- 860 regular chest spawn spots on Crossbones Isle (v43.00, Treasure Hunters), one per map position,
  from the class project's `chest_spawns.csv`. Origin: Pirate Shop Planner's game-file data,
  https://fortnitepirateshoptoken.org/fortnite-chest-map/ (Nov 11, 2026). Coordinates are pixels on its
  1212 x 1298 map; the map image is 1400 x 1500 (same picture, 1.155x).
- Guides count 901 chest spawn points on the island, **243 guaranteed**
  ([ofzenandcomputing](https://www.ofzenandcomputing.com/all-fortnite-treasure-hunt-chest-locations-and-free-rewards/),
  [games.gg](https://games.gg/fortnite/guides/fortnite-all-pirate-treasure-chest-locations/)). The CSV doesn't
  say which spots are guaranteed, so every spot counts the same.
- Non-guaranteed chests spawn about **50-60%** of the time (numbers from older seasons:
  [Fortnite wiki](https://fortnite.fandom.com/wiki/Chest), VideoGamer). So one spawn spot is worth about
  0.27 + 0.73 x 0.55 = **0.67 real chests** on average. A route through 38 spots means about 26 chests.
- Update 2026-11-28: Chapter 7 reports put it at 60% ([VideoGamer](https://www.videogamer.com/news/fortnite-chest-spawn-buff-delivers-a-major-loot-upgrade/),
  hotfix, no Epic note) and "reportedly" 67% from Ch7 S3 ([GameRiv](https://gameriv.com/fortnite-chapter-7-season-3-balance-update-all-nerfs-buffs-and-changes/),
  2026-06-07). None is Treasure Hunters-specific; `params.py` now uses 0.60. No source gives a spawn chance for
  buried / dig spots; 0.5 is a guess. The live planner now weights each spot by these (see `scripts/steering/README.md`).

## Movement

| Number | Value | Status | Source |
|---|---|---|---|
| Jog speed | 5.5 m/s | sourced (community) | [progameguides](https://progameguides.com/fortnite/how-to-run-faster-in-fortnite/) |
| Sprint | 6.47 m/s | sourced (community, unverified) | same search; no Epic figure |
| Speed used | 6.0 m/s | guess between the two | mostly sprinting, some stops for doors/stairs |
| Swim | 3.6 m/s | sourced, low authority | [cyberpost](https://cyberpost.co/?p=132538) |
| Chest open | 0.4 s | sourced | [Epic dev forum](https://forums.unrealengine.com/t/legendary-tier-6-chests-and-custom-chests-take-around-3-5-seconds-to-open-instead-of-the-usual-0-4-seconds/1902141) |
| Time per chest stop | 2.0 s | **guess** | 0.4 s open + grabbing loot and turning around |
| Map scale | 1.7 m per map pixel | **guess** | Epic never publishes map size; puts the island ~1.5 km across and a full crossing at ~5 min, which matches play |

Land vs water comes from the map image itself: deep-blue pixels are water (swim), everything else is
land (run). Shallows count as land. Buildings, cliffs and stairs are not modelled; real routes take a
bit longer.

## Battle bus and storm (all guesses)

Nothing published for Crossbones Isle (80-player lobbies, smaller map:
[esports.gg](https://esports.gg/news/fortnite/fortnite-treasure-hunters-map/)). Storm timings changed several times in
Chapter 7 ([PCGamesN](https://www.pcgamesn.com/fortnite/more-storm-circle-timing-adjustments)), and no source gives
current numbers. Glide/fall speeds aren't published either (Epic's
[glide component docs](https://dev.epicgames.com/documentation/fortnite/verse-api/fortnitedotcom/characters/fort_glide_component)
name the settings but not the values).

| Number | Value |
|---|---|
| Bus speed | 30 m/s (crosses the map in ~70 s) |
| Jump to ground, straight down | 28 s |
| Sideways glide | 18 m/s (each extra 18 m from the bus line costs 1 s) |
| Max distance from bus line | 900 m |
| First storm starts closing | 210 s after the bus starts its path |

Because these are guesses, `run.py land --seconds N` also answers the storm-free question: "best spot if
I get exactly N seconds on the ground".

## Things the model ignores

Other players, floor loot, ammo boxes, rare/vault chests, which circle you get, vehicles and
movement items, the second floor of buildings, and that a chest you planned for might not spawn
(the route doesn't re-plan mid-game).

## Hook worth knowing

Treasure Hunters chests can drop the **Pirate Shop Token** (free item shop for 14 days), and players are
already mapping "fastest chest routes" to farm it
([GamesRadar](https://www.gamesradar.com/games/fortnite/fortnite-players-desperate-for-free-skins-have-mapped-out-the-fastest-routes-to-grind-for-the-pirate-shop-token-because-yes-it-really-is-that-serious/)).
That's the viewer's reason to care. The token odds aren't published (one estimate: 1 in 700,000), so
the video shouldn't promise a token.

## Pass 2 additions

- **Token odds:** Epic confirmed **1 in 137,500 per chest** on Nov 7, 2026, boosted ~1.5x in Saturday
  Treasure Hours ([VGC](https://www.videogameschronicle.com/news/fortnite-officially-confirms-pirate-shop-access-token-drop-rate-as-players-hunt-for-item-which-makes-entire-shop-free/),
  [Kotaku](https://kotaku.com/fortnite-bullied-into-divulging-the-drop-rate-of-the-pirate-shop-token-2000755124),
  [playnews](https://www.playnews.gg/en/news/fortnite-pirate-shop-access-odds-1-in-137-500-per-chest-2x-in-treasure-hours)).
  No chest count, no time limit; teammates share it in squads. Sources disagree on whether every chest
  type counts. None limit it to special chests, and one says breaking a chest counts too.
- **Map scale, still unsettled:** the only measurements found are an older map's 250 m grid squares
  ([Game Rant](https://gamerant.com/fortnite-map-diagram-distance/)) and a 1,836 m run across a
  2026 map in 5:39 ([pulse.bot](https://www.pulse.bot/gaming/news/for-science-i-raced-across-1836-metres-in-fortnite-at-half-of-usain-bolts-top-speed-885d064a-88cd-423b-9356-974ae7211add/)).
  It isn't clear whether that run spanned the island or the full map square. Crossbones Isle is built for
  80 players instead of 100, so it's about √0.8 ≈ 0.9x as wide, which gives 1.35-1.8 m/px. 1.7 sits in
  that range. Because scale only multiplies every travel time, the robustness check (±20%) covers it,
  and his real splits will pin it down (`--calibrate`).
- **Buildings and cliffs:** not modelled separately. The calibration's travel factor absorbs the average
  slowdown. A proper per-cell slowdown would need building outlines the map image doesn't separate cleanly.
