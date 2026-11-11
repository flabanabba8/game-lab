"""Game Lab: four game-work parts in one entry (ModLab, Game Localization Studio, Playtest Pilot, Sprites).

Each part keeps its own module layout under parts/ and registers exactly what the stand-alone plugin did.
"""
from .parts import localization, modlab, playtest, sprites

PARTS = (modlab, localization, playtest, sprites)


def register(ctx):
    for part in PARTS:
        part.register(ctx)
