"""
Request/response schemas for workflow recipes.
"""

from pydantic import BaseModel, Field

from app.modules.automation.models.recipe import RecipeCategory, RecipeDifficulty, RecipePlaceholder


class RecipeResponse(BaseModel):
    """Public recipe response."""
    id: str
    name: str
    description: str
    category: RecipeCategory
    tags: list[str]
    difficulty: RecipeDifficulty
    workflow_type: str
    node_count: int
    edge_count: int
    placeholders: list[RecipePlaceholder]
    built_in: bool
    created_at: str


class RecipeDetailResponse(RecipeResponse):
    """Detailed recipe response including graph data."""
    nodes: list[dict]
    edges: list[dict]


class RecipeCreateRequest(BaseModel):
    """Admin request to create a recipe."""
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    category: RecipeCategory
    tags: list[str] = Field(default_factory=list)
    difficulty: RecipeDifficulty = RecipeDifficulty.BEGINNER
    workflow_type: str = Field(default="standard")
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    placeholders: list[RecipePlaceholder] = Field(default_factory=list)


class RecipeInstantiateResponse(BaseModel):
    """Response after instantiating a recipe into a new workflow."""
    workflow_id: str
    workflow_name: str
    placeholders: list[RecipePlaceholder]


class PublishAsRecipeRequest(BaseModel):
    """Request to publish an existing workflow as a recipe."""
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    category: RecipeCategory
    tags: list[str] = Field(default_factory=list)
    difficulty: RecipeDifficulty = RecipeDifficulty.BEGINNER
    placeholders: list[RecipePlaceholder] = Field(default_factory=list)
