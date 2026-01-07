#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Prompt 模板系统测试脚本

用于验证所有 prompt 模板文件是否能正确加载和渲染
"""

from pathlib import Path
import sys

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from autospider.extractor.llm.prompt_template import (
    render_template,
    get_template_sections,
    is_jinja2_available,
)


def _test_single_template(template_name: str, template_path: str):
    """测试单个模板文件"""
    print(f"\n{'='*80}")
    print(f"测试模板: {template_name}")
    print(f"路径: {template_path}")
    print(f"{'='*80}")
    
    try:
        # 获取所有 sections
        sections = get_template_sections(template_path)
        print(f"\n✓ 模板文件加载成功")
        print(f"  可用的 sections: {sections}")
        
        # 测试每个 section 的渲染
        for section in sections:
            print(f"\n--- Section: {section} ---")
            try:
                # 不同模板需要不同的测试变量
                test_variables = get_test_variables(template_name, section)
                
                rendered = render_template(
                    template_path,
                    section=section,
                    variables=test_variables
                )
                
                # 显示前200个字符
                preview = rendered[:200].replace('\n', ' ')
                if len(rendered) > 200:
                    preview += "..."
                
                print(f"  ✓ 渲染成功 ({len(rendered)} 字符)")
                print(f"  预览: {preview}")
                
            except Exception as e:
                print(f"  ✗ 渲染失败: {e}")
                return False
        
        return True
        
    except Exception as e:
        print(f"\n✗ 模板文件加载失败: {e}")
        return False


def get_test_variables(template_name: str, section: str) -> dict:
    """根据模板名称和 section 返回测试变量"""
    
    # planner.yaml 的测试变量
    if template_name == "planner":
        return {
            "start_url": "https://example.com",
            "task": "收集详情页 URL",
            "target_text": "已中标",
        }
    
    # url_collector.yaml 的测试变量
    elif template_name == "url_collector":
        return {
            "task_description": "收集政府采购详情页",
            "current_url": "https://example.com/list",
            "visited_count": 5,
            "collected_urls_str": "- https://example.com/detail/1\n- https://example.com/detail/2",
        }
    
    # script_generator.yaml 的测试变量
    elif template_name == "script_generator":
        return {
            "task_description": "爬取政府采购数据",
            "list_url": "https://example.com/list",
            "nav_summary": "[{\"step\": 1, \"action\": \"click\"}]",
            "visits_count": 3,
            "visits_summary": "[{\"url\": \"https://example.com/detail/1\"}]",
            "urls_count": 10,
            "url_samples": "[\"https://example.com/detail/1\"]",
            "url_pattern_analysis": "{\"base_url\": \"https://example.com\"}",
        }
    
    # 默认返回空字典
    return {}


def main():
    """主测试函数"""
    print("="*80)
    print("Prompt 模板系统测试")
    print("="*80)
    
    # 检查 Jinja2 支持
    jinja2_status = "✓ 已安装" if is_jinja2_available() else "✗ 未安装（仅支持简单变量替换）"
    print(f"\nJinja2 状态: {jinja2_status}")
    
    # 定义所有模板文件
    prompts_dir = project_root / "prompts"
    templates = [
        ("planner", prompts_dir / "planner.yaml"),
        ("decider", prompts_dir / "decider.yaml"),
        ("url_collector", prompts_dir / "url_collector.yaml"),
        ("script_generator", prompts_dir / "script_generator.yaml"),
    ]
    
    # 测试每个模板
    results = {}
    for template_name, template_path in templates:
        if not template_path.exists():
            print(f"\n✗ 模板文件不存在: {template_path}")
            results[template_name] = False
            continue
        
        results[template_name] = _test_single_template(template_name, str(template_path))
    
    # 输出测试总结
    print("\n" + "="*80)
    print("测试总结")
    print("="*80)
    
    all_passed = True
    for template_name, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"{template_name:20s}: {status}")
        if not passed:
            all_passed = False
    
    print("="*80)
    
    if all_passed:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print("\n⚠️ 部分测试失败，请检查上述错误信息")
        return 1


if __name__ == "__main__":
    sys.exit(main())
