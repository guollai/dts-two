import shutil
import subprocess
from unittest.mock import patch

from dts_gen.core.pipeline.validator import (
    check_duplicate_labels,
    check_property_syntax,
    check_undefined_references,
    find_defined_labels,
    find_referenced_labels,
    run_dtc_check,
    validate_dts,
)


def test_find_defined_labels_extracts_label_names():
    text = '&usb_ctrl0 {\n    status = "okay";\n};\n\n&redriver0 {\n    status = "okay";\n};'

    assert find_defined_labels(text) == {"usb_ctrl0", "redriver0"}


def test_find_referenced_labels_extracts_phandle_references():
    text = '&usb_ctrl0 {\n    vbus-supply = <&pmic_ldo3>;\n};'

    assert find_referenced_labels(text) == {"pmic_ldo3"}


def test_check_undefined_references_reports_missing_target():
    text = '&usb_ctrl0 {\n    vbus-supply = <&pmic_ldo3>;\n};'

    errors = check_undefined_references(text)

    assert len(errors) == 1
    assert "pmic_ldo3" in errors[0].message
    assert errors[0].severity == "error"


def test_check_undefined_references_passes_when_target_defined():
    text = '&usb_ctrl0 {\n    vbus-supply = <&pmic_ldo3>;\n};\n\n&pmic_ldo3 {\n    status = "okay";\n};'

    assert check_undefined_references(text) == []


def test_check_property_syntax_reports_missing_angle_brackets():
    text = '&usb_ctrl0 {\n    vbus-supply = &pmic_ldo3;\n};'

    errors = check_property_syntax(text)

    assert len(errors) == 1
    assert "vbus-supply" in errors[0].message


def test_check_property_syntax_reports_missing_quotes_for_status():
    text = '&usb_ctrl0 {\n    status = okay;\n};'

    errors = check_property_syntax(text)

    assert len(errors) == 1
    assert "status" in errors[0].message


def test_check_property_syntax_passes_for_well_formed_properties():
    text = '&usb_ctrl0 {\n    status = "okay";\n    vbus-supply = <&pmic_ldo3>;\n};'

    assert check_property_syntax(text) == []


def test_check_duplicate_labels_reports_repeated_definition():
    text = '&usb_ctrl0 {\n    status = "okay";\n};\n\n&usb_ctrl0 {\n    status = "okay";\n};'

    errors = check_duplicate_labels(text)

    assert len(errors) == 1
    assert "usb_ctrl0" in errors[0].message


def test_check_duplicate_labels_passes_for_unique_labels():
    text = '&usb_ctrl0 {\n    status = "okay";\n};\n\n&redriver0 {\n    status = "okay";\n};'

    assert check_duplicate_labels(text) == []


def test_validate_dts_returns_no_errors_for_well_formed_text():
    text = '&usb_ctrl0 {\n    status = "okay";\n    vbus-supply = <&pmic_ldo3>;\n};\n\n&pmic_ldo3 {\n    status = "okay";\n};'

    with patch.object(shutil, "which", return_value=None):
        result = validate_dts(text)

    assert result.errors == []


def test_validate_dts_returns_empty_for_empty_text():
    with patch.object(shutil, "which", return_value=None):
        result = validate_dts("")

    assert result.errors == []


def test_validate_dts_warns_when_dtc_not_installed():
    with patch.object(shutil, "which", return_value=None):
        result = validate_dts("")

    assert len(result.warnings) == 1
    assert "dtc" in result.warnings[0].message.lower()


def test_validate_dts_aggregates_multiple_error_types():
    text = (
        '&usb_ctrl0 {\n'
        '    status = okay;\n'
        '    vbus-supply = <&pmic_ldo3>;\n'
        '};\n\n'
        '&usb_ctrl0 {\n'
        '    status = "okay";\n'
        '};'
    )

    with patch.object(shutil, "which", return_value=None):
        result = validate_dts(text)

    messages = [e.message for e in result.errors]
    assert any("pmic_ldo3" in m for m in messages)
    assert any("status" in m for m in messages)
    assert any("usb_ctrl0" in m and "重复" in m for m in messages)


def test_validate_dts_calls_run_dtc_check_when_dtc_available():
    with patch.object(shutil, "which", return_value="/usr/bin/dtc"):
        with patch(
            "dts_gen.core.pipeline.validator.run_dtc_check", return_value=[]
        ) as mock_check:
            result = validate_dts('&usb_ctrl0 { status = "okay"; };')

    mock_check.assert_called_once()
    assert result.warnings == []


def test_run_dtc_check_returns_empty_list_on_success():
    fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("subprocess.run", return_value=fake_result):
        errors = run_dtc_check('&usb_ctrl0 { status = "okay"; };')

    assert errors == []


def test_run_dtc_check_parses_stderr_lines_into_errors_on_failure():
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="ERROR: line 3: syntax error\n"
    )
    with patch("subprocess.run", return_value=fake_result):
        errors = run_dtc_check("garbage input")

    assert len(errors) == 1
    assert "syntax error" in errors[0].message
