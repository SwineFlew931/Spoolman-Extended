"""Tests for the parts that write to Spoolman.

The reconcile runs against a live inventory, so its pruning rules are the thing
most worth pinning down: a wrong removal loses a binding the operator made by
hand, and a missing one leaves the printer resolving a card to the wrong spool.
"""

import json

import pytest

import spoollink_location_sync as sync


@pytest.fixture(autouse=True)
def _clear_state():
    sync._unknown_uid_warned.clear()
    sync._spoolman_uid_cache.clear()
    sync._spoolman_uid_fetched_at = 0.0


@pytest.fixture
def patches(monkeypatch):
    """Capture what the reconcile would write instead of writing it."""
    calls = []
    monkeypatch.setattr(sync, "patch_spool_extra", lambda spool_id, extra: calls.append((spool_id, extra)))
    return calls


def spool(spool_id, tags=(), card_uids=None, archived=False):
    extra = {} if card_uids is None else {"card_uids": json.dumps(card_uids)}
    return {
        "id": spool_id,
        "archived": archived,
        "tags": [{"uid": uid} for uid in tags],
        "extra": extra,
    }


class TestFieldUids:
    """Custom field values arrive JSON-encoded, sometimes as a comma-joined list."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, []),
            ('""', []),
            ('"04411457D32A81"', ["04411457D32A81"]),
            ('"AAA,BBB"', ["AAA", "BBB"]),
            ('" aaa , bbb "', ["AAA", "BBB"]),
            ('"AAA,,BBB"', ["AAA", "BBB"]),
            ("04411457D32A81", ["04411457D32A81"]),  # not encoded at all
            ("123", []),  # decodes to a number, not a UID list
        ],
    )
    def test_parses(self, raw, expected):
        assert sync.field_uids(raw) == expected


class TestBuildUidMap:
    def test_tag_table_wins_over_the_legacy_field(self):
        spools = [spool(1, card_uids="AAA"), spool(2, tags=["AAA"])]
        assert sync.build_uid_map(spools)["AAA"] == 2

    def test_legacy_field_covers_what_the_tag_table_misses(self):
        spools = [spool(1, card_uids="AAA"), spool(2, tags=["BBB"])]
        assert sync.build_uid_map(spools) == {"AAA": 1, "BBB": 2}

    def test_a_spool_with_neither_is_absent(self):
        assert sync.build_uid_map([spool(1)]) == {}


class TestReconcile:
    def test_appends_a_tag_the_field_is_missing(self, patches):
        sync.reconcile_card_uids([spool(59, tags=["04821457D32A81"])])
        assert patches == [(59, {"card_uids": '"04821457D32A81"'})]

    def test_already_mirrored_writes_nothing(self, patches):
        sync.reconcile_card_uids([spool(105, tags=["AAA"], card_uids="AAA")])
        assert patches == []

    def test_appends_without_dropping_what_is_there(self, patches):
        sync.reconcile_card_uids([spool(7, tags=["BBB"], card_uids="AAA")])
        # AAA is claimed by no tag, so it stays; BBB joins it.
        assert patches == [(7, {"card_uids": '"AAA,BBB"'})]

    def test_drops_a_uid_the_tag_table_gives_to_another_spool(self, patches):
        spools = [spool(1, card_uids="AAA"), spool(2, tags=["AAA"], card_uids="AAA")]
        sync.reconcile_card_uids(spools)
        assert patches == [(1, {"card_uids": '""'})]

    def test_drops_a_freed_tag_from_an_archived_spool(self, patches):
        # archive-frees-tag removed the tag row; the mirror has to follow or the
        # printer keeps binding an archived spool.
        sync.reconcile_card_uids([spool(26, card_uids="AAA", archived=True)])
        assert patches == [(26, {"card_uids": '""'})]

    def test_keeps_an_unclaimed_uid_on_a_live_spool(self, patches):
        sync.reconcile_card_uids([spool(3, card_uids="AAA")])
        assert patches == []

    def test_warns_once_per_unclaimed_uid(self, patches, caplog):
        spools = [spool(3, card_uids="AAA")]
        with caplog.at_level("WARNING"):
            sync.reconcile_card_uids(spools)
            sync.reconcile_card_uids(spools)
        assert sum("no tag claims" in r.message for r in caplog.records) == 1

    def test_case_and_order_do_not_cause_a_write(self, patches):
        sync.reconcile_card_uids([spool(9, tags=["aaa"], card_uids="AAA")])
        assert patches == []


class TestDryRun:
    def test_no_request_is_made(self, monkeypatch):
        monkeypatch.setattr(sync, "DRY_RUN", True)
        monkeypatch.setattr(
            sync.requests,
            "patch",
            lambda *a, **k: pytest.fail("dry run must not reach the network"),
        )
        sync.patch_spool_extra(1, {"card_uids": '"AAA"'})
        sync.patch_spool(1, "Snapmaker U1 @ ch0")
