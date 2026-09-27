"""The slice of Spoolman's spool record that tag formats read.

Vendored rather than imported, because the point of this service is that it does
not depend on Spoolman's Python at all -- it reads a spool over the REST API and
hands it to a format. What it validates is therefore Spoolman's *published*
schema, which is a far more stable thing to depend on than its internals.

Two deliberate choices about strictness, both aimed at not breaking when
Spoolman changes:

  * Unknown fields are ignored, so a release that adds one is a non-event here.
  * Almost everything is optional. A format asking for a field nobody filled in
    should produce a note about a missing value, which the formats already do,
    rather than a validation error the user cannot act on.

So this model is a description of what can be read, not a contract about what
must be present. `id` is the only thing genuinely required, and only because a
spool without one cannot be written or linked.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Vendor(BaseModel):
    """The manufacturer, as the formats' "brand" field."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str = ""


class Filament(BaseModel):
    """What is on the spool. Nearly every value a format writes comes from here."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str = ""
    vendor: Vendor | None = None
    material: str = ""
    # Grams of filament on a full spool, and the weight of the empty spool.
    weight: float | None = None
    spool_weight: float | None = None
    density: float | None = None
    diameter: float | None = None
    color_hex: str | None = None
    # Comma-separated additional colours for a multi-colour filament.
    multi_color_hexes: str = ""
    settings_extruder_temp: int | None = None
    settings_bed_temp: int | None = None
    # Operator-defined fields. OpenSpool reads its overrides out of here, so it
    # has to survive the round trip untouched.
    extra: dict[str, str] = {}


class Spool(BaseModel):
    """One physical spool, as `GET /api/v1/spool/{id}` returns it."""

    model_config = ConfigDict(extra="ignore")

    id: int
    filament: Filament = Filament()
    # Per-spool tare override; falls back to the filament's when unset.
    spool_weight: float | None = None
    archived: bool = False
    extra: dict[str, str] = {}
