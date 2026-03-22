"""
Workflow recipes router — CRUD + instantiation endpoints.
"""

import uuid
from typing import Optional

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_current_active_user, require_admin, require_automation_role
from app.models.user import User
from app.modules.automation.models.recipe import (
    RecipeCategory,
    RecipePlaceholder,
    WorkflowRecipe,
)
from app.modules.automation.models.workflow import (
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)
from app.modules.automation.schemas.recipe import (
    PublishAsRecipeRequest,
    RecipeCreateRequest,
    RecipeDetailResponse,
    RecipeInstantiateResponse,
    RecipeResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/workflows/recipes", tags=["Recipes"])


def _to_oid(value: str, label: str = "ID") -> PydanticObjectId:
    """Convert a string to PydanticObjectId, raising 400 on invalid format."""
    try:
        return PydanticObjectId(value)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label} format") from exc


def _recipe_to_response(recipe: WorkflowRecipe) -> RecipeResponse:
    return RecipeResponse(
        id=str(recipe.id),
        name=recipe.name,
        description=recipe.description,
        category=recipe.category,
        tags=recipe.tags,
        difficulty=recipe.difficulty,
        workflow_type=recipe.workflow_type,
        node_count=len(recipe.nodes),
        edge_count=len(recipe.edges),
        placeholders=recipe.placeholders,
        built_in=recipe.built_in,
        created_at=recipe.created_at.isoformat() if recipe.created_at else "",
    )


def _recipe_to_detail_response(recipe: WorkflowRecipe) -> RecipeDetailResponse:
    return RecipeDetailResponse(
        id=str(recipe.id),
        name=recipe.name,
        description=recipe.description,
        category=recipe.category,
        tags=recipe.tags,
        difficulty=recipe.difficulty,
        workflow_type=recipe.workflow_type,
        node_count=len(recipe.nodes),
        edge_count=len(recipe.edges),
        placeholders=recipe.placeholders,
        built_in=recipe.built_in,
        created_at=recipe.created_at.isoformat() if recipe.created_at else "",
        nodes=[n.model_dump() for n in recipe.nodes],
        edges=[e.model_dump() for e in recipe.edges],
    )


# ── Public endpoints ──────────────────────────────────────────────────────────


@router.get("", response_model=list[RecipeResponse])
async def list_recipes(
    category: Optional[RecipeCategory] = Query(None),
    _current_user: User = Depends(require_automation_role),
):
    """List all recipes, optionally filtered by category."""
    query = {}
    if category:
        query["category"] = category.value
    recipes = await WorkflowRecipe.find(query).sort("+name").to_list()
    return [_recipe_to_response(r) for r in recipes]


@router.get("/{recipe_id}", response_model=RecipeDetailResponse)
async def get_recipe(
    recipe_id: str,
    _current_user: User = Depends(require_automation_role),
):
    """Get a recipe by ID including full graph data."""
    recipe = await WorkflowRecipe.get(_to_oid(recipe_id, "recipe ID"))
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return _recipe_to_detail_response(recipe)


