"""Binding tag UIDs to spools, and refusing to do it when that would be wrong.

Two hazards shape this module.

**Extra-field values are JSON-encoded strings.** A text field holding
``04BB1457D32A81`` is stored as ``'"04BB1457D32A81"'``, quotes included, and an
integer ``-1`` is stored as ``'-1'``. Getting that wrong writes garbage
silently, so nothing outside this module encodes or decodes one.

**Duplicate UIDs are the expected case, not a remote risk.** The tags in use
share a five-byte factory suffix and vary in a single byte, so the usable UID
space is 256 values. Across 76 spools that predicts around eleven colliding
pairs, and a collision would silently bind the wrong spool to a printer
channel. Every bind is therefore checked first, and a taken UID is refused.

``card_uids`` is a comma-separated list and is appended to, never replaced:
SpoolLink and Happy Hare write the same records, and ``printer_name`` and
``mmu_gate_map`` belong to them and are never touched here.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.database import spool as spool_db
from spoolman.nfc.identifiers import normalise_uid

logger = logging.getLogger(__name__)

CARD_UID_FIELD = "card_uids"


class UidAlreadyBoundError(Exception):
    """The UID is already bound to a different spool."""

    def __init__(self, uid: str, owner_id: int, owner_name: str) -> None:
        """Record which spool holds the UID.

        Args:
            uid: The UID that is taken.
            owner_id: The spool holding it.
            owner_name: Something the user will recognise that spool by.

        """
        super().__init__(f"Tag {uid} is already bound to {owner_name} (spool {owner_id}).")
        self.uid = uid
        self.owner_id = owner_id
        self.owner_name = owner_name


def decode_value(raw: Any) -> Any:  # noqa: ANN401 - extra fields hold any JSON value
    """Decode one stored extra-field value.

    Args:
        raw: The stored string, or an already-decoded value.

    Returns:
        Any: The decoded value. Text that was never encoded is returned as-is,
            since a field written by something else is still readable data.

    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def encode_value(value: Any) -> str:  # noqa: ANN401 - extra fields hold any JSON value
    """Encode one value for storage in an extra field.

    Args:
        value: The value to store.

    Returns:
        str: The JSON encoding, which is what the column holds.

    """
    return json.dumps(value)


def as_dict(extra: Any) -> dict[str, str]:  # noqa: ANN401 - accepts ORM rows or an API model's dict
    """Normalise a spool's extra fields to a plain mapping.

    Args:
        extra: Either the API model's dict or the ORM's list of field rows.

    Returns:
        dict[str, str]: Key to stored (still encoded) value.

    """
    if not extra:
        return {}
    if isinstance(extra, dict):
        return dict(extra)
    return {field.key: field.value for field in extra}


def parse_card_uids(extra: Any) -> list[str]:  # noqa: ANN401 - accepts ORM rows or an API model's dict
    """Read a spool's bound UIDs.

    Args:
        extra: The spool's extra fields.

    Returns:
        list[str]: Normalised UIDs, empty when none are bound.

    """
    raw = decode_value(as_dict(extra).get(CARD_UID_FIELD))
    if not raw:
        return []
    return [normalise_uid(part) for part in str(raw).split(",") if part.strip()]


def with_uid_added(extra: Any, uid: str) -> str:  # noqa: ANN401 - accepts ORM rows or an API model's dict
    """Build the field value that adds a UID to a spool's list.

    Idempotent: re-binding a UID the spool already holds is a no-op rather than
    a duplicate entry.

    Args:
        extra: The spool's current extra fields.
        uid: The UID to add.

    Returns:
        str: The encoded value to store.

    """
    uid = normalise_uid(uid)
    existing = parse_card_uids(extra)
    if uid not in existing:
        existing.append(uid)
    return encode_value(",".join(existing))


def with_uid_removed(extra: Any, uid: str) -> str:  # noqa: ANN401 - accepts ORM rows or an API model's dict
    """Build the field value that drops a UID from a spool's list.

    Args:
        extra: The spool's current extra fields.
        uid: The UID to remove.

    Returns:
        str: The encoded value to store.

    """
    uid = normalise_uid(uid)
    return encode_value(",".join(held for held in parse_card_uids(extra) if held != uid))


@dataclass(frozen=True)
class UidOwner:
    """Who currently holds a UID."""

    uid: str
    spool_id: int | None = None
    spool_name: str = ""
    archived: bool = False

    @property
    def is_free(self) -> bool:
        """Whether nothing holds this UID.

        Returns:
            bool: True when the UID can be bound to anything.

        """
        return self.spool_id is None


def _describe(spool: Any) -> str:  # noqa: ANN401 - an ORM spool row
    """Name a spool the way a user would recognise it.

    Args:
        spool: The spool row.

    Returns:
        str: The filament's name, falling back to the spool's id.

    """
    filament = getattr(spool, "filament", None)
    name = getattr(filament, "name", None) if filament else None
    return name or f"spool {spool.id}"


async def find_owner(db: AsyncSession, uid: str) -> UidOwner:
    """Find the spool a UID is bound to, archived spools included.

    Archived spools count: their tags have not necessarily been reused, and
    ignoring them would let the same UID be bound twice.

    Args:
        db: The database session.
        uid: The UID to look for.

    Returns:
        UidOwner: The holder, or a free result.

    """
    uid = normalise_uid(uid)
    spools, _ = await spool_db.find(db=db, allow_archived=True)
    for spool in spools:
        if uid in parse_card_uids(spool.extra):
            return UidOwner(
                uid=uid,
                spool_id=spool.id,
                spool_name=_describe(spool),
                archived=bool(spool.archived),
            )
    return UidOwner(uid=uid)


async def bind(db: AsyncSession, spool_id: int, uid: str) -> UidOwner:
    """Bind a UID to a spool, refusing if something else already holds it.

    Args:
        db: The database session.
        spool_id: The spool to bind to.
        uid: The UID read from the tag.

    Returns:
        UidOwner: The binding as it now stands.

    Raises:
        UidAlreadyBoundError: A different spool already holds this UID.

    """
    uid = normalise_uid(uid)
    owner = await find_owner(db, uid)
    if owner.spool_id is not None and owner.spool_id != spool_id:
        logger.warning("Refusing to bind %s to spool %d: held by spool %d", uid, spool_id, owner.spool_id)
        raise UidAlreadyBoundError(uid, owner.spool_id, owner.spool_name)

    spool = await spool_db.get_by_id(db, spool_id)
    await spool_db.update(db=db, spool_id=spool_id, data={"extra": {CARD_UID_FIELD: with_uid_added(spool.extra, uid)}})
    logger.info("Bound tag %s to spool %d", uid, spool_id)
    return UidOwner(uid=uid, spool_id=spool_id, spool_name=_describe(spool))


async def unbind(db: AsyncSession, spool_id: int, uid: str) -> list[str]:
    """Remove one UID from a spool, leaving any others alone.

    Args:
        db: The database session.
        spool_id: The spool to change.
        uid: The UID to remove.

    Returns:
        list[str]: The UIDs the spool still holds.

    """
    uid = normalise_uid(uid)
    spool = await spool_db.get_by_id(db, spool_id)
    await spool_db.update(
        db=db,
        spool_id=spool_id,
        data={"extra": {CARD_UID_FIELD: with_uid_removed(spool.extra, uid)}},
    )
    logger.info("Unbound tag %s from spool %d", uid, spool_id)
    return [held for held in parse_card_uids(spool.extra) if held != uid]
