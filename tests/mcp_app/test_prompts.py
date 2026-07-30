from dts_gen.mcp_app.prompts import (
    DTS_GENERATION_PROMPT,
    ERROR_REPAIR_PROMPT,
    SCHEMATIC_UNDERSTANDING_PROMPT,
    render_prompt,
)


def test_schematic_understanding_prompt_forbids_direct_dts_writing():
    assert "DTS" in SCHEMATIC_UNDERSTANDING_PROMPT
    assert "{ir_summary}" not in SCHEMATIC_UNDERSTANDING_PROMPT  # 无变量的通用引导语


def test_dts_generation_prompt_has_ir_summary_placeholder():
    assert "{ir_summary}" in DTS_GENERATION_PROMPT


def test_error_repair_prompt_has_validate_report_placeholder():
    assert "{validate_report}" in ERROR_REPAIR_PROMPT


def test_render_prompt_substitutes_variables():
    rendered = render_prompt(DTS_GENERATION_PROMPT, ir_summary="5 components, 8 nets")

    assert "5 components, 8 nets" in rendered
    assert "{ir_summary}" not in rendered
