"""The host power actions.

These hold a line that matters more than most: the endpoint must never be able
to run anything other than the two commands the sudoers drop-in grants. So the
argv is asserted rather than the outcome, and nothing here is allowed to reach
a real subprocess -- a test that actually rebooted the build machine would be
an unusually memorable failure.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from nfcwriter import config, power, server

SUDO = "/usr/bin/sudo"
SYSTEMCTL = "/usr/bin/systemctl"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Build a client with the lifespan run, but no hardware touched."""
    monkeypatch.setattr(server.service, "start", lambda: None)
    monkeypatch.setattr(server.service, "stop", lambda: None)
    monkeypatch.setattr(config, "KEEPALIVE_INTERVAL", 2.0)
    with TestClient(server.app) as c:
        yield c


@pytest.fixture
def ran(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture every argv the module would hand to a subprocess.

    Both executables are pinned so the assertions do not depend on where sudo
    and systemctl happen to live on the machine running the tests.
    """
    calls: list[list[str]] = []

    def popen(argv: list[str], *_a: object, **_k: object) -> None:
        calls.append(list(argv))

    monkeypatch.setattr(power.subprocess, "Popen", popen)
    monkeypatch.setattr(power, "GRACE_SECONDS", 0.0)
    monkeypatch.setattr(power, "_sudo", lambda: SUDO)
    monkeypatch.setattr(power, "_systemctl", lambda: SYSTEMCTL)
    return calls


@pytest.fixture
def allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report every action as permitted, without asking sudo."""
    monkeypatch.setattr(power, "permitted", lambda _action: True)


class TestPermitted:
    """Asking sudo whether an action is allowed, without performing it."""

    def test_asks_sudo_and_runs_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The permission probe lists the rule; it must not run the command."""
        seen: list[list[str]] = []

        class Result:
            returncode = 0

        def run(argv: list[str], **_k: object) -> Result:
            seen.append(list(argv))
            return Result()

        monkeypatch.setattr(power.subprocess, "run", run)
        monkeypatch.setattr(power, "_sudo", lambda: SUDO)
        monkeypatch.setattr(power, "_systemctl", lambda: SYSTEMCTL)
        assert power.permitted("reboot") is True
        # -l lists the permission; without it this would reboot the machine.
        assert seen == [[SUDO, "-n", "-l", SYSTEMCTL, "reboot"]]

    def test_a_refusal_is_not_permission(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-zero exit from sudo means no, not maybe."""

        class Result:
            returncode = 1

        monkeypatch.setattr(power.subprocess, "run", lambda *_a, **_k: Result())
        assert power.permitted("reboot") is False

    def test_sudo_missing_is_not_permission(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A host without sudo reports the action unavailable rather than raising."""

        def boom(*_a: object, **_k: object) -> None:
            raise OSError("no sudo here")

        monkeypatch.setattr(power.subprocess, "run", boom)
        assert power.permitted("reboot") is False

    def test_an_unknown_action_is_never_permitted(self) -> None:
        """Only the two names in ACTIONS exist; the verbs themselves are not names."""
        assert power.permitted("poweroff") is False
        assert power.permitted("stop nginx") is False


class TestAvailable:
    """What the endpoint reports it will accept, so a GUI can hide the rest."""

    def test_disabled_offers_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """NFCW_POWER=0 refuses everything regardless of what sudo allows."""
        monkeypatch.setattr(config, "POWER_ENABLED", False)
        assert power.available() == {"reboot": False, "shutdown": False}

    def test_reports_what_sudo_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A half-installed drop-in offers only the action it actually granted."""
        monkeypatch.setattr(config, "POWER_ENABLED", True)
        monkeypatch.setattr(power, "permitted", lambda action: action == "reboot")
        assert power.available() == {"reboot": True, "shutdown": False}


class TestTrigger:
    """Running the action, once the caller has been answered."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("action", "verb"), [("reboot", "reboot"), ("shutdown", "poweroff")])
    async def test_runs_exactly_the_granted_command(
        self,
        ran: list[list[str]],
        action: str,
        verb: str,
    ) -> None:
        """Each action maps to one fixed argv and nothing a caller can influence."""
        await power.trigger(action)
        assert ran == [[SUDO, "-n", SYSTEMCTL, verb]]

    @pytest.mark.asyncio
    async def test_a_failure_to_launch_is_logged_not_raised(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """By now the caller has its 200 and may be gone, so the log is all there is."""

        def boom(*_a: object, **_k: object) -> None:
            raise OSError("denied")

        monkeypatch.setattr(power.subprocess, "Popen", boom)
        monkeypatch.setattr(power, "GRACE_SECONDS", 0.0)
        with caplog.at_level("ERROR"):
            await power.trigger("reboot")
        assert "failed to run" in caplog.text


class TestEndpoint:
    """The HTTP surface, including what it refuses."""

    def test_lists_the_actions(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """GET /power is what lets the GUI decide whether to show the section."""
        monkeypatch.setattr(config, "POWER_ENABLED", True)
        monkeypatch.setattr(power, "permitted", lambda _a: True)
        assert client.get("/power").json() == {"reboot": True, "shutdown": True}

    def test_an_unknown_action_is_a_404(self, client: TestClient, ran: list[list[str]]) -> None:
        """The closed mapping is checked before privilege, so nothing else can run."""
        assert client.post("/power/stop").status_code == 404
        assert ran == []

    def test_disabled_refuses(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        ran: list[list[str]],
    ) -> None:
        """NFCW_POWER=0 refuses even where the sudoers drop-in is installed."""
        monkeypatch.setattr(config, "POWER_ENABLED", False)
        assert client.post("/power/reboot").status_code == 403
        assert ran == []

    def test_without_the_sudoers_drop_in_it_refuses_and_says_so(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        ran: list[list[str]],
    ) -> None:
        """The refusal names the fix, because the cause is not guessable from a 403."""
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
        """The response goes out before the machine does, so the button does not look broken."""
        monkeypatch.setattr(config, "POWER_ENABLED", True)
        monkeypatch.setattr(power, "permitted", lambda _a: True)
        response = client.post(f"/power/{action}")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        # TestClient runs background tasks before returning, so by here the
        # response had already been produced and the command has now run.
        assert ran == [[SUDO, "-n", SYSTEMCTL, verb]]
