import asyncio
from pathlib import Path

from dts_gen.mcp_app.server import build_server


def test_server_registers_all_eight_tools(tmp_path: Path):
    server = build_server(base_dir=tmp_path)

    tools = asyncio.run(server.list_tools())
    tool_names = {tool.name for tool in tools}

    assert tool_names == {
        "ingest_input",
        "extract_hardware_graph",
        "identify_soc_mapping",
        "generate_dts",
        "validate_dts",
        "repair_dts",
        "diff_dts",
        "explain_node",
    }


def test_server_registers_four_resources(tmp_path: Path):
    server = build_server(base_dir=tmp_path)

    # "styleguide://naming" has no {param} in its URI, so the SDK registers
    # it as a static resource (list_resources()), while the other three
    # (soc://{soc}/..., binding://{compatible}, device://{part_number}) are
    # template resources (list_resource_templates()). Together they make up
    # the 4 registered resources.
    resources = asyncio.run(server.list_resources())
    templates = asyncio.run(server.list_resource_templates())

    assert len(resources) + len(templates) == 4
    assert {r.name for r in resources} == {"styleguide_resource"}
    assert {t.name for t in templates} == {"soc_dtsi_resource", "binding_resource", "device_resource"}


def test_server_registers_three_prompts(tmp_path: Path):
    server = build_server(base_dir=tmp_path)

    prompts = asyncio.run(server.list_prompts())
    prompt_names = {p.name for p in prompts}

    assert prompt_names == {"schematic_understanding", "dts_generation", "error_repair"}
