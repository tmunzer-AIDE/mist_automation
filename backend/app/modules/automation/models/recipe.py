"""
Workflow recipe model — reusable workflow templates with placeholder tracking.
"""

from datetime import datetime, timezone
from enum import Enum

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field

from app.models.mixins import TimestampMixin
from app.modules.automation.models.workflow import WorkflowEdge, WorkflowNode


class RecipeCategory(str, Enum):
    """Recipe category."""
    MONITORING = "monitoring"
    DEPLOYMENT = "deployment"
    MAINTENANCE = "maintenance"
    INCIDENT_RESPONSE = "incident_response"
    REPORTING = "reporting"


class RecipeDifficulty(str, Enum):
    """Recipe difficulty level."""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class RecipePlaceholder(BaseModel):
    """A field that the user must fill after instantiating a recipe."""
    node_id: str = Field(..., description="Which node contains the placeholder")
    field_path: str = Field(..., description="Dot path within node config (e.g. 'notification_channel')")
    label: str = Field(..., description="Human-readable label (e.g. 'Slack Webhook URL')")
    description: str = Field(default="", description="Help text shown to the user")
    placeholder_type: str = Field(default="text", description="Input type: text, url, channel, cron, site_id")


class WorkflowRecipe(TimestampMixin, Document):
    """Reusable workflow template."""

    name: str = Field(..., description="Recipe name")
    description: str = Field(default="", description="Recipe description")
    category: RecipeCategory = Field(..., description="Recipe category")
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    difficulty: RecipeDifficulty = Field(default=RecipeDifficulty.BEGINNER, description="Difficulty level")

    workflow_type: str = Field(default="standard", description="standard or subflow")
    nodes: list[WorkflowNode] = Field(default_factory=list, description="Graph nodes")
    edges: list[WorkflowEdge] = Field(default_factory=list, description="Graph edges")
    placeholders: list[RecipePlaceholder] = Field(default_factory=list, description="Fields user must fill")

    built_in: bool = Field(default=False, description="Whether this is a built-in seed recipe")
    created_by: PydanticObjectId | None = Field(default=None, description="User who published this recipe")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "workflow_recipes"
        indexes = ["category", "built_in"]
