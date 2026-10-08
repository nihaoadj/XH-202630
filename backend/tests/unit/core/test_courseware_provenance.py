from app.core.courseware.provenance import build_provenance_graph, validate_provenance_graph


def snapshots():
    return [{
        "resource_id": "source-1", "content_hash": "a" * 64,
        "blocks": [{"block_id": "block-1", "text": "来源内容"}],
    }]


def document():
    return {
        "title": "课件",
        "scenes": [{
            "kind": "intro", "title": "标题", "blocks": ["正文"],
            "source_refs": ["source-1"], "source_block_ids": ["block-1"],
            "source_map": {"title": [["block-1"]], "blocks": [["block-1"]]},
            "component_blocks": [{
                "block_id": "component-1", "component": "callout", "text": "正文",
                "source_refs": [{"source_resource_id": "source-1", "source_block_ids": ["block-1"]}],
            }],
        }],
    }


def test_provenance_graph_covers_visible_fields_and_is_manifest_safe():
    graph = build_provenance_graph(document(), snapshots())
    assert graph.coverage == 1.0
    assert validate_provenance_graph(graph) == []
    manifest = graph.as_manifest()
    assert manifest["root_hash"] == graph.root_hash
    assert all("text" not in node.get("metadata", {}) for node in manifest["nodes"])


def test_unknown_source_block_is_a_stable_hard_gate():
    invalid = document()
    invalid["scenes"][0]["source_block_ids"] = ["missing-block"]
    invalid["scenes"][0]["source_map"]["title"] = [["missing-block"]]
    graph = build_provenance_graph(invalid, snapshots())
    codes = {item["code"] for item in validate_provenance_graph(graph)}
    assert "PROVENANCE_UNKNOWN_SOURCE_BLOCK" in codes
    assert "PROVENANCE_FIELD_COVERAGE_INCOMPLETE" in codes


def test_cross_snapshot_edge_is_rejected():
    graph = build_provenance_graph(document(), snapshots())
    index = next(index for index, edge in enumerate(graph.edges) if edge.source_node_id.startswith("block:") and edge.target_node_id.startswith("field:"))
    edges = list(graph.edges)
    edges[index] = edges[index].model_copy(update={"snapshot_hash": "b" * 64})
    graph = graph.model_copy(update={"edges": edges})
    assert any(item["code"] == "PROVENANCE_CROSS_SNAPSHOT" for item in validate_provenance_graph(graph))
