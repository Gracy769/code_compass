"""Mermaid diagrams must remain valid when repositories contain unusual names."""

import re

from code_compass.analysis.tagger import generate_mermaid_architecture


def test_mermaid_labels_cannot_break_node_or_subgraph_syntax():
    files = [
        {"path": 'src/bad"]\n  injected --> node_2;.ts', "layer": "ui", "rank_score": 9},
        {"path": ".env", "layer": "infra", "rank_score": 8},
        {"path": "src/über [files].py", "layer": 'api"]\n  attacker', "rank_score": 7},
    ]
    diagram = generate_mermaid_architecture(files, [], repo_name="repo\nattacker --> node_2")

    definitions = [line.strip() for line in diagram.splitlines() if re.match(r"\s*node_\d+\[", line)]
    assert len(definitions) == 3
    assert all(re.fullmatch(r'node_\d+\["[\w .-]+"\]', line) for line in definitions)
    assert 'node_2[".env"]' in definitions
    assert "injected --> node_2" not in diagram
    assert "attacker --> node_2" not in diagram
    subgraphs = [line.strip() for line in diagram.splitlines() if line.strip().startswith("subgraph ")]
    assert all(re.fullmatch(r'subgraph sub_[A-Za-z0-9_]+ \["[\w .-]+"\]', line) for line in subgraphs)


def test_mermaid_keeps_ranked_nodes_and_real_edges():
    files = [
        {"path": "src/main.py", "layer": "core", "rank_score": 8},
        {"path": "src/service.py", "layer": "service", "rank_score": 5},
    ]
    symbols = [{"name": "main", "file": "src/main.py"}, {"name": "serve", "file": "src/service.py"}]
    edges = [{"caller": "main", "callee": "serve"}]
    diagram = generate_mermaid_architecture(files, edges, symbols=symbols)
    assert 'node_1["main"]' in diagram
    assert 'node_2["service"]' in diagram
    assert "node_1 --> node_2" in diagram
    assert "class node_1,node_2 tier1;" in diagram
