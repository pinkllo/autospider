from autospider.graph.main_graph import resolve_entry_route


def test_resolve_entry_route_mapping():
    assert resolve_entry_route({"entry_mode": "chat_pipeline"}) == "chat_clarify"
    assert resolve_entry_route({"entry_mode": "pipeline_run"}) == "normalize_pipeline_params"
    assert resolve_entry_route({"entry_mode": "collect_urls"}) == "collect_urls_node"
    assert resolve_entry_route({"entry_mode": "generate_config"}) == "generate_config_node"
    assert resolve_entry_route({"entry_mode": "batch_collect"}) == "batch_collect_node"
    assert resolve_entry_route({"entry_mode": "field_extract"}) == "field_extract_node"
    assert resolve_entry_route({"entry_mode": "multi_pipeline"}) == "plan_node"


def test_resolve_entry_route_fallback():
    assert resolve_entry_route({"entry_mode": "unknown"}) == "finalize_result"
