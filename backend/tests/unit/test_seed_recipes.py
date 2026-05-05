"""Unit tests for built-in workflow seed recipes.

These tests exercise the pure-function recipe builders directly. `WorkflowRecipe`
is a Beanie Document whose constructor calls `get_motor_collection()` — we
short-circuit that with a module-level monkey-patch so the tests do not need
a running MongoDB or a Beanie `init_beanie` call.
"""

import pytest

from app.modules.automation.models.recipe import (
    RecipeCategory,
    RecipeDifficulty,
    WorkflowRecipe,
)
from app.modules.automation.seed_recipes import (
    SEED_RECIPES,
    _build_ai_alert_to_slack,
)


@pytest.fixture(autouse=True)
def _bypass_beanie_collection_init(monkeypatch):
    """Skip the `get_motor_collection()` call inside Document.__init__.

    Beanie Documents call `cls.get_motor_collection()` from `__init__`, which
    requires `init_beanie()` to have run against a live MongoDB. For pure
    in-memory recipe construction we have no DB, so we patch it to a no-op.
    """
    monkeypatch.setattr(WorkflowRecipe, "get_motor_collection", classmethod(lambda cls: None))


@pytest.fixture
def recipe() -> WorkflowRecipe:
    """Build the recipe once per test."""
    return _build_ai_alert_to_slack()


class TestAIAlertToSlackTopLevelFields:
    def test_returns_workflow_recipe(self, recipe):
        assert isinstance(recipe, WorkflowRecipe)

    def test_name(self, recipe):
        assert recipe.name == "AI Alert to Slack"

    def test_description_mentions_directly_to_slack(self, recipe):
        assert "directly to Slack" in recipe.description

    def test_category_is_monitoring(self, recipe):
        assert recipe.category == RecipeCategory.MONITORING

    def test_difficulty_is_beginner(self, recipe):
        assert recipe.difficulty == RecipeDifficulty.BEGINNER

    def test_is_built_in(self, recipe):
        assert recipe.built_in is True


class TestAIAlertToSlackGraphShape:
    def test_has_three_nodes(self, recipe):
        assert len(recipe.nodes) == 3

    def test_has_two_edges(self, recipe):
        assert len(recipe.edges) == 2

    def test_node_order_is_trigger_then_ai_then_slack(self, recipe):
        node_types = [n.type for n in recipe.nodes]
        assert node_types == ["trigger", "ai_agent", "slack"]

    def test_edges_chain_trigger_to_ai_to_slack(self, recipe):
        # Edges should chain: trigger-1 -> ai-1 -> slack-1
        edge_pairs = [(e.source_node_id, e.target_node_id) for e in recipe.edges]
        assert ("trigger-1", "ai-1") in edge_pairs
        assert ("ai-1", "slack-1") in edge_pairs


class TestAIAlertToSlackNodeContent:
    def test_ai_node_named_AI_Agent_no_spaces(self, recipe):
        ai_nodes = [n for n in recipe.nodes if n.type == "ai_agent"]
        assert len(ai_nodes) == 1
        # Exact name: AI_Agent (underscores, NOT "AI Agent" — avoids the
        # spaces->underscores sanitization step).
        assert ai_nodes[0].name == "AI_Agent"
        assert " " not in ai_nodes[0].name

    def test_slack_node_references_ai_agent_result(self, recipe):
        slack_nodes = [n for n in recipe.nodes if n.type == "slack"]
        assert len(slack_nodes) == 1
        assert slack_nodes[0].config.get("slack_json_variable") == "{{ nodes.AI_Agent.result }}"


class TestAIAlertToSlackPlaceholders:
    def test_has_two_placeholders(self, recipe):
        assert len(recipe.placeholders) == 2

    def test_slack_url_placeholder(self, recipe):
        slack_url_phs = [
            p for p in recipe.placeholders if p.node_id == "slack-1" and p.field_path == "notification_channel"
        ]
        assert len(slack_url_phs) == 1
        assert slack_url_phs[0].placeholder_type == "url"

    def test_agent_task_placeholder(self, recipe):
        agent_task_phs = [p for p in recipe.placeholders if p.node_id == "ai-1" and p.field_path == "agent_task"]
        assert len(agent_task_phs) == 1
        assert agent_task_phs[0].placeholder_type == "text"


class TestAIAlertToSlackSeedRegistration:
    def test_included_in_seed_recipes_list(self):
        # The seeding function (seed_built_in_recipes) iterates over SEED_RECIPES.
        # Including the builder there is what makes the recipe seedable.
        assert _build_ai_alert_to_slack in SEED_RECIPES

    def test_seed_recipes_contains_recipe_with_correct_name(self):
        names = [builder().name for builder in SEED_RECIPES]
        assert "AI Alert to Slack" in names
