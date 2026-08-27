from pathlib import Path

import pytest

from fnirs_flow.adapters.shimadzu_layout import ShimadzuLayoutError, read_shimadzu_layout


def test_text_shimadzu_layout_extracts_only_labelled_wavelengths(tmp_path: Path):
    path = tmp_path / "layout.inf"
    path.write_text("[Acquisition]\nWavelengths_nm = 780, 805, 830\nGain = 16\n", encoding="utf-8")
    result = read_shimadzu_layout(path)
    assert result["is_binary"] is False
    assert result["wavelengths_nm"] == [780.0, 805.0, 830.0]
    assert result["metadata_status"] == "parsed"


@pytest.mark.parametrize("content", [b"not a Shimadzu layout", b"\x00\x01\xffbinary"])
def test_unknown_or_binary_layouts_fail_closed(tmp_path: Path, content: bytes):
    path = tmp_path / "layout.inf"
    path.write_bytes(content)
    with pytest.raises(ShimadzuLayoutError):
        read_shimadzu_layout(path)


def test_malformed_text_layout_has_domain_error(tmp_path: Path):
    path = tmp_path / "layout.ini"
    path.write_text("[broken", encoding="utf-8")
    with pytest.raises(ShimadzuLayoutError, match="invalid Shimadzu text layout"):
        read_shimadzu_layout(path)
