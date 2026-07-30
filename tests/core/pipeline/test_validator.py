from dts_gen.core.pipeline.validator import validate_dts


def test_validate_dts_returns_not_implemented_warning_for_empty_text():
    result = validate_dts("")

    assert result.errors == []
    assert len(result.warnings) == 1
    assert "not implemented" in result.warnings[0].message.lower()


def test_validate_dts_returns_not_implemented_warning_for_nonempty_text():
    result = validate_dts("&usb_0 { status = \"okay\"; };")

    assert result.errors == []
    assert len(result.warnings) == 1
