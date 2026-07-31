import pytest
from unittest.mock import Mock, patch

from dts_gen.core.knowledge.spec_sync.fetcher import FetchError, TrackedFile, fetch, list_rst_files

GPIO_BINDING_URL = (
    "https://raw.githubusercontent.com/torvalds/linux/master/"
    "Documentation/devicetree/bindings/gpio/gpio.txt"
)
DT_SPEC_CONTENTS_API_URL = (
    "https://api.github.com/repos/devicetree-org/devicetree-specification/contents/source"
)


def test_fetch_returns_nonempty_text_for_real_url():
    text = fetch(GPIO_BINDING_URL)

    assert isinstance(text, str)
    assert len(text) > 0


def test_fetch_raises_fetch_error_for_invalid_url():
    with pytest.raises(FetchError):
        fetch("https://raw.githubusercontent.com/does-not-exist/does-not-exist/main/nope.txt")


def test_list_rst_files_returns_only_rst_files_from_source_root():
    files = list_rst_files(DT_SPEC_CONTENTS_API_URL)

    assert len(files) > 0
    assert all(isinstance(f, TrackedFile) for f in files)
    assert all(f.filename.endswith(".rst") for f in files)
    assert all("/extensions/" not in f.source_url for f in files)


def test_list_rst_files_raises_fetch_error_for_invalid_api_url():
    with pytest.raises(FetchError):
        list_rst_files("https://api.github.com/repos/does-not-exist/does-not-exist/contents/source")


def test_list_rst_files_raises_fetch_error_for_non_list_response():
    # Pointing the Contents API at a single file (not a directory) returns
    # a JSON object, not a list — this must surface as FetchError, not AttributeError.
    file_contents_api_url = (
        "https://api.github.com/repos/devicetree-org/devicetree-specification/"
        "contents/source/index.rst"
    )

    with pytest.raises(FetchError):
        list_rst_files(file_contents_api_url)


def test_list_rst_files_raises_fetch_error_for_invalid_json_body():
    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.json.side_effect = ValueError("invalid json")

    with patch("requests.get", return_value=fake_response):
        with pytest.raises(FetchError):
            list_rst_files("https://api.github.com/repos/does-not-matter/does-not-matter/contents/source")
