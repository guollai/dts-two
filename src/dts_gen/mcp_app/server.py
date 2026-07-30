from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from dts_gen.mcp_app import prompts as prompt_templates
from dts_gen.mcp_app import resources as knowledge
from dts_gen.mcp_app import tools


def build_server(base_dir: Path) -> MCPServer:
    server = MCPServer(name="dts-gen")

    tool_ctx = tools.build_tool_context(base_dir=base_dir)
    knowledge_ctx = knowledge.build_knowledge_context(data_dir=base_dir / "knowledge")

    @server.tool()
    def ingest_input(files: list[dict], project: str, soc: str | None = None, board: str | None = None) -> dict:
        return tools.ingest_input(tool_ctx, files=files, project=project, soc=soc, board=board)

    @server.tool()
    def extract_hardware_graph(task_id: str, page_range: list[int] | None = None) -> dict:
        return tools.extract_hardware_graph(tool_ctx, task_id=task_id, page_range=page_range)

    @server.tool()
    def identify_soc_mapping(task_id: str, soc: str) -> dict:
        return tools.identify_soc_mapping(tool_ctx, task_id=task_id, soc=soc)

    @server.tool()
    def generate_dts(task_id: str, scope: dict | None = None) -> dict:
        return tools.generate_dts(tool_ctx, task_id=task_id, scope=scope)

    @server.tool()
    def validate_dts(task_id: str) -> dict:
        return tools.validate_dts(tool_ctx, task_id=task_id)

    @server.tool()
    def repair_dts(task_id: str) -> dict:
        return tools.repair_dts(tool_ctx, task_id=task_id)

    @server.tool()
    def diff_dts(task_id: str, existing_dts_path: str) -> dict:
        return tools.diff_dts(tool_ctx, task_id=task_id, existing_dts_path=existing_dts_path)

    @server.tool()
    def explain_node(task_id: str, node_path: str) -> dict:
        return tools.explain_node(tool_ctx, task_id=task_id, node_path=node_path)

    @server.resource("soc://{soc}/dtsi/main")
    def soc_dtsi_resource(soc: str) -> dict:
        return knowledge.read_soc_dtsi(knowledge_ctx, soc=soc)

    @server.resource("binding://{compatible}")
    def binding_resource(compatible: str) -> dict:
        return knowledge.read_binding(knowledge_ctx, compatible=compatible)

    @server.resource("device://{part_number}")
    def device_resource(part_number: str) -> dict:
        return knowledge.read_device(knowledge_ctx, part_number=part_number)

    @server.resource("styleguide://naming")
    def styleguide_resource() -> dict:
        return knowledge.read_styleguide(knowledge_ctx)

    @server.prompt(name="schematic_understanding")
    def schematic_understanding_prompt() -> str:
        return prompt_templates.SCHEMATIC_UNDERSTANDING_PROMPT

    @server.prompt(name="dts_generation")
    def dts_generation_prompt(ir_summary: str) -> str:
        return prompt_templates.render_prompt(
            prompt_templates.DTS_GENERATION_PROMPT, ir_summary=ir_summary
        )

    @server.prompt(name="error_repair")
    def error_repair_prompt(validate_report: str) -> str:
        return prompt_templates.render_prompt(
            prompt_templates.ERROR_REPAIR_PROMPT, validate_report=validate_report
        )

    return server


def main() -> None:
    default_base_dir = Path.cwd() / ".dts-gen" / "tasks"
    server = build_server(base_dir=default_base_dir)
    server.run(transport="stdio")
