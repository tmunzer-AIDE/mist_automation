"""
Snapshot analyzer: orchestrates all check categories and builds prediction reports.

Provides:
- analyze_site() — run all 7 check categories on baseline vs predicted snapshots
- build_prediction_report() — aggregate CheckResults into a PredictionReport
- compute_overall_severity() — derive worst severity from check results
"""

from __future__ import annotations

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


def compute_overall_severity(results: list[CheckResult]) -> str:
    """Compute worst severity from a list of check results."""
    worst = max((_SEVERITY_ORDER.get(r.status, 0) for r in results), default=0)
    return _SEVERITY_LABELS[worst]


# ---------------------------------------------------------------------------
# analyze_site
# ---------------------------------------------------------------------------


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
    """
    results: list[CheckResult] = []
    results.extend(check_connectivity(baseline, predicted))
    results.extend(check_config_conflicts(predicted))
    results.extend(check_template_variables(predicted))
    results.extend(check_port_impact(baseline, predicted))
    results.extend(check_routing(baseline, predicted))
    results.extend(check_security(baseline, predicted))
    results.extend(check_stp(baseline, predicted))
    return results


# ---------------------------------------------------------------------------
# build_prediction_report
# ---------------------------------------------------------------------------


def build_prediction_report(results: list[CheckResult]) -> PredictionReport:
    """Aggregate CheckResults into a PredictionReport with counts and severity."""
    passed = sum(1 for r in results if r.status == "pass")
    warnings = sum(1 for r in results if r.status == "warning")
    errors = sum(1 for r in results if r.status == "error")
    critical = sum(1 for r in results if r.status == "critical")
    skipped = sum(1 for r in results if r.status == "skipped")
    severity = compute_overall_severity(results)

    parts: list[str] = []
    if critical:
        parts.append(f"{critical} critical")
    if errors:
        parts.append(f"{errors} error(s)")
    if warnings:
        parts.append(f"{warnings} warning(s)")
    summary = ", ".join(parts) if parts else "All checks passed"

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
        execution_safe=(errors == 0 and critical == 0),
    )
