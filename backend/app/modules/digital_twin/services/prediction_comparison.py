"""
Compare Twin predictions with Impact Analysis actual findings.

Called after an IA monitoring session completes to assess prediction accuracy.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def compare_prediction_vs_reality(
    twin_prediction: dict[str, Any] | None,
    ia_validation_results: dict[str, Any] | None,
    ia_impact_severity: str,
) -> dict[str, Any]:
    """Compare Twin prediction with IA actual results.

    Args:
        twin_prediction: Frozen PredictionReport dict from Twin session
        ia_validation_results: Actual validation results from IA session
        ia_impact_severity: Actual impact severity from IA (none/info/warning/critical)

    Returns:
        Comparison dict with:
        - predicted_severity: what the Twin said
        - actual_severity: what IA found
        - accuracy: "correct" / "under_predicted" / "over_predicted" / "unknown"
        - details: list of specific prediction vs reality mismatches
    """
    if not twin_prediction:
        return {
            "predicted_severity": "unknown",
            "actual_severity": ia_impact_severity,
            "accuracy": "unknown",
            "details": ["No Twin prediction available for comparison"],
        }

    predicted_severity = twin_prediction.get("overall_severity", "clean")
    actual_severity = ia_impact_severity or "none"

    # Map severity to numeric for comparison
    severity_order = {"clean": 0, "none": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}
    pred_level = severity_order.get(predicted_severity, 0)
    actual_level = severity_order.get(actual_severity, 0)

    if pred_level == actual_level:
        accuracy = "correct"
    elif pred_level > actual_level:
        accuracy = "over_predicted"
    else:
        accuracy = "under_predicted"

    details: list[str] = []

    # Compare predicted check counts vs actual issues
    pred_errors = twin_prediction.get("errors", 0) + twin_prediction.get("critical", 0)
    pred_warnings = twin_prediction.get("warnings", 0)

    if accuracy == "correct":
        details.append(f"Prediction matched: both predicted and actual severity were '{actual_severity}'")
    elif accuracy == "over_predicted":
        details.append(
            f"Twin predicted '{predicted_severity}' ({pred_errors} error(s), {pred_warnings} warning(s)) "
            f"but actual impact was '{actual_severity}' — false positive"
        )
    else:
        details.append(
            f"Twin predicted '{predicted_severity}' but actual impact was '{actual_severity}' "
            f"— issue not caught by pre-deployment checks"
        )

    # Check for specific IA incidents vs Twin predictions
    if ia_validation_results:
        actual_failures = [
            k for k, v in ia_validation_results.items() if isinstance(v, dict) and v.get("status") in ("warn", "fail")
        ]
        if actual_failures and pred_level == 0:
            details.append(
                f"IA found {len(actual_failures)} issue(s) that Twin did not predict: "
                f"{', '.join(actual_failures[:5])}"
            )

    return {
        "predicted_severity": predicted_severity,
        "actual_severity": actual_severity,
        "accuracy": accuracy,
        "predicted_errors": pred_errors,
        "predicted_warnings": pred_warnings,
        "details": details,
    }
