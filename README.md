# gvl-obs-common

Gemeinsamer Code von [GVL Media Studio](https://github.com/hamterfreund08/gvl-media-studio) und GVL Regie. Entwickelt von [hamterfreund08](https://github.com/hamterfreund08) für die German Virtual League.

Beide Programme binden dieses Repo als Submodul `gvl-obs-common` ein und packen es beim Bauen in ihre EXE. Allein ist es kein lauffähiges Programm.

| Datei | Inhalt |
|---|---|
| `gvl_common/tunnel.py`, `dns.py` | Cloudflare-Quick-Tunnel und Namensauflösung für frische Tunnel-Adressen |
| `gvl_common/service.py` | Schutz der Eingänge, Live-Kanal zum Dock |
| `gvl_common/roblox.py` | Wappen und Avatare über die Roblox-Thumbnail-API |
| `gvl_common/obs.py` | Docks und Skripte in OBS eintragen, OBS-Prozess erkennen |
| `gvl_common/module.py` | GVL Konferenz-Modul und Move Transition automatisch installieren |
| `gvl_common/updater.py`, `app.py`, `files.py` | Updates über GitHub, App-Fenster, Dateihelfer |
| `gvl_common/assets/` | Schrift Montserrat (SIL Open Font License 1.1) und GVL-Logo |

## Lizenz

Copyright (c) 2026 hamterfreund08. Alle Rechte vorbehalten. Montserrat steht unter der SIL Open Font License 1.1, siehe `gvl_common/assets/Montserrat-OFL.txt`.
