import copy
import json

import pytest

import ucp_gen.cli as cli

from .fixtures import BUNDLE


@pytest.fixture(autouse=True)
def offline_github(monkeypatch):
    def fake_fetch(owner, repo, number, token=None):
        assert (owner, repo, number) == ("acme", "rocket", 42)
        return copy.deepcopy(BUNDLE)

    monkeypatch.setattr(cli, "fetch_issue_bundle", fake_fetch)


def test_cli_writes_valid_json(tmp_path, capsys):
    out = tmp_path / "task.ucp.json"
    assert cli.main(["github", "acme/rocket#42", "-o", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["ucp_version"] == "0.1.0"
    assert "sources" in data
    assert "wrote" in capsys.readouterr().err


def test_cli_markdown_mode(capsys):
    assert cli.main(["github", "acme/rocket#42", "--markdown", "--token-budget", "600"]) == 0
    output = capsys.readouterr().out
    assert "Payment webhook drops events" in output
    assert "{" not in output.splitlines()[0]


def test_cli_rejects_bad_ref():
    with pytest.raises(SystemExit):
        cli.main(["github", "not-a-ref"])
