from datetime import UTC, datetime, timedelta

from steep.analyze import Policy, evaluate
from steep.models import Package, VersionInfo

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
PKG = Package("npm", "x", "1.0.0", "package-lock.json")


def info(age_days: float, prov: bool | None = None, **kw: bool) -> VersionInfo:
    return VersionInfo(NOW - timedelta(days=age_days), prov, **kw)


def rules(findings):
    return {(f.rule, f.severity) for f in findings}


def test_too_new_severity_scales_with_age():
    p = Policy(min_age_days=7)
    assert rules(evaluate(PKG, info(1), [], p, NOW)) == {("too-new", "high")}
    assert rules(evaluate(PKG, info(5), [], p, NOW)) == {("too-new", "medium")}
    assert evaluate(PKG, info(8), [], p, NOW) == []


def test_boundary_exactly_at_cooldown_is_ok():
    assert evaluate(PKG, info(7), [], Policy(min_age_days=7), NOW) == []


def test_zero_cooldown_disables_age_rule():
    assert evaluate(PKG, info(0.01), [], Policy(min_age_days=0), NOW) == []


def test_provenance_regression():
    out = evaluate(PKG, info(30, prov=False), [info(60, prov=True)], Policy(), NOW)
    assert rules(out) == {("provenance-regression", "high")}


def test_no_regression_when_never_had_provenance_or_unknown():
    assert evaluate(PKG, info(30, prov=False), [info(60, prov=False)], Policy(), NOW) == []
    assert evaluate(PKG, info(30, prov=None), [info(60, prov=True)], Policy(), NOW) == []


def test_regression_only_looks_at_recent_releases():
    earlier = [info(40, prov=False)] * 3 + [info(90, prov=True)]
    assert evaluate(PKG, info(30, prov=False), earlier, Policy(), NOW) == []


def test_yanked_and_deprecated():
    out = evaluate(PKG, info(30, yanked=True, deprecated=True), [], Policy(), NOW)
    assert rules(out) == {("yanked", "high"), ("deprecated", "medium")}


def test_not_found():
    assert rules(evaluate(PKG, None, [], Policy(), NOW)) == {("not-found", "low")}


def test_naive_timestamp_treated_as_utc():
    naive = VersionInfo(datetime(2026, 10, 21, 11))
    assert rules(evaluate(PKG, naive, [], Policy(), NOW)) == {("too-new", "high")}


def test_allow_list():
    p = Policy(allow=["npm:x@1.0.0", "pypi:y"])
    assert p.is_allowed(PKG)
    assert p.is_allowed(Package("pypi", "y", "9", "f"))
    assert not p.is_allowed(Package("npm", "z", "1", "f"))
