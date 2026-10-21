import json
from pathlib import Path

import pytest

from steep.lockfiles import LockfileError, discover, parse_lockfile, parse_package_lock


def test_package_lock_v3_filters_non_registry_entries():
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "root", "version": "1.0.0"},
            "node_modules/a": {
                "version": "1.2.3",
                "resolved": "https://registry.npmjs.org/a/-/a-1.2.3.tgz",
            },
            "node_modules/a/node_modules/@s/b": {
                "version": "0.1.0",
                "resolved": "https://registry.npmjs.org/@s/b/-/b-0.1.0.tgz",
            },
            "node_modules/gitdep": {
                "version": "1.0.0",
                "resolved": "git+ssh://git@github.com/x/y.git",
            },
            "node_modules/linked": {"resolved": "../linked", "link": True},
            "node_modules/private": {
                "version": "1.0.0",
                "resolved": "https://npm.corp.example/p.tgz",
            },
        },
    }
    pkgs = parse_package_lock(json.dumps(lock), "package-lock.json")
    assert [(p.name, p.version) for p in pkgs] == [("@s/b", "0.1.0"), ("a", "1.2.3")]


def test_package_lock_v1_nested():
    lock = {
        "dependencies": {
            "a": {
                "version": "1.0.0",
                "resolved": "https://registry.npmjs.org/a/-/a-1.0.0.tgz",
                "dependencies": {
                    "b": {
                        "version": "2.0.0",
                        "resolved": "https://registry.npmjs.org/b/-/b-2.0.0.tgz",
                    }
                },
            }
        }
    }
    pkgs = parse_package_lock(json.dumps(lock), "package-lock.json")
    assert {(p.name, p.version) for p in pkgs} == {("a", "1.0.0"), ("b", "2.0.0")}


def test_invalid_json_raises():
    with pytest.raises(LockfileError):
        parse_package_lock("{nope", "package-lock.json")


def test_requirements_pins_only(tmp_path: Path):
    f = tmp_path / "requirements.txt"
    f.write_text(
        "# comment\nRequests[security]==2.31.0 ; python_version>'3'\n"
        "Foo_Bar==1.0 \\\n  --hash=sha256:abc\n"
        "loose>=1.0\n-r other.txt\ngit+https://x/y.git\nwild==1.*\n"
    )
    pkgs = parse_lockfile(f, f.read_text())
    assert [(p.name, p.version) for p in pkgs] == [("foo-bar", "1.0"), ("requests", "2.31.0")]


def test_uv_lock_registry_only(tmp_path: Path):
    text = """
[[package]]
name = "Django"
version = "5.1"
source = { registry = "https://pypi.org/simple" }
[[package]]
name = "local"
version = "0.1"
source = { editable = "." }
[[package]]
name = "internal"
version = "1.0"
source = { registry = "https://pypi.corp.example/simple" }
"""
    pkgs = parse_lockfile(tmp_path / "uv.lock", text)
    assert [(p.name, p.version) for p in pkgs] == [("django", "5.1")]


def test_poetry_lock_skips_sourced(tmp_path: Path):
    text = """
[[package]]
name = "a"
version = "1.0"
[[package]]
name = "g"
version = "2.0"
[package.source]
type = "git"
url = "https://x"
"""
    assert [p.name for p in parse_lockfile(tmp_path / "poetry.lock", text)] == ["a"]


def test_cargo_lock_requires_crates_io_source(tmp_path: Path):
    text = """
[[package]]
name = "myapp"
version = "0.1.0"
[[package]]
name = "serde"
version = "1.0.200"
source = "registry+https://github.com/rust-lang/crates.io-index"
[[package]]
name = "forked"
version = "1.0.0"
source = "git+https://github.com/x/forked"
"""
    assert [p.name for p in parse_lockfile(tmp_path / "Cargo.lock", text)] == ["serde"]


def test_go_sum_dedupes_and_skips_gomod_lines(tmp_path: Path):
    text = "a.com/m v1.0.0 h1:x=\na.com/m v1.0.0/go.mod h1:y=\nb.com/n v0.2.0 h1:z=\n"
    pkgs = parse_lockfile(tmp_path / "go.sum", text)
    assert [(p.name, p.version) for p in pkgs] == [("a.com/m", "v1.0.0"), ("b.com/n", "v0.2.0")]


def test_unsupported_file(tmp_path: Path):
    with pytest.raises(LockfileError):
        parse_lockfile(tmp_path / "Gemfile.lock", "")


def test_discover_skips_vendored_dirs(tmp_path: Path):
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "package-lock.json").write_text("{}")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "uv.lock").write_text("")
    found = [p.relative_to(tmp_path).as_posix() for p in discover([tmp_path])]
    assert found == ["app/uv.lock"]


def test_discover_missing_path(tmp_path: Path):
    with pytest.raises(LockfileError):
        list(discover([tmp_path / "nope"]))
