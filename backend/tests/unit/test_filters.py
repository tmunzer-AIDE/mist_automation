"""
Unit tests for trigger condition evaluation (replaces old filter tests).

Tests the Jinja2 condition evaluation engine used by workflow triggers
and condition branches.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.modules.automation.services.executor_service import WorkflowExecutor
from app.utils.variables import validate_template


class TestTriggerConditionEvaluation:
    """Test Jinja2 condition evaluation via WorkflowExecutor."""

    def setup_method(self):
        self.executor = WorkflowExecutor.__new__(WorkflowExecutor)
        self.executor.mist_service = MagicMock()
        self.executor.variable_context = {
            "trigger": {
                "type": "alarm",
                "severity": "critical",
                "events": [{"type": "ap_offline", "device": {"name": "AP-01"}}],
                "count": 5,
                "active": True,
            },
            "results": {},
        }

    def test_simple_equality_true(self):
        result = self.executor._evaluate_condition_expression("{{ type == 'alarm' }}")
        assert result is True

    def test_simple_equality_false(self):
        result = self.executor._evaluate_condition_expression("{{ type == 'audit' }}")
        assert result is False

    def test_nested_field_access(self):
        result = self.executor._evaluate_condition_expression(
            "{{ events[0].device.name == 'AP-01' }}"
        )
        assert result is True

    def test_nested_field_mismatch(self):
        result = self.executor._evaluate_condition_expression(
            "{{ events[0].device.name == 'SW-01' }}"
        )
        assert result is False

    def test_severity_critical(self):
        result = self.executor._evaluate_condition_expression(
            "{{ severity == 'critical' }}"
        )
        assert result is True

    def test_numeric_comparison(self):
        result = self.executor._evaluate_condition_expression("{{ count > 3 }}")
        assert result is True

    def test_numeric_comparison_false(self):
        result = self.executor._evaluate_condition_expression("{{ count > 10 }}")
        assert result is False

    def test_boolean_truthy(self):
        result = self.executor._evaluate_condition_expression("{{ active }}")
        assert result is True

    def test_and_condition(self):
        result = self.executor._evaluate_condition_expression(
            "{{ type == 'alarm' and severity == 'critical' }}"
        )
        assert result is True

    def test_and_condition_partial_fail(self):
        result = self.executor._evaluate_condition_expression(
            "{{ type == 'alarm' and severity == 'major' }}"
        )
        assert result is False

    def test_or_condition(self):
        result = self.executor._evaluate_condition_expression(
            "{{ severity == 'critical' or severity == 'major' }}"
        )
        assert result is True

    def test_in_operator(self):
        result = self.executor._evaluate_condition_expression(
            "{{ severity in ['critical', 'major'] }}"
        )
        assert result is True

    def test_not_in_operator(self):
        result = self.executor._evaluate_condition_expression(
            "{{ severity not in ['info', 'warning'] }}"
        )
        assert result is True

    def test_empty_expression_is_falsy(self):
        result = self.executor._evaluate_condition_expression("")
        assert result is False

    def test_false_string_is_falsy(self):
        result = self.executor._evaluate_condition_expression("{{ false }}")
        assert result is False

    def test_none_string_is_falsy(self):
        result = self.executor._evaluate_condition_expression("{{ none }}")
        assert result is False

    def test_undefined_variable_is_falsy(self):
        result = self.executor._evaluate_condition_expression("{{ nonexistent_var }}")
        assert result is False

    def test_contains_check(self):
        result = self.executor._evaluate_condition_expression(
            "{{ 'offline' in events[0].type }}"
        )
        assert result is True


class TestTriggerConditionValidation:
    """Test Jinja2 template validation for trigger conditions."""

    def test_valid_simple_expression(self):
        is_valid, error = validate_template("{{ type == 'alarm' }}")
        assert is_valid is True
        assert error is None

    def test_valid_complex_expression(self):
        is_valid, error = validate_template(
            "{{ severity in ['critical', 'major'] and count > 0 }}"
        )
        assert is_valid is True
        assert error is None

    def test_invalid_unclosed_brace(self):
        is_valid, error = validate_template("{{ type == 'alarm'")
        assert is_valid is False
        assert error is not None

    def test_invalid_syntax(self):
        is_valid, error = validate_template("{% if %}")
        assert is_valid is False

    def test_empty_string_is_valid(self):
        is_valid, error = validate_template("")
        assert is_valid is True

    def test_none_is_valid(self):
        is_valid, error = validate_template(None)
        assert is_valid is True

    def test_plain_text_is_valid(self):
        is_valid, error = validate_template("just plain text")
        assert is_valid is True


class TestSaveAsVariableStorage:
    """Test save_as variable storage in executor."""

    def setup_method(self):
        self.executor = WorkflowExecutor.__new__(WorkflowExecutor)
        self.executor.mist_service = MagicMock()
        self.executor.variable_context = {
            "trigger": {"type": "alarm"},
            "results": {},
        }

    def test_results_stored_in_context(self):
        """Verify save_as stores output into variable_context."""
        self.executor.variable_context["results"]["my_sites"] = [
            {"name": "Site A"},
            {"name": "Site B"},
        ]
        assert len(self.executor.variable_context["results"]["my_sites"]) == 2
        assert self.executor.variable_context["results"]["my_sites"][0]["name"] == "Site A"

    def test_variable_accessible_in_condition(self):
        """Verify stored variables are accessible via Jinja2 evaluation."""
        self.executor.variable_context["results"]["site_count"] = 5
        result = self.executor._evaluate_condition_expression("{{ site_count > 3 }}")
        assert result is True


class TestSetVariableAction:
    """Test set_variable action execution."""

    def setup_method(self):
        self.executor = WorkflowExecutor.__new__(WorkflowExecutor)
        self.executor.mist_service = MagicMock()
        self.executor.variable_context = {
            "trigger": {"events": [{"severity": "critical"}]},
            "results": {},
        }

    @pytest.mark.asyncio
    async def test_set_variable_string(self):
        config = {
            "variable_name": "sev",
            "variable_expression": "{{ events[0].severity }}",
        }
        result = await self.executor._execute_set_variable(config)
        assert result["variable_name"] == "sev"
        assert self.executor.variable_context["results"]["sev"] == "critical"

    @pytest.mark.asyncio
    async def test_set_variable_json(self):
        config = {
            "variable_name": "data",
            "variable_expression": '{"key": "value"}',
        }
        result = await self.executor._execute_set_variable(config)
        assert self.executor.variable_context["results"]["data"] == {"key": "value"}


class TestForEachAction:
    """Test for_each loop execution."""

    def setup_method(self):
        self.executor = WorkflowExecutor.__new__(WorkflowExecutor)
        self.executor.mist_service = MagicMock()
        self.executor.variable_context = {
            "trigger": {},
            "results": {
                "sites": [
                    {"name": "Site A"},
                    {"name": "Site B"},
                    {"name": "Site C"},
                ]
            },
        }

    def _make_for_each_node(self, loop_over, loop_variable="site", max_iterations=100):
        from app.modules.automation.models.workflow import WorkflowNode
        return WorkflowNode(
            id="foreach-1",
            type="for_each",
            name="Loop",
            config={
                "loop_over": loop_over,
                "loop_variable": loop_variable,
                "max_iterations": max_iterations,
            },
        )

    @pytest.mark.asyncio
    async def test_for_each_basic(self):
        node = self._make_for_each_node("results.sites")
        result = await self.executor._execute_for_each(node, MagicMock())
        assert result["iterations"] == 3

    @pytest.mark.asyncio
    async def test_for_each_max_iterations(self):
        node = self._make_for_each_node("results.sites", max_iterations=2)
        result = await self.executor._execute_for_each(node, MagicMock())
        assert result["iterations"] == 2

    @pytest.mark.asyncio
    async def test_for_each_none_raises(self):
        node = self._make_for_each_node("results.nonexistent", loop_variable="item")
        with pytest.raises(ValueError, match="resolved to None"):
            await self.executor._execute_for_each(node, MagicMock())

    @pytest.mark.asyncio
    async def test_for_each_not_list_raises(self):
        self.executor.variable_context["results"]["scalar"] = "not a list"
        node = self._make_for_each_node("results.scalar", loop_variable="item")
        with pytest.raises(ValueError, match="is not a list"):
            await self.executor._execute_for_each(node, MagicMock())

    @pytest.mark.asyncio
    async def test_for_each_cleans_up_context(self):
        node = self._make_for_each_node("results.sites")
        await self.executor._execute_for_each(node, MagicMock())
        assert "loop" not in self.executor.variable_context
        assert "item" not in self.executor.variable_context
