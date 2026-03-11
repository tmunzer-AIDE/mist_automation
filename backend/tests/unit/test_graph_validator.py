"""Unit tests for graph validator."""
import pytest

from app.core.exceptions import ValidationError
from app.modules.automation.models.workflow import NodePort, NodePosition, WorkflowEdge, WorkflowNode
from app.modules.automation.services.graph_validator import validate_graph


def _node(id: str, type: str = "mist_api_get", **kw) -> WorkflowNode:
    return WorkflowNode(
        id=id,
        type=type,
        name=kw.get("name", id),
        position=NodePosition(x=0, y=0),
        output_ports=kw.get("output_ports", [NodePort(id="default")]),
    )


def _edge(id: str, src: str, tgt: str, src_port: str = "default", tgt_port: str = "input") -> WorkflowEdge:
    return WorkflowEdge(id=id, source_node_id=src, target_node_id=tgt, source_port_id=src_port, target_port_id=tgt_port)


class TestGraphValidator:
    def test_valid_simple_graph(self):
        nodes = [_node("t", "trigger"), _node("a")]
        edges = [_edge("e1", "t", "a")]
        validate_graph(nodes, edges)  # should not raise

    def test_empty_nodes_raises(self):
        with pytest.raises(ValidationError, match="at least one node"):
            validate_graph([], [])

    def test_no_trigger_raises(self):
        with pytest.raises(ValidationError, match="exactly one trigger"):
            validate_graph([_node("a")], [])

    def test_multiple_triggers_raises(self):
        with pytest.raises(ValidationError, match="exactly one trigger"):
            validate_graph([_node("t1", "trigger"), _node("t2", "trigger")], [])

    def test_orphan_node_raises(self):
        nodes = [_node("t", "trigger"), _node("a"), _node("orphan")]
        edges = [_edge("e1", "t", "a")]
        with pytest.raises(ValidationError, match="not reachable"):
            validate_graph(nodes, edges)

    def test_invalid_edge_source_raises(self):
        nodes = [_node("t", "trigger")]
        edges = [_edge("e1", "nonexistent", "t")]
        with pytest.raises(ValidationError, match="non-existent source"):
            validate_graph(nodes, edges)

    def test_invalid_edge_target_raises(self):
        nodes = [_node("t", "trigger")]
        edges = [_edge("e1", "t", "nonexistent")]
        with pytest.raises(ValidationError, match="non-existent target"):
            validate_graph(nodes, edges)

    def test_duplicate_edge_id_raises(self):
        nodes = [_node("t", "trigger"), _node("a"), _node("b")]
        edges = [_edge("e1", "t", "a"), _edge("e1", "t", "b")]
        with pytest.raises(ValidationError, match="Duplicate edge"):
            validate_graph(nodes, edges)

    def test_cycle_raises(self):
        nodes = [
            _node("t", "trigger"),
            _node("a"),
            _node("b"),
        ]
        edges = [
            _edge("e1", "t", "a"),
            _edge("e2", "a", "b"),
            _edge("e3", "b", "a"),
        ]
        with pytest.raises(ValidationError, match="cycle"):
            validate_graph(nodes, edges)

    def test_branching_graph_valid(self):
        nodes = [
            _node("t", "trigger"),
            _node("c", "condition", output_ports=[NodePort(id="branch_0"), NodePort(id="else")]),
            _node("a"),
            _node("b"),
        ]
        edges = [
            _edge("e1", "t", "c"),
            _edge("e2", "c", "a", src_port="branch_0"),
            _edge("e3", "c", "b", src_port="else"),
        ]
        validate_graph(nodes, edges)  # should not raise

    def test_trigger_only_valid(self):
        nodes = [_node("t", "trigger")]
        validate_graph(nodes, [])  # trigger alone is valid
