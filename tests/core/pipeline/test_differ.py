from dts_gen.core.pipeline.differ import diff_dts


def test_diff_dts_produces_unified_diff_for_changed_text():
    original = "&usb_0 {\n  status = \"disabled\";\n};\n"
    generated = "&usb_0 {\n  status = \"okay\";\n};\n"

    result = diff_dts(original, generated)

    assert "-  status = \"disabled\";" in result.patch
    assert "+  status = \"okay\";" in result.patch
    assert result.risk_notes == []


def test_diff_dts_returns_empty_patch_for_identical_text():
    text = "&usb_0 {\n  status = \"okay\";\n};\n"

    result = diff_dts(text, text)

    assert result.patch == ""
