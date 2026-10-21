"""End-to-end: real CLI against a local HTTP server that mimics the four registries."""

import json
import subprocess
from pathlib import Path

import pytest

from steep.cli import main
from steep.http import Fetcher, FetchError, check_url

PACKAGE_LOCK = {
    "lockfileVersion": 3,
    "packages": {
        "node_modules/evil-pkg": {
            "version": "1.1.0",
            "resolved": "https://registry.npmjs.org/evil-pkg/-/e.tgz",
        },
        "node_modules/@scope/old": {
            "version": "2.0.0",
            "resolved": "https://registry.npmjs.org/@scope/old/-/o.tgz",
        },
    },
}


def run(capsys, *args: str):
    code = main(["--no-cache", *args])
    return code, capsys.readouterr()


def test_npm_findings_json(registry_env, tmp_path: Path, capsys):
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps(PACKAGE_LOCK))
    code, out = run(capsys, "--format", "json", str(lock))
    data = json.loads(out.out)
    found = {(f["package"], f["rule"]) for f in data["findings"]}
    assert ("npm:evil-pkg@1.1.0", "provenance-regression") in found
    assert ("npm:@scope/old@2.0.0", "deprecated") in found
    assert code == 1


def test_pypi_litellm_style_regression(registry_env, tmp_path: Path, capsys):
    f = tmp_path / "requirements.txt"
    f.write_text("litellm_like==1.107.0\nlitellm_like==1.106.2\n")
    code, out = run(capsys, "--format", "json", "--min-age-days", "3650", str(f))
    findings = json.loads(out.out)["findings"]
    bad = [
        x
        for x in findings
        if x["package"].endswith("1.107.0") and x["rule"] == "provenance-regression"
    ]
    assert bad
    assert not [
        x
        for x in findings
        if x["package"].endswith("1.106.2") and x["rule"] == "provenance-regression"
    ]
    assert code == 1


def test_crates_yanked_and_go_age(registry_env, tmp_path: Path, capsys):
    cargo = tmp_path / "Cargo.lock"
    cargo.write_text(
        '[[package]]\nname = "serde-ish"\nversion = "1.0.1"\n'
        'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
    )
    code, out = run(capsys, "--format", "json", str(cargo))
    assert [f["rule"] for f in json.loads(out.out)["findings"]] == ["yanked"]
    assert code == 1

    gosum = tmp_path / "go.sum"
    gosum.write_text("github.com/BurntSushi/toml v1.4.0 h1:abc=\n")
    # Go release is hours old relative to wall clock only if "now" matches; use huge window.
    code, out = run(capsys, "--format", "json", "--min-age-days", "100000", str(gosum))
    assert [f["rule"] for f in json.loads(out.out)["findings"]] == ["too-new"]


def test_unknown_version_is_low_and_does_not_fail(registry_env, tmp_path: Path, capsys):
    f = tmp_path / "requirements.txt"
    f.write_text("litellm_like==9.9.9\n")
    code, out = run(capsys, str(f))
    assert "not-found" in out.out
    assert code == 0


def test_lookup_failure_reported_not_fatal(registry_env, tmp_path: Path, capsys):
    f = tmp_path / "Cargo.lock"
    f.write_text(
        '[[package]]\nname = "ghost"\nversion = "1.0.0"\n'
        'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
    )
    code, out = run(capsys, str(f))
    assert "lookup-failed" in out.out and code == 0


def test_allow_and_fail_on_never(registry_env, tmp_path: Path, capsys):
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps(PACKAGE_LOCK))
    code, out = run(capsys, "--allow", "npm:evil-pkg", "--allow", "npm:@scope/old", str(lock))
    assert code == 0 and "checked 0" in out.out
    code, _ = run(capsys, "--fail-on", "never", str(lock))
    assert code == 0


def test_markdown_output(registry_env, tmp_path: Path, capsys):
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps(PACKAGE_LOCK))
    _, out = run(capsys, "--format", "markdown", str(lock))
    assert out.out.startswith("### steep:") and "| high |" in out.out


def test_config_file_and_errors(registry_env, tmp_path: Path, capsys):
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps(PACKAGE_LOCK))
    cfg = tmp_path / "steep.toml"
    cfg.write_text('fail_on = "never"\nallow = ["npm:evil-pkg"]\n')
    code, out = run(capsys, "--config", str(cfg), str(lock))
    assert code == 0 and "evil-pkg" not in out.out
    cfg.write_text("bogus = 1\n")
    code, out = run(capsys, "--config", str(cfg), str(lock))
    assert code == 2 and "unknown keys" in out.err
    code, out = run(capsys, "--config", str(tmp_path / "missing.toml"), str(lock))
    assert code == 2


def test_usage_errors(tmp_path: Path, capsys):
    code, out = run(capsys, str(tmp_path))
    assert code == 2 and "no supported lockfiles" in out.err
    code, out = run(capsys, str(tmp_path / "nope.lock"))
    assert code == 2
    bad = tmp_path / "package-lock.json"
    bad.write_text("{")
    code, out = run(capsys, str(bad))
    assert code == 2 and "invalid JSON" in out.err
    code, _ = run(capsys, "--min-age-days", "-1", str(bad))
    assert code == 2


def test_cache_and_offline(registry_env, tmp_path: Path, capsys):
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps(PACKAGE_LOCK))
    cache = tmp_path / "cache"
    assert main(["--cache-dir", str(cache), "--format", "json", str(lock)]) == 1
    capsys.readouterr()
    assert any(cache.iterdir())
    # Offline run succeeds purely from cache and gives the same verdict.
    assert main(["--cache-dir", str(cache), "--offline", "--format", "json", str(lock)]) == 1
    # Offline with an empty cache degrades to lookup-failed findings, not a crash.
    code = main(["--cache-dir", str(tmp_path / "empty"), "--offline", str(lock)])
    assert code == 0
    assert "lookup-failed" in capsys.readouterr().out


def test_base_ref_only_checks_new_versions(registry_env, tmp_path: Path, capsys, monkeypatch):
    def git(*a: str):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    lock = tmp_path / "package-lock.json"
    old = {
        "lockfileVersion": 3,
        "packages": {
            "node_modules/@scope/old": PACKAGE_LOCK["packages"]["node_modules/@scope/old"]
        },
    }
    lock.write_text(json.dumps(old))
    git("add", ".")
    git("commit", "-qm", "base")
    lock.write_text(json.dumps(PACKAGE_LOCK))  # adds evil-pkg only
    code, out = run(capsys, "--base", "HEAD", "--format", "json", str(lock))
    names = {f["package"] for f in json.loads(out.out)["findings"]}
    assert names == {"npm:evil-pkg@1.1.0"}
    # a lockfile that is new on this branch has every package checked
    (tmp_path / "requirements.txt").write_text("litellm_like==1.107.0\n")
    code, out = run(
        capsys, "--base", "HEAD", "--format", "json", str(tmp_path / "requirements.txt")
    )
    assert any(f["rule"] == "provenance-regression" for f in json.loads(out.out)["findings"])
    code, out = run(capsys, "--base", "no-such-ref", str(lock))
    assert code == 2


def test_refuses_plain_http_to_remote_host():
    with pytest.raises(FetchError):
        check_url("http://registry.example.com/x")
    assert check_url("https://registry.npmjs.org/x")
    assert check_url("http://127.0.0.1:1/x")
    with pytest.raises(FetchError):
        Fetcher().get_json("file:///etc/passwd")
