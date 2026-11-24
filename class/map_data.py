"""Crossbones Isle sample for the November 2026 Treasure Hunters season.

Location names come from the linked Battle Royale map. AI selected the
connections and estimated their travel times for this assignment. Chest
counts are scenario assumptions and can differ from actual spawns.
"""

MAP_URL = "https://fndb.gg/map/"
START = "Lantern Landing"
LOOT_STOPS = ("Loguetown", "Plunder Port", "Busy Bay", "Cursed Cavern")
CHESTS_PER_STOP = 5

LOCATIONS = (
    START,
    "Rubber Resort",
    "Plunder Port",
    "The Chest",
    "Arlong Park",
    "Windmill Village",
    "The $.$. Rocky",
    "Busy Bay",
    "Cursed Cavern",
    "Buggy's Beachhead",
    "Loguetown",
)

# Each tuple is a two-way modeled connection with a travel time in seconds.
ROUTES = (
    ("Lantern Landing", "Loguetown", 85),
    ("Lantern Landing", "Windmill Village", 25),
    ("Windmill Village", "Loguetown", 35),
    ("Windmill Village", "Arlong Park", 30),
    ("Arlong Park", "Rubber Resort", 36),
    ("Rubber Resort", "The Chest", 22),
    ("The Chest", "Buggy's Beachhead", 41),
    ("Buggy's Beachhead", "Lantern Landing", 37),
    ("Loguetown", "Plunder Port", 24),
    ("Plunder Port", "Busy Bay", 34),
    ("Loguetown", "Busy Bay", 50),
    ("Busy Bay", "Cursed Cavern", 43),
    ("Busy Bay", "The $.$. Rocky", 19),
    ("The $.$. Rocky", "Cursed Cavern", 16),
    ("Lantern Landing", "Cursed Cavern", 62),
)
