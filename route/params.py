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
RANDOM_SPAWN_P = 0.55          # SOURCED range 50-60% for non-guaranteed chests (older seasons)
EXPECTED_CHESTS_PER_SPOT = GUARANTEED_SHARE + (1 - GUARANTEED_SHARE) * RANDOM_SPAWN_P  # ~0.67

# --- Drop and storm (all GUESS: nothing published for Crossbones Isle) -------
BUS_SPEED = 30.0          # m/s along its straight path. GUESS (bus crosses the map in ~70 s)
FALL_BASE_S = 28.0        # s from jumping to boots-on-ground when landing right under the bus. GUESS
GLIDE_SPEED = 18.0        # m/s of sideways travel while skydiving/gliding; each extra 18 m costs 1 s. GUESS
MAX_DROP_REACH_M = 900.0  # furthest you can land from the bus line. GUESS
STORM1_CLOSES_S = 210.0   # game clock (bus at map edge = 0) when the first storm starts moving. GUESS
