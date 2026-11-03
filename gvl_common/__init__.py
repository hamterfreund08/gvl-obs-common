"""Gemeinsame Teile von GVL Media Studio und GVL Regie.

Beide Programme packen diesen Ordner beim Bauen in ihre EXE und bleiben damit unabhaengig installierbar.
"""
import os

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT = os.path.join(ASSETS, "Montserrat.ttf")
LOGO = os.path.join(ASSETS, "gvl_logo.png")
