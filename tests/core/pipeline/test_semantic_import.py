from dts_gen.core.pipeline.semantic_import import parse_connected_label


def test_parse_connected_label_extracts_designator_and_pin():
    assert parse_connected_label("R3 pin 1") == ("R3", "1")


def test_parse_connected_label_handles_alphanumeric_pin():
    assert parse_connected_label("SU1C pin G37") == ("SU1C", "G37")


def test_parse_connected_label_handles_no_space_before_pin_number():
    assert parse_connected_label("R544 pin2") == ("R544", "2")


def test_parse_connected_label_returns_none_for_single_bracket_reference():
    assert parse_connected_label("[22]") is None


def test_parse_connected_label_returns_none_for_multi_page_bracket_reference():
    assert parse_connected_label("[7,37,8]") is None


def test_parse_connected_label_returns_none_for_coordinate_bracket_reference():
    assert parse_connected_label("[47-C4,47-D4]") is None


def test_parse_connected_label_returns_none_for_bare_net_name():
    assert parse_connected_label("VDD_CX") is None


def test_parse_connected_label_returns_none_for_ground_label():
    assert parse_connected_label("GND") is None


def test_parse_connected_label_returns_none_for_uncertain_designator():
    assert parse_connected_label("C? pin 1") is None
