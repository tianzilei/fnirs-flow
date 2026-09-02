"""Backend adapters with lazy exports to keep lightweight package imports dependency-free."""

from importlib import import_module

_EXPORTS = {
    "AnalyzIRScript": ("analyzir_export", "AnalyzIRScript"),
    "AnalyzIRStep": ("analyzir_export", "AnalyzIRStep"),
    "convert_flow_to_analyzir": ("analyzir_export", "convert_flow_to_analyzir"),
    "generate_r_script": ("analyzir_export", "generate_r_script"),
    "write_analyzir_mapping_report": ("analyzir_export", "write_analyzir_mapping_report"),
    "write_analyzir_script": ("analyzir_export", "write_analyzir_script"),
    "AnalyzIRImportResult": ("analyzir_import", "AnalyzIRImportResult"),
    "import_analyzir": ("analyzir_import", "import_analyzir"),
    "parse_analyzir_json": ("analyzir_import", "parse_analyzir_json"),
    "parse_analyzir_r_script": ("analyzir_import", "parse_analyzir_r_script"),
    "Homer3ProcessConfig": ("homer3_export", "Homer3ProcessConfig"),
    "Homer3ProcessStep": ("homer3_export", "Homer3ProcessStep"),
    "convert_flow_to_homer3": ("homer3_export", "convert_flow_to_homer3"),
    "write_homer3_config": ("homer3_export", "write_homer3_config"),
    "write_homer3_mapping_report": ("homer3_export", "write_homer3_mapping_report"),
    "Homer3ImportResult": ("homer3_import", "Homer3ImportResult"),
    "import_homer3": ("homer3_import", "import_homer3"),
    "parse_homer3_cfg": ("homer3_import", "parse_homer3_cfg"),
    "parse_homer3_json": ("homer3_import", "parse_homer3_json"),
    "parse_homer3_process_func": ("homer3_import", "parse_homer3_process_func"),
    "SplitProcessedHb": ("processed_hb_split", "SplitProcessedHb"),
    "split_processed_hb": ("processed_hb_split", "split_processed_hb"),
    "save_split_processed_hb": ("processed_hb_split", "save_split_processed_hb"),
    "ShimadzuLayoutError": ("shimadzu_layout", "ShimadzuLayoutError"),
    "read_nirs_spm_ini": ("shimadzu_layout", "read_nirs_spm_ini"),
    "read_shimadzu_layout": ("shimadzu_layout", "read_shimadzu_layout"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute)
    globals()[name] = value
    return value

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
