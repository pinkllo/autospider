from __future__ import annotations

from autospider.contexts.collection.domain import (
    CollectionRun,
    FieldBinding,
    FieldDefinition,
    PageResult,
    VariantResolver,
    XPathPattern,
    append_page_result,
)


def test_collection_run_summary_counts_success_and_failure() -> None:
    run = CollectionRun(
        run_id="run-1",
        plan_id="plan-1",
        subtask_id="subtask-1",
        thread_id="thread-1",
    )
    run = append_page_result(run, PageResult(url="https://a", status="succeeded"))
    run = append_page_result(run, PageResult(url="https://b", status="failed"))
    summary = run.summarize()

    assert summary["total_urls"] == 2
    assert summary["success_count"] == 1
    assert summary["failure_count"] == 1


def test_field_binding_and_variant_resolver_are_serializable() -> None:
    binding = FieldBinding(
        field=FieldDefinition(name="title", description="标题"),
        pattern=XPathPattern(xpath="//div/a"),
        source="xpath",
    )

    assert binding.to_payload()["field"]["name"] == "title"
    assert VariantResolver().resolve_label({"category": "公告"}) == "公告"
