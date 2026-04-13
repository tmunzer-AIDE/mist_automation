"""
Snapshot analyzer: orchestrates all check categories and builds prediction reports.

Provides:
- analyze_site() — run all 7 check categories on baseline vs predicted snapshots
- build_prediction_report() — aggregate CheckResults into a PredictionReport
- compute_overall_severity() — derive worst severity from check results

Pre-existing issue classification:
    analyze_site() runs every check twice — once against (baseline, baseline) to
    capture the baseline state, and once against (baseline, predicted) for the
    proposed change. Any failing predicted result whose details are a subset of
    the matching baseline result is marked ``pre_existing=True``. This lets
    ``build_prediction_report`` exclude unrelated baseline config debt from the
    ``execution_safe`` decision, while still surfacing it in the report.
"""

from __future__ import annotations

import structlog

from app.modules.digital_twin.checks.config_conflicts import check_config_conflicts
from app.modules.digital_twin.checks.connectivity import check_connectivity
from app.modules.digital_twin.checks.port_impact import check_port_impact
from app.modules.digital_twin.checks.routing import check_routing
from app.modules.digital_twin.checks.security import check_security
from app.modules.digital_twin.checks.stp import check_stp
from app.modules.digital_twin.checks.template_checks import check_template_variables
from app.modules.digital_twin.models import CheckResult, PredictionReport
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot

# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"pass": 0, "skipped": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}
_SEVERITY_LABELS = {0: "clean", 1: "info", 2: "warning", 3: "error", 4: "critical"}
_FAILING_STATUSES = frozenset({"warning", "error", "critical"})

logger = structlog.get_logger(__name__)


