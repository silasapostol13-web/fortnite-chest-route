"""Every game number the model uses, in one place.

Tag on each line: SOURCED = a published number (see RESEARCH.md),
GUESS = my estimate because nothing official exists. Change them here and
everything else follows.
"""

# --- Map -------------------------------------------------------------------
MAP_LOGICAL_SIZE = (1212, 1298)   # SOURCED: coordinate space of the spawn data (class chest_data.py)
MAP_IMAGE_SIZE = (1400, 1500)     # measured from the downloaded map image
METERS_PER_PX = 1.7               # GUESS: Epic publishes no map size; ~2 km across the playable square
CELL_PX = 5                       # walk grid cell, in logical map pixels (~8.5 m). A modelling choice.

# --- Movement ---------------------------------------------------------------
RUN_SPEED = 6.0     # m/s. SOURCED range: jog 5.5, sprint 6.47 (community measurements). 6.0 = mostly sprinting.
SWIM_SPEED = 3.6    # m/s. SOURCED (one low-authority guide), treat as rough.
CHEST_STOP_S = 2.0  # s per chest: ~0.4 s open (SOURCED, Epic forum) + ~1.6 s to grab loot and turn (GUESS)

# --- Spawn odds -------------------------------------------------------------
GUARANTEED_SHARE = 243 / 901   # SOURCED: 901 spawn points, 243 guaranteed (Treasure Hunters guides)
# Chance a NON-guaranteed ("regular") chest spot has a chest this match. Checked 2026-11-28; Epic publishes no number,
# every figure below is a press/community report, none is specific to Treasure Hunters (v43.00, Crossbones Isle):
#   50%      Ch2 S4 v14.00 "reduced the spawn rate of Standard Chests to 50%"   https://fortnite.fandom.com/wiki/Chest
#   40-55% -> 60%  Chapter 7 hotfix (VideoGamer, ~Dec 2025, no Epic note cited)
#            https://www.videogamer.com/news/fortnite-chest-spawn-buff-delivers-a-major-loot-upgrade/
#   60% -> 67% "reportedly", Ch7 S3 balance update (GameRiv, 2026-06-07, unsourced)
#            https://gameriv.com/fortnite-chapter-7-season-3-balance-update-all-nerfs-buffs-and-changes/
# 0.60 = the lower Chapter 7 report (was 0.55 from older seasons). compare_planners.py spawn --regular-p checks 0.45-0.67.
RANDOM_SPAWN_P = 0.60
# Buried / dig spots: NO source gives a spawn chance (searched 2026-11-28; guides only count spots, 14 to 62 per map,
# e.g. https://www.igeeksblog.com/fortnite-treasure-hunters-buried-chest-locations/, 2026-11-13). GUESS: a coin flip,
# a bit below a regular chest, because a dig spot you can't see costs a detour to check.
BURIED_SPAWN_P = 0.5
# What the planner counts each spot as (expected chests). "guaranteed" / "guaranteed_rare" are the CSV's guaranteed
# spots (SOURCED as always spawning by the same guides as GUARANTEED_SHARE).
SPAWN_P = {"regular": RANDOM_SPAWN_P, "guaranteed": 1.0, "guaranteed_rare": 1.0, "buried": BURIED_SPAWN_P}
EXPECTED_CHESTS_PER_SPOT = GUARANTEED_SHARE + (1 - GUARANTEED_SHARE) * RANDOM_SPAWN_P  # ~0.71

# --- Drop and storm (all GUESS: nothing published for Crossbones Isle) -------
BUS_SPEED = 30.0          # m/s along its straight path. GUESS (bus crosses the map in ~70 s)
FALL_BASE_S = 28.0        # s from jumping to boots-on-ground when landing right under the bus. GUESS
GLIDE_SPEED = 18.0        # m/s of sideways travel while skydiving/gliding; each extra 18 m costs 1 s. GUESS
MAX_DROP_REACH_M = 900.0  # furthest you can land from the bus line. GUESS
STORM1_CLOSES_S = 210.0   # game clock (bus at map edge = 0) when the first storm starts moving. GUESS
