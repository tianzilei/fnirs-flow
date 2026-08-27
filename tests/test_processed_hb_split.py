import json
from pathlib import Path

import numpy as np

from fnirs_flow.adapters.processed_hb_split import save_split_processed_hb, split_processed_hb
from fnirs_flow.adapters.vendor_processed_hb import parse_vendor_processed_hb


def _recording(tmp_path: Path):
    source = tmp_path / "synthetic_RE.TXT"
    source.write_text(
        "[File Information]\n"
        "Points=4\n"
        "Channels=3\n"
        "Time(sec)\tTask\tMark\tCount\t"
        "CH1 oxyHb\tCH1 deoxyHb\tCH1 totalHb\t"
        "CH2 oxyHb\tCH2 deoxyHb\tCH2 totalHb\t"
        "CH3 oxyHb\tCH3 deoxyHb\tCH3 totalHb\n"
        "0\tA\t0\t0\t1\t2\t3\t2\t3\t5\t3\t4\t7\n"
        "1\tA\t0\t1\t2\t3\t5\t3\t4\t7\t4\t5\t9\n"
        "2\tB\t1\t2\t3\t4\t7\t4\t5\t9\t5\t6\t11\n"
        "3\tB\t0\t3\t4\t5\t9\t5\t6\t11\t6\t7\t13\n",
        encoding="utf-8",
    )
    recording, _qc = parse_vendor_processed_hb(source)
    return recording


def test_split_channels_and_time_window_and_export(tmp_path: Path):
    data = _recording(tmp_path)
    split = split_processed_hb(data, channels=[1, 3], time_window_s=(1.0, 2.0))
    assert split.n_channels == 2
    assert split.n_samples > 0
    assert np.all((split.time_s >= 1.0) & (split.time_s <= 2.0))
    csv_path = save_split_processed_hb(split, tmp_path / "split.csv")
    json_path = save_split_processed_hb(split, tmp_path / "split.json")
    npz_path = save_split_processed_hb(split, tmp_path / "split.npz")
    assert csv_path.exists() and json_path.exists() and npz_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["channel_indices"] == [1, 3]
    assert payload["source_provenance"]["parser_name"] == "vendor_processed_hb"
    with np.load(npz_path) as archive:
        assert archive["channel_indices"].tolist() == [1, 3]
        assert json.loads(str(archive["source_provenance_json"]))["parser_name"] == "vendor_processed_hb"


def test_explicit_npz_format_does_not_change_output_path(tmp_path: Path):
    split = split_processed_hb(_recording(tmp_path), channels=[1])
    output = save_split_processed_hb(split, tmp_path / "split.bin", fmt="npz")
    assert output == tmp_path / "split.bin"
    assert output.exists()
    assert not (tmp_path / "split.bin.npz").exists()
