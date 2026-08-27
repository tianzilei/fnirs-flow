from __future__ import annotations

import numpy as np
import pytest

from fnirs_flow.adapters.vendor_processed_hb import ProcessedHbParseError, parse_vendor_processed_hb


def _write(
    path,
    timestamps=(0, 1, 2, 3),
    *,
    channels=1,
    points=4,
    end_time=None,
    include_hbt=True,
    condition_block="",
):
    fields = ["Time(sec)", "Task", "Mark", "Count"]
    for channel in range(1, channels + 1):
        fields.extend([f"CH{channel} oxyHb", f"CH{channel} deoxyHb"])
        if include_hbt:
            fields.append(f"CH{channel} totalHb")
    rows = []
    for i, timestamp in enumerate(timestamps):
        values = [str(timestamp), "T", "0", str(i)]
        for channel in range(1, channels + 1):
            hbo, hbr = i + channel, i + channel + 1
            values.extend([str(hbo), str(hbr)])
            if include_hbt:
                values.append(str(hbo + hbr))
        rows.append("\t".join(values))
    header = f"[File Information]\nPoints={points}\nChannels={channels}\n"
    if end_time is not None:
        header += f"End Time(sec)={end_time}\n"
    path.write_text(
        header + condition_block + "\t".join(fields) + "\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )


def test_parse_processed_hb_preserves_native_time_and_provenance(tmp_path):
    path = tmp_path / "sample_RE.TXT"
    _write(path)
    recording, qc = parse_vendor_processed_hb(path)
    assert recording.hbo.shape == (1, 4)
    assert recording.channels[0].channel == "ch001"
    assert np.array_equal(recording.native_timestamps_s, [0, 1, 2, 3])
    assert recording.absolute_unit_verified is False
    assert recording.provenance.sha256 and recording.provenance.hbt_check_status == "pass"
    assert qc.status == "pass"


def test_parse_processed_hb_fails_on_duplicate_time(tmp_path):
    path = tmp_path / "bad_RE.TXT"
    _write(path, (0, 1, 1, 3))
    with pytest.raises(ProcessedHbParseError, match="strictly increasing"):
        parse_vendor_processed_hb(path)


def test_parse_42_channels_and_missing_hbt(tmp_path):
    path = tmp_path / "forty_two_RE.TXT"
    _write(path, channels=42, include_hbt=False)
    recording, qc = parse_vendor_processed_hb(path)
    assert recording.hbo.shape == (42, 4)
    assert recording.channels[-1].channel == "ch042"
    assert recording.hbt_validation is None
    assert recording.provenance.hbt_check_status == "unavailable"
    assert qc.status == "pass"


def test_header_point_and_end_time_mismatches_are_audited(tmp_path):
    path = tmp_path / "warnings_RE.TXT"
    _write(path, points=99, end_time=99)
    recording, qc = parse_vendor_processed_hb(path)
    assert set(qc.warnings) == {"HEADER_POINT_COUNT_MISMATCH", "HEADER_END_TIME_MISMATCH"}
    assert recording.provenance.warning_codes == qc.warnings


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda text: text.replace("\tCH1 deoxyHb", ""), "missing HbO/HbR"),
        (
            lambda text: text.replace("CH1 oxyHb", "CH0 oxyHb")
            .replace("CH1 deoxyHb", "CH0 deoxyHb")
            .replace("CH1 totalHb", "CH0 totalHb"),
            "start at 1 and be contiguous",
        ),
        (lambda text: text.replace("\t3\t4\t7\n", "\t3\t4\n", 1), "columns; expected"),
        (lambda text: text.replace("\t3\t4\t7\n", "\t3\t4\t7\textra\n", 1), "columns; expected"),
        (lambda text: text.replace("\t3\t4\t7\n", "\tnan\t4\t7\n", 1), "non-finite"),
    ],
)
def test_malformed_channel_tables_fail_closed(tmp_path, mutator, message):
    path = tmp_path / "malformed_RE.TXT"
    _write(path)
    path.write_text(mutator(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(ProcessedHbParseError, match=message):
        parse_vendor_processed_hb(path)


def test_all_zero_signal_fails_closed(tmp_path):
    path = tmp_path / "zero_RE.TXT"
    _write(path)
    text = path.read_text(encoding="utf-8")
    for hbo in ("1", "2", "3", "4"):
        text = text.replace(f"\t{hbo}\t{int(hbo) + 1}\t{int(hbo) * 2 + 1}\n", f"\t0\t{int(hbo) + 1}\t{int(hbo) + 1}\n")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ProcessedHbParseError, match="all-zero"):
        parse_vendor_processed_hb(path)


def test_partial_hbt_across_channels_fails_as_ambiguous(tmp_path):
    path = tmp_path / "partial_hbt_RE.TXT"
    _write(path, channels=2)
    path.write_text(path.read_text(encoding="utf-8").replace("CH2 totalHb", "Total"), encoding="utf-8")
    with pytest.raises(ProcessedHbParseError, match="partial HbT"):
        parse_vendor_processed_hb(path)


def test_bom_and_reordered_sections_are_supported(tmp_path):
    path = tmp_path / "bom_RE.TXT"
    _write(path)
    text = path.read_text(encoding="utf-8")
    text = "[Comment]\nOwner=test\n" + text.replace("CH1 oxyHb", "  CH1 oxyHb  ")
    path.write_text(text, encoding="utf-8-sig")
    recording, qc = parse_vendor_processed_hb(path)
    assert recording.hbo.shape == (1, 4)
    assert "UTF8_BOM" in qc.warnings


def test_multiple_time_headers_fail_as_ambiguous(tmp_path):
    path = tmp_path / "ambiguous_RE.TXT"
    _write(path)
    text = path.read_text(encoding="utf-8")
    path.write_text("Time(sec)\tOther\n" + text, encoding="utf-8")
    with pytest.raises(ProcessedHbParseError, match="unique Time"):
        parse_vendor_processed_hb(path)


def test_gain_only_condition_is_not_mislabeled_as_voltage(tmp_path):
    path = tmp_path / "gain_RE.TXT"
    _write(
        path,
        condition_block=(
            "[Condition-1]\n"
            "Gain(X1,X4,X16,X64)\n"
            "R1,R2,R3\n"
            "1,4,16\n"
        ),
    )
    recording, _qc = parse_vendor_processed_hb(path)
    metadata = recording.header.sections["Parsed Condition Metadata"]
    assert metadata == {"Amp. Gain": "1,4,16"}


def test_voltage_and_gain_conditions_remain_separate(tmp_path):
    path = tmp_path / "conditions_RE.TXT"
    _write(
        path,
        condition_block=(
            "[Condition-1]\n"
            "R1,R2,R3\n"
            "606,596,1000\n"
            "Gain(X1,X4,X16,X64)\n"
            "R1,R2,R3\n"
            "1,4,16\n"
        ),
    )
    recording, _qc = parse_vendor_processed_hb(path)
    metadata = recording.header.sections["Parsed Condition Metadata"]
    assert metadata == {"Applied Voltage": "606.0,596.0,1000.0", "Amp. Gain": "1,4,16"}


def test_condition_count_mismatch_fails_closed(tmp_path):
    path = tmp_path / "bad_condition_RE.TXT"
    _write(path, condition_block="[Condition-1]\nR1,R2,R3\n606,596,1000,638\n")
    with pytest.raises(ProcessedHbParseError, match="count does not match"):
        parse_vendor_processed_hb(path)


def test_conflicting_repeated_condition_rows_fail_closed(tmp_path):
    path = tmp_path / "ambiguous_condition_RE.TXT"
    _write(
        path,
        condition_block=(
            "[Condition-1]\nR1,R2,R3\n606,596,1000\n"
            "[Condition-2]\nR1,R2,R3\n600,590,990\n"
        ),
    )
    with pytest.raises(ProcessedHbParseError, match="ambiguous repeated Shimadzu voltage"):
        parse_vendor_processed_hb(path)
