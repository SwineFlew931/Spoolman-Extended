"""The host power actions.

These hold a line that matters more than most: the endpoint must never be able
to run anything other than the two commands the sudoers drop-in grants. So the
argv is asserted rather than the outcome, and nothing here is allowed to reach
a real subprocess -- a test that actually rebooted the build machine would be
an unusually memorable failure.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nfcwriter import config, power, server


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(server.service, "start", lambda: None)
    monkeypatch.setattr(server.service, "stop", lambda: None)
    monkeypatch.setattr(config, "KEEPALIVE_INTERVAL", 2.0)
    with TestClient(server.app) as c:
        yield c


@pytest.fixture
def ran(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture every argv the module would hand to a subprocess."""
    calls: list[list[str]] = []

    def popen(argv: list[str], *_a: Any, **_k: Any) -> None:
        calls.append(list(argv))

    monkeypatch.setattr(power.subprocess, "Popen", popen)
    monkeypatch.setattr(power, "GRACE_SECONDS", 0.0)
    monkeypatch.setattr(power, "_systemctl", lambda: "/usr/bin/systemctl")
    return calls


@pytest.fixture
def allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(power, "permitted", lambda _action: True)


class TestPermitted:
    def test_asks_sudo_and_runs_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []

        class Result:
            returncode = 0

        def run(argv: list[str], **_k: Any) -> Result:
            seen.append(list(argv))
            return Result()

        monkeypatch.setattr(power.subprocess, "run", run)
        monkeypatch.setattr(power, "_systemctl", lambda: "/usr/bin/systemctl")
        assert power.permitted("reboot") is True
        # -l lists the permission; without it this would reboot the machine.
        assert seen == [["sudo", "-n", "-l", "/usr/bin/systemctl", "reboot"]]

    def test_a_refusal_is_not_permission(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Result:
            returncode = 1

        monkeypatch.setattr(power.subprocess, "run", lambda *_a, **_k: Result())
        assert power.permitted("reboot") is False

    def test_sudo_missing_is_not_permission(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_a: Any, **_k: Any) -> None:
            raise OSError("no sudo here")

        monkeypatch.setattr(power.subprocess, "run", boom)
        assert power.permitted("reboot") is False

    def test_an_unknown_action_is_never_permitted(self) -> None:
        assert power.permitted("poweroff") is False  # the verb, not the action name
        assert power.permitted("stop nginx") is False


class TestAvailable:
    def test_disabled_offers_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "POWER_ENABLED", False)
        assert power.available() == {"reboot": False, "shutdown": False}

    def test_reports_what_sudo_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "POWER_ENABLED", True)
        monkeypatch.setattr(power, "permitted", lambda action: action == "reboot")
        assert power.available() == {"reboot": True, "shutdown": False}


class TestTrigger:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("action", "verb"), [("reboot", "reboot"), ("shutdown", "poweroff")])
    async def test_runs_exactly_the_granted_command(
        self, ran: list[list[str]], action: str, verb: str
    ) -> None:
        await power.trigger(action)
        assert ran == [["sudo", "-n", "/usr/bin/systemctl", verb]]

    @pytest.mark.asyncio
    async def test_a_failure_to_launch_is_logged_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def boom(*_a: Any, **_k: Any) -> None:
            raise OSError("denied")

        monkeypatch.setattr(power.subprocess, "Popen", boom)
        monkeypatch.setattr(power, "GRACE_SECONDS", 0.0)
        with caplog.at_level("ERROR"):
            await power.trigger("reboot")
        assert "failed to run" in caplog.text


class TestEndpoint:
    def test_lists_the_actions(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "POWER_ENABLED", True)
        monkeypatch.setattr(power, "permitted", lambda _a: True)
        assert client.get("/power").json() == {"reboot": True, "shutdown": True}

    def test_an_unknown_action_is_a_404(self, client: TestClient, ran: list[list[str]]) -> None:
        assert client.post("/power/stop").status_code == 404
        assert ran == []

    def test_disabled_refuses(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, ran: list[list[str]]
    ) -> None:
        monkeypatch.setattr(config, "POWER_ENABLED", False)
        assert client.post("/power/reboot").status_code == 403
        assert ran == []

    def test_without_the_sudoers_drop_in_it_refuses_and_says_so(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, ran: list[list[str]]
    ) -> None:
        monkeypatch.setattr(config, "POWER_ENABLED", True)
        monkeypatch.setattr(power, "permitted", lambda _a: False)
        response = client.post("/power/reboot")
        assert response.status_code == 403
        assert "sudoers" in response.json()["detail"]
        assert ran == []

    @pytest.mark.parametrize(("action", "verb"), [("reboot", "reboot"), ("shutdown", "poweroff")])
    def test_a_permitted_action_answers_then_runs(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        ran: list[list[str]],
        action: str,
        verb: str,
    ) -> None:
        monkeypatch.setattr(config, "POWER_ENABLED", True)
        monkeypatch.setattr(power, "permitted", lambda _a: True)
        response = client.post(f"/power/{action}")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        # TestClient runs background tasks before returning, so by here the
        # response had already been produced and the command has now run.
        assert ran == [["sudo", "-n", "/usr/bin/systemctl", verb]]
