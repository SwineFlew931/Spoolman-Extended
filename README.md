# Spoolman Extended

**An unofficial fork of [Spoolman](https://github.com/Donkie/Spoolman) by Donkie.**
Not affiliated with or endorsed by the Spoolman project.

Spoolman Extended adds NFC tag reading and writing to Spoolman. Nothing else is
changed: the inventory, the API, the label designer and the web client all work
exactly as they do upstream, and everything below this notice is Spoolman's own
documentation, unedited.

| | |
|---|---|
| **Upstream** | https://github.com/Donkie/Spoolman — report Spoolman bugs there, not here |
| **Base version** | v0.26.1 (`f387203`). Fork versions mirror it as `0.26.1+ext.N`, so the base is always visible |
| **Status** | In development |

### What this fork adds

- Read and write NFC tags from within Spoolman, using a PN532 reader.
- A choice of tag formats on write — OpenTag3D, OpenSpool, nfc2klipper and
  UID-only bindings, with the compatible NTAG chips computed from the actual
  payload rather than guessed.
- Tag writing folded into the existing "add spool" flow, so a new spool can be
  created and tagged in one pass.
- Tapping a tag that Spoolman already knows about takes you to its spool.

The reader is driven by a small separate daemon (`nfcd/`), so an installation
without NFC hardware runs exactly like upstream Spoolman and needs none of its
dependencies.

### Optional extras

- [`integrations/snapmaker-u1/`](integrations/snapmaker-u1/) — keeps a Snapmaker
  U1's per-channel spool state mirrored into Spoolman's `Location` field, and
  works around a stall in SpoolLink's own tag resolution. A separate service
  that nothing else depends on; skip it if you have no U1.

### License and credit

Spoolman is MIT licensed, © 2023 Daniel Hultgren. `LICENSE` is unchanged and
applies to all of it. Additions made in this fork are © 2026 SwineFlew931 and
released under the same MIT license.

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://github.com/Donkie/Spoolman/assets/2332094/4e6e80ac-c7be-4ad2-9a33-dedc1b5ba30e">
  <source media="(prefers-color-scheme: light)" srcset="https://github.com/Donkie/Spoolman/assets/2332094/3c120b3a-1422-42f6-a16b-8d5a07c33000">
  <img alt="Icon of a filament spool" src="https://github.com/Donkie/Spoolman/assets/2332094/3c120b3a-1422-42f6-a16b-8d5a07c33000">
</picture>

<br/>

_Keep track of your inventory of 3D-printer filament spools._

Spoolman is a self-hosted web service designed to help you efficiently manage your 3D printer filament spools and monitor their usage. It acts as a centralized database that seamlessly integrates with popular 3D printing software like [OctoPrint](https://octoprint.org/) and [Klipper](https://www.klipper3d.org/)/[Moonraker](https://moonraker.readthedocs.io/en/latest/). When connected, it automatically updates spool weights as printing progresses, giving you real-time insights into filament usage.

[![Static Badge](https://img.shields.io/badge/Spoolman%20Wiki-blue?link=https%3A%2F%2Fgithub.com%2FDonkie%2FSpoolman%2Fwiki)](https://github.com/Donkie/Spoolman/wiki)
[![GitHub Release](https://img.shields.io/github/v/release/Donkie/Spoolman)](https://github.com/Donkie/Spoolman/releases)

### Features
* **Filament Management**: Keep comprehensive records of filament types, manufacturers, and individual spools.
* **API Integration**: The [REST API](https://donkie.github.io/Spoolman/) allows easy integration with other software, facilitating automated workflows and data exchange.
* **Real-Time Updates**: Stay informed with live spool updates through Websockets, providing immediate feedback during printing operations.
* **Central Filament Database**: A community-supported database of manufacturers and filaments simplify adding new spools to your inventory. Contribute by heading to [SpoolmanDB](https://github.com/Donkie/SpoolmanDB).
* **Web-Based Client**: Spoolman includes a built-in web client that lets you manage data effortlessly:
  * View, create, edit, and delete filament data.
  * Search, group and filter your inventory by manufacturer, material, location and more.
  * Add custom fields to tailor information to your specific needs.
  * Design and print labels with QR codes for easy spool identification and tracking.
  * Contribute to its translation into 18 languages via [Weblate](https://hosted.weblate.org/projects/spoolman/).
* **Database Support**: SQLite, PostgreSQL, MySQL, and CockroachDB.
* **Multi-Printer Management**: Handles spool updates from several printers simultaneously.
* **Advanced Monitoring**: Integrate with [Prometheus](https://prometheus.io/) for detailed historical analysis of filament usage, helping you track and optimize your printing processes. See the [Wiki](https://github.com/Donkie/Spoolman/wiki/Filament-Usage-History) for instructions on how to set it up.

**Spoolman integrates with:**
  * [Moonraker](https://moonraker.readthedocs.io/en/latest/configuration/#spoolman) and most front-ends (Fluidd, KlipperScreen, Mainsail, ...)
  * [OctoPrint](https://github.com/mdziekon/octoprint-spoolman)
  * [OctoEverywhere](https://octoeverywhere.com/spoolman?source=github_spoolman)
  * [Home Assistant](https://github.com/Disane87/spoolman-homeassistant)
  * [MCP Server](https://github.com/Disane87/spoolman-mcp) - Manage your filament inventory through AI assistants like Claude using the Model Context Protocol

**Web client preview:**
![The Spoolman web client, showing the spool library with a spool's details open alongside it](.github/media/client-screenshot.png)

<table>
  <tr>
    <td width="50%"><img alt="The Spoolman dashboard, showing spools as draggable cards grouped by storage location" src=".github/media/dashboard-screenshot.png"></td>
    <td width="50%"><img alt="The Spoolman label designer, showing a 50 by 25 mm spool label with a QR code, filament name and colour swatch" src=".github/media/label-designer-screenshot.png"></td>
  </tr>
  <tr>
    <td align="center"><sub>Dashboard — spools as cards, grouped by location or any other field. Drag one to move it.</sub></td>
    <td align="center"><sub>Label designer — QR labels built from any spool, filament or vendor field.</sub></td>
  </tr>
</table>

## Installation
Please see the [Installation page on the Wiki](https://github.com/Donkie/Spoolman/wiki/Installation) for details how to install Spoolman.

If the new client misbehaves on your setup, set `SPOOLMAN_LEGACY_CLIENT=TRUE` to go back to
the previous one. Both ship in every release and talk to the same API, so your data is
untouched either way — but please [report the problem](https://github.com/Donkie/Spoolman/issues)
so it can be fixed.
