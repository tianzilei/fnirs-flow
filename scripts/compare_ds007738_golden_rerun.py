"""Compare ds007738 golden-path results with an imported-package rerun."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_REFERENCE = PROJECT_ROOT / "outputs" / "ds007738_golden_path"
DEFAULT_RERUN = PROJECT_ROOT / "outputs" / "ds007738_cross_env_v1"
REPORT_PATH = PROJECT_ROOT / "docs" / "audit" / f"ds007738_reproducibility_{date.today().isoformat()}.md"
RTOL = 1e-8
ATOL = 1e-10


def flatten_values(value: Any, prefix: str = "$") -> tuple[dict[str, float], dict[str, Any]]:
    """Flatten JSON into numeric and nonnumeric leaves for comparison."""
    numeric: dict[str, float] = {}
    metadata: dict[str, Any] = {}
    if isinstance(value, bool):
        metadata[prefix] = value
    elif isinstance(value, (int, float)):
        numeric[prefix] = float(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            child_numeric, child_metadata = flatten_values(item, f"{prefix}.{key}")
            numeric.update(child_numeric)
            metadata.update(child_metadata)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child_numeric, child_metadata = flatten_values(item, f"{prefix}[{index}]")
            numeric.update(child_numeric)
            metadata.update(child_metadata)
    else:
        metadata[prefix] = value
    return numeric, metadata


def result_json_files(root: Path) -> dict[str, Path]:
    files = {}
    for relative_dir in ("derivatives/channel", "derivatives/roi", "derivatives/group"):
        directory = root / relative_dir
        for path in directory.glob("*.json"):
            if not path.name.startswith("._"):
                files[path.relative_to(root).as_posix()] = path
    return files


def compare_result_trees(reference: Path, rerun: Path) -> dict[str, Any]:
    reference_files = result_json_files(reference)
    rerun_files = result_json_files(rerun)
    missing = sorted(set(reference_files) - set(rerun_files))
    unexpected = sorted(set(rerun_files) - set(reference_files))
    elements = 0
    failures = []
    max_abs_difference = 0.0
    metadata_mismatches = []
    for relative in sorted(set(reference_files) & set(rerun_files)):
        expected = json.loads(reference_files[relative].read_text(encoding="utf-8"))
        actual = json.loads(rerun_files[relative].read_text(encoding="utf-8"))
        expected_numbers, expected_metadata = flatten_values(expected)
        actual_numbers, actual_metadata = flatten_values(actual)
        if expected_metadata != actual_metadata:
            metadata_mismatches.append(relative)
        if set(expected_numbers) != set(actual_numbers):
            failures.append(f"{relative}: numeric schema differs")
            continue
        for location, expected_value in expected_numbers.items():
            actual_value = actual_numbers[location]
            elements += 1
            difference = abs(expected_value - actual_value)
            max_abs_difference = max(max_abs_difference, difference)
            if not np.isclose(actual_value, expected_value, rtol=RTOL, atol=ATOL):
                failures.append(f"{relative}:{location}")
    return {
        "files_compared": len(set(reference_files) & set(rerun_files)),
        "numeric_elements": elements,
        "rtol": RTOL,
        "atol": ATOL,
        "max_abs_difference": max_abs_difference,
        "numeric_failures": failures,
        "metadata_mismatches": metadata_mismatches,
        "missing_files": missing,
        "unexpected_files": unexpected,
        "passed": not (failures or metadata_mismatches or missing or unexpected),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(reference: Path = DEFAULT_REFERENCE, rerun: Path = DEFAULT_RERUN) -> dict[str, Any]:
    config_hashes = {}
    for name in ("flow.json", "plan.json", "execution_dag.json"):
        reference_path = reference / "compiled" / name
        rerun_path = rerun / name
        config_hashes[name] = {
            "reference": sha256(reference_path),
            "rerun": sha256(rerun_path),
            "match": sha256(reference_path) == sha256(rerun_path),
        }
    result_comparison = compare_result_trees(reference, rerun)
    rerun_summary = json.loads((rerun / "logs" / "execution_summary.json").read_text(encoding="utf-8"))
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "comparison": "ds007738 golden path vs imported package rerun",
        "reference": reference.relative_to(PROJECT_ROOT).as_posix(),
        "rerun": rerun.relative_to(PROJECT_ROOT).as_posix(),
        "config_hashes": config_hashes,
        "results": result_comparison,
        "rerun_summary": rerun_summary,
        "passed": (
            all(item["match"] for item in config_hashes.values())
            and result_comparison["passed"]
            and rerun_summary["failed_runs"] == 0
            and rerun_summary["successful_runs"] == 4
        ),
    }
    output_path = rerun / "reproducibility_comparison.json"
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_report(result)
    return result


def write_report(result: dict[str, Any]) -> None:
    hashes = "\n".join(
        f"- `{name}`：{'一致' if details['match'] else '不一致'}"
        for name, details in result["config_hashes"].items()
    )
    comparison = result["results"]
    text = f"""# ds007738 跨目录复现验证

生成时间：{result['created_at']}

- 总体结果：{'PASS' if result['passed'] else 'FAIL'}
- 复跑成功：{result['rerun_summary']['successful_runs']} / {result['rerun_summary']['total_runs']}
- 比较 JSON 文件：{comparison['files_compared']}
- 比较数值元素：{comparison['numeric_elements']}
- 容差：`rtol={comparison['rtol']}`，`atol={comparison['atol']}`
- 最大绝对差：{comparison['max_abs_difference']}
- 容差外元素：{len(comparison['numeric_failures'])}
- 基线目录：`{result['reference']}`
- 干净复跑目录：`{result['rerun']}`
- 正式选择：participant `01 02`，task `covert`，run `01 02`
- Attempt：`{result['rerun_summary']['attempt_id']}`

## 配置哈希

{hashes}

验证流程为 export → verify → import → relink → rerun。复跑使用项目本地隔离的 `.venv-mne`
环境和独立输出目录。导出包使用 `external-data://ds007738/`，不包含 `/Volumes/` 或
`/Users/` 机器绝对路径；本次验证不代表跨操作系统复现。
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare a ds007738 package rerun with the golden path")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--rerun", type=Path, default=DEFAULT_RERUN)
    args = parser.parse_args()
    result = compare(args.reference.resolve(), args.rerun.resolve())
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