@router.post("/{recipe_id}/instantiate", response_model=RecipeInstantiateResponse)
async def instantiate_recipe(
    recipe_id: str,
    current_user: User = Depends(require_automation_role),
):
    """Create a new workflow from a recipe template."""
    recipe = await WorkflowRecipe.get(_to_oid(recipe_id, "recipe ID"))
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    # Deep-clone nodes and edges with new UUIDs
    id_map: dict[str, str] = {}
    new_nodes: list[WorkflowNode] = []
    for node in recipe.nodes:
        new_id = str(uuid.uuid4())
        id_map[node.id] = new_id
        new_node = node.model_copy(deep=True)
        new_node.id = new_id
        new_nodes.append(new_node)

    new_edges: list[WorkflowEdge] = []
    for edge in recipe.edges:
        new_edge = edge.model_copy(deep=True)
        new_edge.id = str(uuid.uuid4())
        new_edge.source_node_id = id_map.get(edge.source_node_id, edge.source_node_id)
        new_edge.target_node_id = id_map.get(edge.target_node_id, edge.target_node_id)
        new_edges.append(new_edge)

    # Remap placeholder node_ids
    new_placeholders: list[RecipePlaceholder] = []
    for ph in recipe.placeholders:
        new_ph = ph.model_copy()
        new_ph.node_id = id_map.get(ph.node_id, ph.node_id)
        new_placeholders.append(new_ph)

    # Create the workflow as draft
    workflow = Workflow(
        name=f"{recipe.name}",
        description=recipe.description or None,
        workflow_type=recipe.workflow_type,
        created_by=current_user.id,
        status=WorkflowStatus.DRAFT,
        nodes=new_nodes,
        edges=new_edges,
    )
    await workflow.insert()

    logger.info("recipe_instantiated", recipe_id=recipe_id, workflow_id=str(workflow.id), user=str(current_user.id))

    return RecipeInstantiateResponse(
        workflow_id=str(workflow.id),
        workflow_name=workflow.name,
        placeholders=new_placeholders,
    )


# ── Admin endpoints ───────────────────────────────────────────────────────────


@router.post("", response_model=RecipeResponse, status_code=201)
async def create_recipe(
    request: RecipeCreateRequest,
    current_user: User = Depends(require_admin),
):
    """Create a new recipe (admin only)."""
    recipe = WorkflowRecipe(
        name=request.name,
        description=request.description,
        category=request.category,
        tags=request.tags,
        difficulty=request.difficulty,
        workflow_type=request.workflow_type,
        nodes=[WorkflowNode(**n) for n in request.nodes],
        edges=[WorkflowEdge(**e) for e in request.edges],
        placeholders=request.placeholders,
        built_in=False,
        created_by=current_user.id,
    )
    await recipe.insert()
    return _recipe_to_response(recipe)


@router.delete("/{recipe_id}", status_code=204)
async def delete_recipe(
    recipe_id: str,
    _current_user: User = Depends(require_admin),
):
    """Delete a recipe (admin only, cannot delete built-in recipes)."""
    recipe = await WorkflowRecipe.get(_to_oid(recipe_id, "recipe ID"))
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    if recipe.built_in:
        raise HTTPException(status_code=400, detail="Cannot delete built-in recipes")
    await recipe.delete()


# ── Publish as recipe ─────────────────────────────────────────────────────────


publish_router = APIRouter(prefix="/workflows", tags=["Recipes"])


@publish_router.post("/{workflow_id}/publish-as-recipe", response_model=RecipeResponse)
async def publish_as_recipe(
    workflow_id: str,
    request: PublishAsRecipeRequest,
    current_user: User = Depends(require_admin),
):
    """Publish an existing workflow as a recipe (admin only)."""
    workflow = await Workflow.get(_to_oid(workflow_id, "workflow ID"))
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    # Strip sensitive config values from nodes
    sanitized_nodes: list[WorkflowNode] = []
    for node in workflow.nodes:
        clean_node = node.model_copy(deep=True)
        keys_to_remove = [
            k for k in clean_node.config
            if any(s in k.lower() for s in ("secret", "password", "token", "_set"))
        ]
        for key in keys_to_remove:
            del clean_node.config[key]
        sanitized_nodes.append(clean_node)

    recipe = WorkflowRecipe(
        name=request.name,
        description=request.description,
        category=request.category,
        tags=request.tags,
        difficulty=request.difficulty,
        workflow_type=workflow.workflow_type,
        nodes=sanitized_nodes,
        edges=workflow.edges,
        placeholders=request.placeholders,
        built_in=False,
        created_by=current_user.id,
    )
    await recipe.insert()

    logger.info("workflow_published_as_recipe", workflow_id=workflow_id, recipe_id=str(recipe.id))
    return _recipe_to_response(recipe)
