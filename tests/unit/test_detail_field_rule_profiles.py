from __future__ import annotations

from autospider.contexts.collection.domain.fields import FieldDefinition
from autospider.contexts.collection.infrastructure.field.field_config import ensure_extraction_config
from autospider.contexts.collection.infrastructure.repositories.field_xpath_repository import (
    FieldXPathQueryService,
)
from autospider.platform.shared_kernel.knowledge_contracts import (
    build_detail_template_signature,
    build_field_semantic_signature,
)


def _field() -> FieldDefinition:
    return FieldDefinition(
        name="title",
        description="标题",
        data_type="text",
        extraction_source="page",
    )


class _FakeFieldXPathQueryService(FieldXPathQueryService):
    def _list_active_xpaths(self, *, repo, domain: str, field_name: str) -> list[str]:  # type: ignore[override]
        _ = repo, domain, field_name
        return []


def test_same_template_same_field_signature_reuses_world_profile() -> None:
    field = _field()
    service = _FakeFieldXPathQueryService()
    url = "https://example.com/detail/1"
    world_snapshot = {
        "world_model": {
            "page_models": {
                "detail": {
                    "metadata": {
                        "detail_field_profiles": [
                            {
                                "field_name": "title",
                                "xpath": "//h1/text()",
                                "validated": True,
                                "detail_template_signature": build_detail_template_signature(
                                    url=url,
                                    page_hint=field.description,
                                ),
                                "field_signature": build_field_semantic_signature(
                                    field_name=field.name,
                                    description=field.description,
                                    data_type=field.data_type,
                                    extraction_source=str(field.extraction_source or ""),
                                ),
                            }
                        ]
                    }
                }
            }
        }
    }

    configs = service.build_fields_config(url, [field], world_snapshot=world_snapshot)

    assert configs[0]["xpath"] == "//h1/text()"
    assert configs[0]["xpath_validated"] is True


def test_same_domain_different_template_does_not_reuse_unrelated_profile() -> None:
    field = _field()
    service = _FakeFieldXPathQueryService()
    world_snapshot = {
        "world_model": {
            "page_models": {
                "detail": {
                    "metadata": {
                        "detail_field_profiles": [
                            {
                                "field_name": "title",
                                "xpath": "//div[@class='headline']/text()",
                                "validated": True,
                                "detail_template_signature": "another-template",
                                "field_signature": build_field_semantic_signature(
                                    field_name=field.name,
                                    description=field.description,
                                    data_type=field.data_type,
                                    extraction_source=str(field.extraction_source or ""),
                                ),
                            }
                        ]
                    }
                }
            }
        }
    }

    configs = service.build_fields_config(
        "https://example.com/detail/2",
        [field],
        world_snapshot=world_snapshot,
    )

    assert configs[0]["xpath"] is None


def test_world_profile_match_keeps_legacy_fallback_path_available() -> None:
    field = _field()
    service = _FakeFieldXPathQueryService()
    configs = service.build_fields_config("https://example.com/detail/3", [field], world_snapshot={})

    assert "detail_template_signature" in configs[0]
    assert "field_signature" in configs[0]


def test_ensure_extraction_config_keeps_profile_signatures() -> None:
    field = _field()
    service = _FakeFieldXPathQueryService()
    raw_fields = service.build_fields_config("https://example.com/detail/4", [field], world_snapshot={})

    extraction_config = ensure_extraction_config({"fields": raw_fields})
    payload = extraction_config.to_payload()

    assert payload["fields"][0]["detail_template_signature"] == raw_fields[0]["detail_template_signature"]
    assert payload["fields"][0]["field_signature"] == raw_fields[0]["field_signature"]