def _status_counts(results: list[CheckResult]) -> dict[str, int]:
    """Return status bucket counts for a set of check results."""
    return {
        "pass": sum(1 for r in results if r.status == "pass"),
        "info": sum(1 for r in results if r.status == "info"),
        "warning": sum(1 for r in results if r.status == "warning"),
        "error": sum(1 for r in results if r.status == "error"),
        "critical": sum(1 for r in results if r.status == "critical"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
    }


def _run_check_category(
    category: str,
    check_fn,
    *args,
) -> list[CheckResult]:
    """Run one check category with start/end logging."""
    logger.info("twin_check_category_started", category=category)
    results = check_fn(*args)
    counts = _status_counts(results)
    logger.info(
        "twin_check_category_completed",
        category=category,
        total=len(results),
        **counts,
    )
    return results


def _log_check_results(
    *,
    stage: str,
    site_id: str,
    results: list[CheckResult],
) -> None:
    """Emit one structured log entry per check result for UI troubleshooting."""
    for result in results:
        logger.info(
            "twin_check_result",
            stage=stage,
            site_id=site_id,
            check_id=result.check_id,
            check_name=result.check_name,
            layer=result.layer,
            status=result.status,
            pre_existing=result.pre_existing,
            summary=result.summary,
            details=result.details,
            affected_objects=result.affected_objects,
            affected_sites=result.affected_sites,
            remediation_hint=result.remediation_hint,
            description=result.description,
        )


def compute_overall_severity(results: list[CheckResult]) -> str:
    """Compute worst severity from a list of check results."""
    worst = max((_SEVERITY_ORDER.get(r.status, 0) for r in results), default=0)
    return _SEVERITY_LABELS[worst]


# ---------------------------------------------------------------------------
# analyze_site
# ---------------------------------------------------------------------------


def _run_all_checks(baseline: SiteSnapshot, predicted: SiteSnapshot) -> list[CheckResult]:
    """Run every check category against a (baseline, predicted) pair."""
    results: list[CheckResult] = []
    results.extend(_run_check_category("connectivity", check_connectivity, baseline, predicted))
    results.extend(_run_check_category("config_conflicts", check_config_conflicts, predicted))
    results.extend(_run_check_category("template_variables", check_template_variables, predicted))
    results.extend(_run_check_category("port_impact", check_port_impact, baseline, predicted))
    results.extend(_run_check_category("routing", check_routing, baseline, predicted))
    results.extend(_run_check_category("security", check_security, baseline, predicted))
    results.extend(_run_check_category("stp", check_stp, baseline, predicted))
    return results


def _run_checks_for_change_profile(
    baseline: SiteSnapshot,
    predicted: SiteSnapshot,
    affected_object_types: list[str] | None,
) -> list[CheckResult]:
    """Run checks according to change profile.

    For ``devices``-only changes we prioritize switch/gateway topology and
    routing checks (L1/L2/L3) and skip Wi-Fi-centric categories.
    """
    if not affected_object_types:
        return _run_all_checks(baseline, predicted)

    affected = {t for t in affected_object_types if t}
    if affected == {"devices"}:
        results: list[CheckResult] = []
        results.extend(_run_check_category("connectivity", check_connectivity, baseline, predicted))
        # Run L1 config checks relevant to switch/gateway changes, but skip
        # Wi-Fi-specific duplicate-SSID checks in this profile.
        cfg_results = [r for r in _run_check_category("config_conflicts", check_config_conflicts, predicted) if r.check_id != "CFG-SSID"]
        results.extend(cfg_results)
        results.extend(_run_check_category("port_impact", check_port_impact, baseline, predicted))
        results.extend(_run_check_category("routing", check_routing, baseline, predicted))
        results.extend(_run_check_category("stp", check_stp, baseline, predicted))
        return results

    return _run_all_checks(baseline, predicted)


def _classify_pre_existing(
    predicted_results: list[CheckResult],
    baseline_results: list[CheckResult],
) -> None:
    """Mark predicted results as ``pre_existing`` when baseline already failed the same way.

    A predicted failing check is pre-existing when the same check_id is failing
    in the baseline analysis and every predicted detail is already present in
    the baseline details. New details (worsening) disqualify the mark, so
    changes that *add* issues are still treated as introduced by the change.
    """
    baseline_by_id: dict[str, CheckResult] = {r.check_id: r for r in baseline_results}
    for r in predicted_results:
        if r.status not in _FAILING_STATUSES:
            continue
        b = baseline_by_id.get(r.check_id)
        if not b or b.status not in _FAILING_STATUSES:
            continue
        baseline_details = set(b.details)
        predicted_details = set(r.details)
        if not predicted_details or predicted_details <= baseline_details:
            r.pre_existing = True
            logger.info(
                "twin_check_marked_pre_existing",
                check_id=r.check_id,
                status=r.status,
                details=r.details,
            )


def analyze_site(baseline: SiteSnapshot, predicted: SiteSnapshot) -> list[CheckResult]:
    """Run all check categories and return a flat list of results.

    Categories (7 modules, producing results across layers 1-5):
    - connectivity: CONN-PHYS, CONN-VLAN
    - config_conflicts: CFG-SUBNET, CFG-VLAN, CFG-SSID, CFG-DHCP-RNG, CFG-DHCP-CFG
    - template_checks: TMPL-VAR
    - port_impact: PORT-DISC, PORT-CLIENT
    - routing: ROUTE-GW, ROUTE-OSPF, ROUTE-BGP, ROUTE-WAN
    - security: SEC-GUEST, SEC-POLICY, SEC-NAC
    - stp: STP-ROOT, STP-BPDU, STP-LOOP

    Every failing check is additionally classified as ``pre_existing`` when
    the same issue already existed in the baseline snapshot.
    """
    predicted_results = _run_checks_for_change_profile(baseline, predicted, None)

    if baseline is predicted:
        # Degenerate case — nothing changed, every failing check is inherently pre-existing.
        for r in predicted_results:
            if r.status in _FAILING_STATUSES:
                r.pre_existing = True
        return predicted_results

    baseline_results = _run_checks_for_change_profile(baseline, baseline, None)
    _classify_pre_existing(predicted_results, baseline_results)
    return predicted_results


def analyze_site_with_context(
    baseline: SiteSnapshot,
    predicted: SiteSnapshot,
    affected_object_types: list[str] | None,
) -> list[CheckResult]:
    """Run checks with optional change-type context for profile selection."""
    logger.info(
        "twin_site_checks_started",
        site_id=predicted.site_id,
        affected_object_types=affected_object_types or [],
    )
    predicted_results = _run_checks_for_change_profile(baseline, predicted, affected_object_types)

    if baseline is predicted:
        for r in predicted_results:
            if r.status in _FAILING_STATUSES:
                r.pre_existing = True
        return predicted_results

    baseline_results = _run_checks_for_change_profile(baseline, baseline, affected_object_types)
    _classify_pre_existing(predicted_results, baseline_results)
    _log_check_results(stage="predicted", site_id=predicted.site_id, results=predicted_results)
    counts = _status_counts(predicted_results)
    logger.info(
        "twin_site_checks_completed",
        site_id=predicted.site_id,
        total=len(predicted_results),
        **counts,
    )
    return predicted_results


# ---------------------------------------------------------------------------
# build_prediction_report
# ---------------------------------------------------------------------------


def build_prediction_report(results: list[CheckResult]) -> PredictionReport:
    """Aggregate CheckResults into a PredictionReport with counts and severity.

    ``execution_safe`` is diff-based: only errors and critical issues that are
    NOT flagged ``pre_existing`` block execution. Issues that were already
    present in the baseline snapshot are reported but do not gate approval.
    """
    passed = sum(1 for r in results if r.status == "pass")
    warnings = sum(1 for r in results if r.status == "warning")
    errors = sum(1 for r in results if r.status == "error")
    critical = sum(1 for r in results if r.status == "critical")
    skipped = sum(1 for r in results if r.status == "skipped")
    severity = compute_overall_severity(results)

    blocking_errors = sum(1 for r in results if r.status == "error" and not r.pre_existing)
    blocking_critical = sum(1 for r in results if r.status == "critical" and not r.pre_existing)
    pre_existing_failures = sum(1 for r in results if r.status in _FAILING_STATUSES and r.pre_existing)

    parts: list[str] = []
    if critical:
        parts.append(f"{critical} critical")
    if errors:
        parts.append(f"{errors} error(s)")
    if warnings:
        parts.append(f"{warnings} warning(s)")
    summary = ", ".join(parts) if parts else "All checks passed"
    if pre_existing_failures:
        summary += f" ({pre_existing_failures} pre-existing, not introduced by this change)"

    return PredictionReport(
        total_checks=len(results) - skipped,
        passed=passed,
        warnings=warnings,
        errors=errors,
        critical=critical,
        skipped=skipped,
        check_results=results,
        overall_severity=severity,
        summary=summary,
        execution_safe=(blocking_errors == 0 and blocking_critical == 0),
    )
