"""Game Lab: three game-work plugins in one entry (ModLab, Game Localization Studio, Playtest Pilot).

Each part keeps its own module layout under parts/ and registers exactly what the stand-alone plugin did.
"""
from .parts import localization, modlab, playtest

PARTS = (modlab, localization, playtest)


def register(ctx):
    for part in PARTS:
        part.register(ctx)
