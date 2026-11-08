import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def diagnostic():
    path = Path(__file__).parents[1] / "tools/diagnose_auth.py"
    spec = importlib.util.spec_from_file_location("diagnose_auth", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_diagnostic_requires_explicit_flag_before_reading_options(diagnostic, monkeypatch):
    loader = Mock()
    monkeypatch.setattr(diagnostic, "load_options", loader)
    monkeypatch.setattr(diagnostic.sys, "argv", ["diagnose_auth.py", "--data-dir", "unused"])
    with pytest.raises(SystemExit) as exited:
        diagnostic.main()
    assert exited.value.code != 0
    loader.assert_not_called()


def test_entrypoint_never_runs_bridge_or_retries(diagnostic, monkeypatch):
    bridge = Mock()
    bridge.guard.state = {"reason": "auth_http_401"}
    bridge.diagnose_auth_once.side_effect = diagnostic.CloudError("auth_http_401")
    monkeypatch.setattr(diagnostic, "MyThermowattBridge", Mock(return_value=bridge))
    monkeypatch.setattr(
        diagnostic,
        "load_options",
        Mock(return_value={"commands_enabled": False, "cloud_enabled": True}),
    )
    monkeypatch.setattr(
        diagnostic.sys, "argv", ["diagnose_auth.py", "--allow-single-login", "--data-dir", "unused"]
    )
    assert diagnostic.main() == 1
    bridge.diagnose_auth_once.assert_called_once()
    bridge.run.assert_not_called()
    bridge.session.close.assert_called_once()


@pytest.mark.parametrize(
    "options", [{"cloud_enabled": False}, {"cloud_enabled": True, "commands_enabled": True}]
)
def test_diagnostic_refuses_unsafe_options_before_bridge_init(diagnostic, monkeypatch, options):
    bridge_class = Mock()
    monkeypatch.setattr(diagnostic, "MyThermowattBridge", bridge_class)
    monkeypatch.setattr(diagnostic, "load_options", Mock(return_value=options))
    monkeypatch.setattr(
        diagnostic.sys, "argv", ["diagnose_auth.py", "--allow-single-login", "--data-dir", "unused"]
    )
    assert diagnostic.main() == 1
    bridge_class.assert_not_called()
