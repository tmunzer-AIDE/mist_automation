# Workflow Editor

Part of mist_automation — see root `CLAUDE.md` for global architecture and `frontend/CLAUDE.md` for Angular patterns.

## Architecture

The workflow editor (`features/workflows/editor/`) is an n8n-style node graph editor:

- **Data model**: Workflows use `WorkflowNode[]` + `WorkflowEdge[]` (not a linear pipeline). Each node has `id`, `type`, `position: {x, y}`, `config`, `output_ports[]`. Edges connect `source_node_id:source_port_id` → `target_node_id:target_port_id`.
- **SVG graph canvas** (`editor/canvas/graph-canvas.component`): Raw SVG with pointer events for pan (middle-click/Ctrl+drag), zoom (scroll wheel 0.25–2.0x), node drag, edge creation (drag from output port to input port). Nodes rendered via `<foreignObject>` for Material icons. Edges rendered as cubic Bezier `<path>` elements. Snap-to-grid on node move.
- **Node config panel** (`editor/config/node-config-panel.component`): Side panel that configures the selected node. Uses reactive forms with dynamic FormArrays. The **emit guard pattern** (`private emitting = false`) prevents `ngOnChanges` from rebuilding the form when changes originate from the component's own `configChanged` emission.
- **Variable picker** (`editor/config/variable-picker.component`): Tree view of upstream node output variables. Queries backend for available variables per node. Click-to-insert `{{ variable.path }}` at cursor position.
- **Simulation panel** (`editor/simulation/simulation-panel.component`): Bottom panel for workflow dry-run and step-by-step debugging. Pick a payload (JSON editor or recent webhook events), run simulation, replay node snapshots with per-node input/output inspection and visual execution status on the canvas.
- **Palette sidebar** (`editor/palette/block-palette-sidebar.component`): Uses native HTML drag-and-drop (`draggable="true"` + `dragstart` event setting `dataTransfer`), NOT CDK drag-drop. Emits action type string.
- **Action metadata**: `ACTION_META` in `core/models/workflow-meta.ts` is the single source of truth for action type icons, colors, labels, and default output ports — do not duplicate.
- **API catalog** fetched from backend, filtered by HTTP method matching action type, with dynamic path/query parameter inputs.
- **Port-based branching**: Condition nodes have `branch_0`/`branch_1`/`else` output ports. For-each nodes have `loop_body`/`done` output ports. Trigger nodes have no input port, only a `default` output port.
- **Sub-flow support**: Workflows have a `workflow_type` (`standard` or `subflow`). Sub-flows use `subflow_input` (entry, no input port) and `subflow_output` (terminal, no output ports) nodes. Standard workflows invoke sub-flows via `invoke_subflow` action nodes. The palette conditionally shows `subflow_output` only when editing a subflow. Config panel has specialized sections for `subflow_input` (editable parameter list), `invoke_subflow` (target picker + input mappings), and `subflow_output` (output expression editors).
- **Execution results**: `node_results: Record<string, NodeExecutionResult>` dict keyed by node_id (not a flat array).
