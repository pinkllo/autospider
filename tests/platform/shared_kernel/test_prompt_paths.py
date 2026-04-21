from __future__ import annotations

from pathlib import Path

from autospider.platform.shared_kernel.utils.paths import get_package_root, get_prompt_path
from autospider.platform.shared_kernel.utils.prompt_template import render_shared_rules


def test_get_package_root_points_to_autospider_package() -> None:
    package_root = get_package_root()

    assert package_root.name == "autospider"
    assert (package_root / "prompts" / "skill_selector.yaml").exists()


def test_get_prompt_path_resolves_existing_prompt_file() -> None:
    prompt_path = Path(get_prompt_path("skill_selector.yaml"))

    assert prompt_path.name == "skill_selector.yaml"
    assert prompt_path.exists()
    assert "platform" not in prompt_path.parts[-3:-1]


def test_render_shared_rules_reads_shared_prompt_sections() -> None:
    rendered = render_shared_rules(["output_rules"])

    assert rendered.strip()
    assert "JSON" in rendered
