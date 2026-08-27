"""Backend adapters: bidirectional import/export with Homer3 and AnalyzIR, plus MNE-NIRS execution."""

from fnirs_flow.adapters.analyzir_export import (
    AnalyzIRScript,
    AnalyzIRStep,
    convert_flow_to_analyzir,
    generate_r_script,
    write_analyzir_mapping_report,
    write_analyzir_script,
)
from fnirs_flow.adapters.analyzir_import import (
    AnalyzIRImportResult,
    import_analyzir,
    parse_analyzir_json,
    parse_analyzir_r_script,
)
from fnirs_flow.adapters.homer3_export import (
    Homer3ProcessConfig,
    Homer3ProcessStep,
    convert_flow_to_homer3,
    write_homer3_config,
    write_homer3_mapping_report,
)
from fnirs_flow.adapters.homer3_import import (
    Homer3ImportResult,
    import_homer3,
    parse_homer3_cfg,
    parse_homer3_json,
    parse_homer3_process_func,
)
from fnirs_flow.adapters.processed_hb_split import SplitProcessedHb, save_split_processed_hb, split_processed_hb
from fnirs_flow.adapters.shimadzu_layout import ShimadzuLayoutError, read_nirs_spm_ini, read_shimadzu_layout

__all__ = [
    # AnalyzIR export
    "AnalyzIRScript",
    "AnalyzIRStep",
    "convert_flow_to_analyzir",
    "generate_r_script",
    "write_analyzir_script",
    "write_analyzir_mapping_report",
    # AnalyzIR import
    "AnalyzIRImportResult",
    "import_analyzir",
    "parse_analyzir_r_script",
    "parse_analyzir_json",
    # Homer3 export
    "Homer3ProcessConfig",
    "Homer3ProcessStep",
    "convert_flow_to_homer3",
    "write_homer3_config",
    "write_homer3_mapping_report",
    # Homer3 import
    "Homer3ImportResult",
    "import_homer3",
    "parse_homer3_cfg",
    "parse_homer3_json",
    "parse_homer3_process_func",
    # Shimadzu/NIRS-SPM layout import
    "ShimadzuLayoutError",
    "read_nirs_spm_ini",
    "read_shimadzu_layout",
    "SplitProcessedHb",
    "split_processed_hb",
    "save_split_processed_hb",
]
