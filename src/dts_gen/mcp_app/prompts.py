from __future__ import annotations

SCHEMATIC_UNDERSTANDING_PROMPT = """\
你正在识别一张硬件原理图。只输出结构化的器件、引脚、网络识别结果（Component/Net/Relation），
不要直接编写 DTS 代码。对识别不确定的字段，明确标记为待确认项，不要猜测填充。
"""

DTS_GENERATION_PROMPT = """\
基于以下中间表示（IR）生成 devicetree 片段，严格依据 IR 和已有 binding 资源，
不可编造寄存器地址、IRQ 编号、GPIO 编号或 compatible 字符串。

IR 摘要：
{ir_summary}
"""

ERROR_REPAIR_PROMPT = """\
根据以下校验报告，对 devicetree 代码做最小化修复，不要修改与报告无关的节点。

校验报告：
{validate_report}
"""


def render_prompt(template: str, **variables: str) -> str:
    return template.format(**variables)
