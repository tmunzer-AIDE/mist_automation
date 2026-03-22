import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export interface RecipePlaceholder {
  node_id: string;
  field_path: string;
  label: string;
  description: string;
  placeholder_type: string;
}

export interface RecipeResponse {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  difficulty: string;
  workflow_type: string;
  node_count: number;
  edge_count: number;
  placeholders: RecipePlaceholder[];
  built_in: boolean;
  created_at: string;
}

export interface RecipeDetailResponse extends RecipeResponse {
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
}

export interface RecipeInstantiateResponse {
  workflow_id: string;
  workflow_name: string;
  placeholders: RecipePlaceholder[];
}

@Injectable({ providedIn: 'root' })
export class RecipeService {
  private readonly api = inject(ApiService);

  list(category?: string): Observable<RecipeResponse[]> {
    const params: Record<string, string> = {};
    if (category) params['category'] = category;
    return this.api.get<RecipeResponse[]>('/workflows/recipes', params);
  }

  get(id: string): Observable<RecipeDetailResponse> {
    return this.api.get<RecipeDetailResponse>(`/workflows/recipes/${id}`);
  }

  instantiate(id: string): Observable<RecipeInstantiateResponse> {
    return this.api.post<RecipeInstantiateResponse>(`/workflows/recipes/${id}/instantiate`, {});
  }

  publishAsRecipe(
    workflowId: string,
    data: { name: string; description: string; category: string; difficulty: string; tags: string[]; placeholders: RecipePlaceholder[] }
  ): Observable<RecipeResponse> {
    return this.api.post<RecipeResponse>(`/workflows/${workflowId}/publish-as-recipe`, data);
  }

  delete(id: string): Observable<void> {
    return this.api.delete<void>(`/workflows/recipes/${id}`);
  }
}
