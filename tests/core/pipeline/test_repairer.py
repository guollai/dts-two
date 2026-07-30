from dts_gen.core.pipeline.repairer import repair_dts


def test_repair_dts_returns_input_unchanged_with_no_fixes():
    original = "&usb_0 { status = \"okay\"; };"

    result = repair_dts(original, errors=[])

    assert result.dts_text == original
    assert result.applied_fixes == []
