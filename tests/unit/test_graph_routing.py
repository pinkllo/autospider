from autospider.graph.main_graph import resolve_chat_review_route, resolve_entry_route
from autospider.graph.nodes.entry_nodes import _resolve_chat_dispatch_mode


def test_resolve_entry_route_mapping():
    assert resolve_entry_route({"entry_mode": "chat_pipeline"}) == "chat_clarify"
    assert resolve_entry_route({"entry_mode": "pipeline_run"}) == "normalize_pipeline_params"
    assert resolve_entry_route({"entry_mode": "collect_urls"}) == "finalize_result"
    assert resolve_entry_route({"entry_mode": "generate_config"}) == "finalize_result"
    assert resolve_entry_route({"entry_mode": "batch_collect"}) == "finalize_result"
    assert resolve_entry_route({"entry_mode": "field_extract"}) == "finalize_result"
    assert resolve_entry_route({"entry_mode": "multi_pipeline"}) == "finalize_result"


def test_chat_dispatch_mode_is_fixed_to_multi_for_chat_pipeline():
    assert _resolve_chat_dispatch_mode() == "multi"


def test_chat_pipeline_review_approval_hands_off_into_planning_path():
    assert resolve_chat_review_route({"node_status": "ok", "chat_review_state": "approved"}) == "chat_prepare_execution_handoff"


def test_resolve_entry_route_fallback():
    assert resolve_entry_route({"entry_mode": "unknown"}) == "finalize_result"
