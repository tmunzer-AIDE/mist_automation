"""AI Agent analysis service for config change impact assessment.

Uses the LLM + MCP tool-calling loop to analyze collected monitoring data
and produce actionable recommendations. Falls back to rule-based summary
when LLM is unavailable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from app.modules.impact_analysis.models import MonitoringSession

logger = structlog.get_logger(__name__)


async def analyze_session(session: MonitoringSession) -> dict[str, Any]:
    """Analyze a monitoring session and produce impact assessment.

    Returns:
        {
            "has_impact": bool,
            "severity": "critical" | "warning" | "info",
            "summary": str (markdown),
            "culprit_field": str | None,
            "recommendations": list[str],
            "affected_devices": list[str],
            "tool_calls": list[dict] (if AI agent used),
            "thinking_texts": list[str] (if AI agent used),
            "source": "ai_agent" | "rule_based",
        }
    """
    # Check if LLM is available
    if await _is_llm_available():
        try:
            return await _ai_agent_analysis(session)
        except Exception as e:
            logger.warning("ai_agent_analysis_failed", session_id=str(session.id), error=str(e))
            # Fall through to rule-based

    return _rule_based_analysis(session)


async def _is_llm_available() -> bool:
    """Check if any LLM config is available and the feature is enabled."""
    try:
        from app.modules.llm.services.llm_service_factory import is_llm_available

        return await is_llm_available()
    except Exception:
        return False


async def _ai_agent_analysis(session: MonitoringSession) -> dict[str, Any]:
    """Run AI Agent analysis with LLM + MCP tools."""
    from app.modules.llm.services.agent_service import AIAgentService
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.mcp_client import create_local_mcp_client
    from app.modules.llm.services.prompt_builders import _sanitize_for_prompt

    llm_service = await create_llm_service()

    # Build system prompt
    system_prompt = _build_system_prompt()

    # Build user message with session data
    user_message = _build_user_message(session, _sanitize_for_prompt)

    # Connect to in-process MCP server for backup/workflow/system data access
    mcp_client = create_local_mcp_client()
    await mcp_client.connect()

    try:
        agent = AIAgentService(
            llm=llm_service,
            mcp_clients=[mcp_client],
            max_iterations=10,
        )

        result = await agent.run(
            task=user_message,
            system_prompt=system_prompt,
        )

        # Parse structured result from agent response
        return {
            "has_impact": _detect_impact_from_text(result.result),
            "severity": _detect_severity_from_text(result.result),
            "summary": result.result,
            "culprit_field": None,
            "recommendations": _extract_recommendations(result.result),
            "affected_devices": [],
            "tool_calls": [
                {
                    "tool": tc.tool,
                    "arguments": tc.arguments,
                    "result": tc.result[:500] if tc.result else None,
                    "is_error": tc.is_error,
                }
                for tc in (result.tool_calls or [])
            ],
            "thinking_texts": result.thinking_texts or [],
            "source": "ai_agent",
        }
    finally:
        await mcp_client.disconnect()


def _build_system_prompt() -> str:
    """Build the system prompt for the impact analysis AI agent."""
    return (
        "You are a network impact analyst for Juniper Mist. A configuration change was made to a "
        "network device and the system has been monitoring network health. Your job is to analyze "
        "all collected data and determine:\n\n"
        "1. Whether the configuration change caused any degradation in network performance, "
        "connectivity, or stability\n"
        '2. The severity of the impact: "critical" (service outage or major degradation), '
        '"warning" (minor degradation or potential risk), or "info" (no significant impact)\n'
        "3. The specific configuration field or change that likely caused the issue (if identifiable)\n"
        "4. Concrete recommendations: rollback the change, adjust specific settings, continue "
        "monitoring, or accept the change\n\n"
        "Be concise and actionable. Focus on facts from the data, not speculation. "
        "If the data shows no issues, say so clearly.\n\n"
        "Format your response as:\n"
        "**Severity**: [critical/warning/info]\n"
        "**Summary**: [1-3 sentence summary]\n"
        "**Recommendations**:\n"
        "- [recommendation 1]\n"
        "- [recommendation 2]\n\n"
        "You have access to MCP tools that can query backups, workflows, and system data "
        "for additional context if needed."
    )


def _build_user_message(session: MonitoringSession, sanitize_fn: Any) -> str:
    """Build the user message with all session data for analysis."""
    parts: list[str] = []

    # Config change details
    parts.append("## Config Change Details")
    parts.append(f"- Device: {sanitize_fn(session.device_name)} ({session.device_type.value})")
    parts.append(f"- MAC: {session.device_mac}")
    parts.append(f"- Site: {sanitize_fn(session.site_name)}")
    parts.append(f"- Changes detected: {len(session.config_changes)}")
    for i, change in enumerate(session.config_changes):
        parts.append(f"  {i + 1}. {change.event_type} at {change.timestamp.isoformat()}")
        if change.device_model:
            parts.append(f"     Model: {sanitize_fn(change.device_model)}")
        if change.firmware_version:
            parts.append(f"     Firmware: {sanitize_fn(change.firmware_version)}")
        if change.commit_user:
            parts.append(
                f"     Committed by: {sanitize_fn(change.commit_user)} via {sanitize_fn(change.commit_method)}"
            )
        if change.config_diff:
            # Truncate large diffs but include enough for the AI to analyze
            diff = change.config_diff[:3000]
            if len(change.config_diff) > 3000:
                diff += f"\n... (truncated, full diff is {len(change.config_diff)} chars)"
            parts.append(f"     Config diff (Junos):\n```\n{diff}\n```")

    # SLE Delta
    if session.sle_delta:
        parts.append("\n## SLE Performance Delta")
        degraded = session.sle_delta.get("overall_degraded", False)
        parts.append(f"- Overall degraded: {degraded}")
        for metric in session.sle_delta.get("metrics", []):
            status_icon = "DEGRADED" if metric.get("degraded") else "OK"
            parts.append(
                f"- {metric['name']}: baseline={metric.get('baseline_value')}, "
                f"current={metric.get('current_value')}, "
                f"change={metric.get('change_percent')}% [{status_icon}]"
            )

    # Device-level drill-down
    if session.sle_drill_down:
        parts.append("\n## SLE Device-Level Drill-Down")
        for metric, endpoints in session.sle_drill_down.items():
            if isinstance(endpoints, list):
                parts.append(f"- {metric}: {len(endpoints)} endpoint(s) with data")
            else:
                parts.append(f"- {metric}: {endpoints}")

    # Incidents
    if session.incidents:
        parts.append("\n## Device Incidents During Monitoring")
        for incident in session.incidents:
            resolved_str = "RESOLVED" if incident.resolved else "UNRESOLVED"
            revert_str = " [CONFIG REVERT]" if incident.is_revert else ""
            parts.append(
                f"- {incident.event_type} ({incident.severity}) at {incident.timestamp.isoformat()} "
                f"[{resolved_str}]{revert_str}"
            )

    # Topology diff
    if session.topology_baseline and session.topology_latest:
        from app.modules.impact_analysis.services.topology_service import compute_topology_diff

        diff = compute_topology_diff(session.topology_baseline, session.topology_latest)
        if diff.get("has_changes"):
            parts.append("\n## Topology Changes")
            for detail in diff.get("details", [])[:20]:
                parts.append(f"- {detail.get('type', 'unknown')}: {detail}")
        else:
            parts.append("\n## Topology: No changes detected")

    # Validation results
    if session.validation_results:
        parts.append("\n## Validation Check Results")
        for check_name, result in session.validation_results.items():
            if check_name == "overall_status":
                parts.append(f"- **Overall**: {result}")
                continue
            if isinstance(result, dict):
                status = result.get("status", "unknown")
                parts.append(f"- {check_name}: {status}")
                details = result.get("details", [])
                if details and isinstance(details, list):
                    for d in details[:5]:
                        parts.append(f"  - {d}")

    # Monitoring stats
    parts.append("\n## Monitoring Duration")
    parts.append(f"- Polls completed: {session.polls_completed}/{session.polls_total}")
    parts.append(f"- Interval: {session.interval_minutes} minutes")

    return "\n".join(parts)


def _rule_based_analysis(session: MonitoringSession) -> dict[str, Any]:
    """Generate rule-based analysis when LLM is unavailable."""
    issues: list[str] = []
    recommendations: list[str] = []
    severity = "info"

    # Check SLE delta
    if session.sle_delta and session.sle_delta.get("overall_degraded"):
        severity = "warning"
        for metric in session.sle_delta.get("metrics", []):
            if metric.get("degraded"):
                issues.append(
                    f"SLE {metric['name']} degraded by {abs(metric.get('change_percent', 0)):.1f}% "
                    f"(baseline: {metric.get('baseline_value')}, current: {metric.get('current_value')})"
                )
        recommendations.append("Review the SLE metrics and consider rolling back the configuration change")

    # Check incidents
    unresolved = [i for i in session.incidents if not i.resolved]
    reverts = [i for i in session.incidents if i.is_revert]

    if reverts:
        severity = "critical"
        issues.append(f"Device automatically reverted configuration ({len(reverts)} revert event(s))")
        recommendations.append("The device rejected the configuration change — investigate the cause before retrying")

    if unresolved:
        if severity != "critical":
            severity = "warning"
        issues.append(f"{len(unresolved)} unresolved incident(s) during monitoring window")
        for incident in unresolved[:5]:
            issues.append(f"  - {incident.event_type} ({incident.severity})")
        recommendations.append("Investigate unresolved incidents before considering the change stable")

    # Check validation results
    if session.validation_results:
        overall = session.validation_results.get("overall_status", "pass")
        if overall == "fail":
            if severity != "critical":
                severity = "warning"
            failed_checks = [
                name
                for name, result in session.validation_results.items()
                if isinstance(result, dict) and result.get("status") == "fail"
            ]
            if failed_checks:
                issues.append(f"Failed validation checks: {', '.join(failed_checks)}")
                recommendations.append("Address failed validation checks before considering the change stable")

    has_impact = severity in ("critical", "warning")

    if not issues:
        summary = "No significant impact detected. The configuration change appears stable."
        recommendations.append("Continue normal operations")
    else:
        summary = f"Impact detected ({severity}). " + " ".join(issues[:3])

    return {
        "has_impact": has_impact,
        "severity": severity,
        "summary": summary,
        "culprit_field": None,
        "recommendations": recommendations,
        "affected_devices": [],
        "tool_calls": [],
        "thinking_texts": [],
        "source": "rule_based",
    }


def _detect_impact_from_text(text: str) -> bool:
    """Detect whether the AI agent found impact from its response text."""
    text_lower = text.lower()
    no_impact_phrases = ["no significant impact", "no impact detected", "change appears stable", "severity**: info"]
    if any(phrase in text_lower for phrase in no_impact_phrases):
        return False
    impact_phrases = ["degradation", "degraded", "severity**: critical", "severity**: warning", "rollback", "revert"]
    return any(phrase in text_lower for phrase in impact_phrases)


def _detect_severity_from_text(text: str) -> str:
    """Detect severity from AI agent response."""
    text_lower = text.lower()
    if "severity**: critical" in text_lower:
        return "critical"
    if "severity**: warning" in text_lower:
        return "warning"
    return "info"


def _extract_recommendations(text: str) -> list[str]:
    """Extract recommendation bullet points from AI agent response."""
    recommendations: list[str] = []
    in_recommendations = False
    for line in text.split("\n"):
        stripped = line.strip()
        if "recommendation" in stripped.lower() and (":" in stripped or "**" in stripped):
            in_recommendations = True
            continue
        if in_recommendations and stripped.startswith("- "):
            recommendations.append(stripped[2:].strip())
        elif in_recommendations and stripped and not stripped.startswith("- ") and not stripped.startswith("*"):
            in_recommendations = False
    return recommendations
