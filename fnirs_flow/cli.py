"""fnirs-flow CLI: validate, compile, discover, dry-run, run, export."""

from __future__ import annotations

import argparse
import ipaddress
import json
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import cast


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _webui_dir() -> Path:
    """Return the source-only WebUI directory used by explicit dev mode."""
    repo_webui = Path(__file__).resolve().parent.parent / "webui"
    if repo_webui.is_dir():
        return repo_webui
    raise RuntimeError("WebUI developer sources are unavailable in this installation")


def _packaged_webui_ready() -> bool:
    return files("fnirs_flow.resources.webui").joinpath("dist").joinpath("index.html").is_file()


def cmd_backends(args: argparse.Namespace) -> int:
    """Show backend status and capabilities."""
    from fnirs_flow.adapters.backend_registry import get_registry

    registry = get_registry()

    print("Backend Status:")
    print("=" * 60)

    for backend_id in registry.list_all():
        is_available = registry.is_available(backend_id)
        # Keep CLI status output portable across Windows code pages (for
        # example, the default GBK console used on Chinese Windows systems).
        status = "[OK] Available" if is_available else "[--] Not Available"
        print(f"\n{backend_id}: {status}")

        if is_available:
            try:
                # Get backend class
                backend_class = registry.get(backend_id)
                if backend_class:
                    # Try to get capabilities
                    if hasattr(backend_class, 'capabilities'):
                        caps = backend_class.capabilities
                        if isinstance(caps, dict):
                            print(f"  Version: {caps.get('version', 'unknown')}")
                            ops = caps.get('supported_operations', [])
                            if ops:
                                print(f"  Operations: {', '.join(ops)}")
                            limitations = caps.get('limitations', [])
                            if limitations:
                                print(f"  Limitations: {', '.join(limitations)}")
            except Exception as e:
                print(f"  Error getting info: {e}")

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from fnirs_flow.application.flow_use_cases import validate_flow_payload

    flow_path = Path(args.flow_json)
    if not flow_path.exists():
        print(f"Error: File not found: {args.flow_json}")
        return 1

    flow_dict = json.loads(flow_path.read_text(encoding="utf-8"))
    report = validate_flow_payload(flow_dict)

    if report.is_valid and not report.has_fatal_risks:
        print(f"Flow '{flow_dict.get('flow_id', 'unknown')}' passed validation.")
        if report.warnings:
            print(f"  Warnings: {len(report.warnings)}")
            for w in report.warnings:
                print(f"    - {w}")
        if report.risks:
            print(f"  Risks: {len(report.risks)}")
            for r in report.risks:
                print(f"    [{r.severity}] {r.message}")
        return 0
    else:
        print("Flow validation FAILED.")
        if report.errors:
            print(f"  Errors ({len(report.errors)}):")
            for e in report.errors:
                print(f"    - {e}")
        if report.risks:
            fatal = [r for r in report.risks if r.severity == "fatal"]
            if fatal:
                print(f"  Fatal risks ({len(fatal)}):")
                for r in fatal:
                    print(f"    - {r.message}")
        return 1


def cmd_compile(args: argparse.Namespace) -> int:
    from fnirs_flow.application.flow_use_cases import compile_flow_payload

    flow_path = Path(args.flow_json)
    if not flow_path.exists():
        print(f"Error: File not found: {args.flow_json}")
        return 1

    flow_dict = json.loads(flow_path.read_text(encoding="utf-8"))
    result = compile_flow_payload(flow_dict, args.outdir)

    print(f"Compiled flow '{result.flow_graph.flow_id}'")
    print(f"  Output:    {result.outdir}")
    print(f"  Steps:     {len(result.execution_dag.atoms)}")
    print(f"  Layers:    {len(result.execution_dag.execution_layers)}")
    print()
    print("Generated files:")
    for f in sorted(result.outdir.iterdir()):
        print(f"  {f.name}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from fnirs_flow.application.data_use_cases import discover_dataset_to_workspace

    try:
        manifest = discover_dataset_to_workspace(
            args.dataset_id,
            args.outdir,
            data_root=getattr(args, "data_root", None),
        )
        compiled_dir = Path(args.outdir) / "compiled"
        print(f"Dataset '{args.dataset_id}' discovered")
        print(f"  Files:      {len(manifest.files)}")
        print(f"  Runs:       {len(manifest.subject_session_runs)}")
        print(f"  Local root: {manifest.runtime_local_root or manifest.local_root}")
        print(f"  Output:     {compiled_dir}")
        if not manifest.files:
            print()
            print("  NOTE: No local files found. Data may need to be downloaded.")
            print(f"  Source: {manifest.source.url}")
        return 0
    except ValueError as e:
        print(f"Error: {e}")
        return 1


def cmd_dry_run(args: argparse.Namespace) -> int:
    from fnirs_flow.application.execution_use_cases import dry_run_compiled_project

    try:
        result = dry_run_compiled_project(
            args.plan_dir,
            outdir=args.outdir,
            participant_labels=getattr(args, "participant_label", []) or [],
            session_labels=getattr(args, "session_label", []) or [],
            task_labels=getattr(args, "task_label", []) or [],
            run_labels=getattr(args, "run_label", []) or [],
        )
        report_path = Path(args.outdir) / "derivatives" / "reports" / "run_report.md"
        print(f"Dry-run complete for '{args.plan_dir}'")
        print(f"  Planned runs: {result.total_runs}")
        print(f"  DAG nodes:    {result.summary.get('dag_nodes', 0)}")
        print(f"  Layers:       {result.summary.get('execution_layers', 0)}")
        print(f"  Report:       {report_path}")
        print()
        for run in result.planned_runs:
            print(f"  [{run.status}] {run.run_id}")
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1


def cmd_run(args: argparse.Namespace) -> int:
    """Execute real analysis runs via ExecutionService."""
    from fnirs_flow.application.execution_use_cases import execute_compiled_project
    from fnirs_flow.execution.service import ExecutionRequest

    try:
        request = ExecutionRequest(
            project_dir=args.plan_dir,
            outdir=args.outdir,
            data_root=getattr(args, "data_root", None),
            participant_labels=getattr(args, "participant_label", []) or [],
            session_labels=getattr(args, "session_label", []) or [],
            task_labels=getattr(args, "task_label", []) or [],
            run_labels=getattr(args, "run_label", []) or [],
            continue_on_failure=getattr(args, "continue_on_failure", True),
        )
        result = execute_compiled_project(request)

        # Print summary
        print(f"Execution complete for '{args.plan_dir}'")
        print(f"  Attempt ID:     {result.attempt_id}")
        print(f"  Total runs:     {result.total_runs}")
        print(f"  Successful:     {result.successful_runs}")
        print(f"  Failed:         {result.failed_runs}")
        print(f"  Skipped:        {result.skipped_runs}")

        if result.failure_ids:
            print(f"  Failure IDs:    {', '.join(result.failure_ids)}")

        outdir = Path(args.outdir) if args.outdir else Path(args.plan_dir)
        summary_path = outdir / "logs" / "execution_summary.json"
        if summary_path.exists():
            print(f"  Summary:        {summary_path}")

        # Print per-run status
        for rr in result.run_results:
            status_icon = {
                "completed": "[OK]",
                "failed": "[FAIL]",
                "skipped": "[SKIP]",
            }.get(rr.status, "[???]")
            print(f"    {status_icon} {rr.run_id}")
            if rr.status == "failed":
                for ar in rr.atom_results:
                    if ar.error:
                        print(f"        Error: {ar.error}")

        # A skipped real-data run means the requested analysis did not execute
        # (most commonly because --data-root is missing or invalid).  Do not
        # expose that state as a successful CLI exit.
        return 0 if result.failed_runs == 0 and result.skipped_runs == 0 else 1
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_export(args: argparse.Namespace) -> int:
    """Export a compiled project as a .fnirsflow.zip package."""
    from fnirs_flow.exporters.package_exporter import export_package, get_package_profile

    compiled_dir = Path(args.plan_dir)
    if not (compiled_dir / "plan.json").exists():
        # Check if user passed the parent directory
        if (compiled_dir / "compiled" / "plan.json").exists():
            compiled_dir = compiled_dir / "compiled"
        else:
            print(f"Error: No plan.json found in {args.plan_dir}")
            return 1

    profile_id = args.profile
    try:
        profile = get_package_profile(profile_id)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    pkg_name = f"{compiled_dir.parent.name}_package.fnirsflow.zip"
    pkg_path = outdir / pkg_name

    try:
        export_root = compiled_dir.parent if compiled_dir.name == "compiled" else compiled_dir
        export_package(export_root, pkg_path, profile_id=profile_id)
        print(f"Package exported: {pkg_path}")
        print(f"  Profile:  {profile.name}")
        print(f"  Size:     {pkg_path.stat().st_size} bytes")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_verify_package(args: argparse.Namespace) -> int:
    """Verify a .fnirsflow.zip package."""
    from fnirs_flow.exporters.package_verifier import verify_and_print

    package_path = Path(args.package_path)
    expected_profile = args.profile if hasattr(args, 'profile') else None

    return verify_and_print(package_path, expected_profile)


def cmd_import_package(args: argparse.Namespace) -> int:
    """Import a package and optionally relink it to a local dataset."""
    from fnirs_flow.exporters.package_importer import import_package

    try:
        result = import_package(
            args.package_path,
            args.outdir,
            relink_data=bool(args.data_root),
            data_root=args.data_root,
        )
        print(f"Package imported: {args.package_path}")
        print(f"  Output:      {result['output_dir']}")
        print(f"  Read-only:   {result['read_only']}")
        print(f"  Relinked:    {result['relinked']}")
        print(f"  Quarantined: {len(result['quarantined_atoms'])}")
        return 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1


def cmd_relink_data(args: argparse.Namespace) -> int:
    """Relink an imported package to a local data root."""
    from fnirs_flow.exporters.package_importer import relink_package_data

    try:
        result = relink_package_data(args.package_dir, args.data_root)
        print(f"Package data relinked: {args.package_dir}")
        print(f"  Data root: {result['data_root']}")
        print(f"  Missing:   {len(result['missing_paths'])}")
        return 0 if not result["missing_paths"] else 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1


def cmd_import_homer3(args: argparse.Namespace) -> int:
    """Import a Homer3 config and convert to fnirs-flow atoms."""
    from fnirs_flow.adapters.homer3_import import import_homer3, write_import_report

    source = Path(args.source)
    if not source.exists():
        print(f"Error: File not found: {source}")
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    result = import_homer3(source)

    # Print summary
    print(f"Homer3 import: {source}")
    print(f"  Format:    {result.source_format}")
    print(f"  Atoms:     {len(result.atoms)}")
    print(f"  Unmapped:  {len(result.unmapped_functions)}")

    if result.atoms:
        print()
        print("Imported atoms:")
        for i, atom in enumerate(result.atoms, 1):
            op = atom.get("operation", "")
            cat = atom.get("category", "")
            src = atom.get("source_function", "")
            print(f"  {i}. {atom['atom_type']} ({op}, {cat}) <- {src}")

    if result.unmapped_functions:
        print()
        print("Unmapped Homer3 functions:")
        for u in result.unmapped_functions:
            print(f"  - {u['function']}: {u['reason']}")

    if result.warnings:
        print()
        for w in result.warnings:
            print(f"  Warning: {w}")

    # Write report
    report_path = write_import_report(result, outdir)

    # Write atoms as JSON
    atoms_path = outdir / "imported_atoms.json"
    atoms_path.write_text(
        json.dumps(result.atoms, indent=2, default=str),
        encoding="utf-8",
    )

    print()
    print(f"  Report:    {report_path}")
    print(f"  Atoms JSON: {atoms_path}")
    return 0


def cmd_import_analyzir(args: argparse.Namespace) -> int:
    """Import an AnalyzIR R script or JSON and convert to fnirs-flow atoms."""
    from fnirs_flow.adapters.analyzir_import import import_analyzir, write_import_report

    source = Path(args.source)
    if not source.exists():
        print(f"Error: File not found: {source}")
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    result = import_analyzir(source)

    # Print summary
    print(f"AnalyzIR import: {source}")
    print(f"  Format:    {result.source_format}")
    print(f"  Atoms:     {len(result.atoms)}")
    print(f"  Unmapped:  {len(result.unmapped_functions)}")
    if result.data_path:
        print(f"  Data path: {result.data_path}")

    if result.atoms:
        print()
        print("Imported atoms:")
        for i, atom in enumerate(result.atoms, 1):
            op = atom.get("operation", "")
            cat = atom.get("category", "")
            src = atom.get("source_function", "")
            print(f"  {i}. {atom['atom_type']} ({op}, {cat}) <- {src}")

    if result.unmapped_functions:
        print()
        print("Unmapped AnalyzIR functions:")
        for u in result.unmapped_functions:
            print(f"  - {u['function']}: {u['reason']}")

    if result.warnings:
        print()
        for w in result.warnings:
            print(f"  Warning: {w}")

    # Write report
    report_path = write_import_report(result, outdir)

    # Write atoms as JSON
    atoms_path = outdir / "imported_atoms.json"
    atoms_path.write_text(
        json.dumps(result.atoms, indent=2, default=str),
        encoding="utf-8",
    )

    print()
    print(f"  Report:    {report_path}")
    print(f"  Atoms JSON: {atoms_path}")
    return 0


def cmd_export_homer3(args: argparse.Namespace) -> int:
    """Export fnirs-flow atoms to Homer3 process config."""
    from fnirs_flow.adapters.homer3_export import (
        convert_flow_to_homer3,
        write_homer3_config,
        write_homer3_mapping_report,
    )

    atoms_path = Path(args.atoms_json)
    if not atoms_path.exists():
        print(f"Error: File not found: {atoms_path}")
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    atoms = json.loads(atoms_path.read_text(encoding="utf-8"))
    if not isinstance(atoms, list):
        print("Error: atoms JSON must be a list of atom objects")
        return 1

    config = convert_flow_to_homer3(atoms)

    # Print summary
    print(f"Homer3 export: {len(atoms)} atoms")
    print(f"  Mapped:   {len(config.steps)}")
    print(f"  Unmapped: {len(config.unmapped_atoms)}")

    if config.steps:
        print()
        print("Exported steps:")
        for i, step in enumerate(config.steps, 1):
            print(f"  {i}. {step.name} -> {step.func}")

    if config.unmapped_atoms:
        print()
        print("Unmapped atoms (no Homer3 equivalent):")
        for a in config.unmapped_atoms:
            print(f"  - {a}")

    # Write files
    config_path = write_homer3_config(config, outdir)
    report_path = write_homer3_mapping_report(config, outdir)

    print()
    print(f"  Config:  {config_path}")
    print(f"  Report:  {report_path}")
    return 0


def cmd_export_analyzir(args: argparse.Namespace) -> int:
    """Export fnirs-flow atoms to an AnalyzIR R script."""
    from fnirs_flow.adapters.analyzir_export import (
        convert_flow_to_analyzir,
        write_analyzir_mapping_report,
        write_analyzir_script,
    )

    atoms_path = Path(args.atoms_json)
    if not atoms_path.exists():
        print(f"Error: File not found: {atoms_path}")
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    atoms = json.loads(atoms_path.read_text(encoding="utf-8"))
    if not isinstance(atoms, list):
        print("Error: atoms JSON must be a list of atom objects")
        return 1

    script = convert_flow_to_analyzir(
        atoms,
        data_path=args.data_path or "",
        output_dir=args.output_dir or "",
    )

    # Print summary
    print(f"AnalyzIR export: {len(atoms)} atoms")
    print(f"  Mapped:   {len(script.steps)}")
    print(f"  Unmapped: {len(script.unmapped_atoms)}")

    if script.steps:
        print()
        print("Exported steps:")
        for i, step in enumerate(script.steps, 1):
            print(f"  {i}. {step.name} -> {step.func}")

    if script.unmapped_atoms:
        print()
        print("Unmapped atoms (no AnalyzIR equivalent):")
        for a in script.unmapped_atoms:
            print(f"  - {a}")

    # Write files
    r_path = write_analyzir_script(script, outdir, args.filename)
    report_path = write_analyzir_mapping_report(script, outdir)

    print()
    print(f"  R script: {r_path}")
    print(f"  Report:   {report_path}")
    return 0


def cmd_deps_resolve(args: argparse.Namespace) -> int:
    """Resolve dependencies for a flow or compiled directory."""
    from fnirs_flow.dependencies.resolver import resolve_dependencies

    source = Path(args.flow_json)
    if not source.exists():
        print(f"Error: Path not found: {args.flow_json}")
        return 1

    # Determine if this is a flow JSON or compiled directory
    if source.is_dir():
        dag_path = source / "execution_dag.json"
        if not dag_path.exists():
            print(f"Error: No execution_dag.json found in {source}")
            return 1
    else:
        # Compile the flow first
        from fnirs_flow.application.flow_use_cases import compile_flow_payload
        flow_dict = json.loads(source.read_text(encoding="utf-8"))
        outdir = source.parent / "compiled"
        result = compile_flow_payload(flow_dict, outdir)
        dag_path = result.outdir / "execution_dag.json"

    # Load DAG and resolve
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    plan = resolve_dependencies(dag, flow_id=source.stem)

    # Save plan
    plan_path = dag_path.parent / "dependency_plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    # Print summary
    print(f"Dependency Resolution: {plan.plan_id}")
    print(f"  Status:    {plan.status.value}")
    print(f"  Flow ID:   {plan.flow_id}")
    print(f"  Revision:   {plan.revision}")
    print()
    print(f"  Requirements: {len(plan.requirements)}")
    for req in plan.requirements:
        status_icon = {
            "satisfied": "[OK]",
            "missing": "[MISSING]",
            "incompatible_version": "[VERSION]",
            "incompatible_python": "[PYTHON]",
        }.get(req.status.value, "[???]")
        print(f"    {status_icon} {req.package.distribution} ({req.profile_id})")
        if req.installed_version:
            print(f"           Installed: {req.installed_version}")
        if req.error_message:
            print(f"           Error: {req.error_message}")

    print()
    print(f"  Affected atoms: {sum(len(a) for a in plan.affected_atoms.values())}")
    for profile_id, atom_ids in plan.affected_atoms.items():
        print(f"    {profile_id}: {', '.join(atom_ids[:5])}")

    if plan.requires_user_approval:
        print()
        print("  ACTION REQUIRED: Plan needs user approval before installation.")
        print(f"  Run: fnirs-flow deps install --plan {plan.plan_id}")

    print()
    print(f"  Plan saved: {plan_path}")
    return 0


def cmd_deps_install(args: argparse.Namespace) -> int:
    """Install dependencies from an approved plan."""
    from fnirs_flow.dependencies.installer import get_installation_orchestrator
    from fnirs_flow.dependencies.models import ApprovalRecord, DependencyPlan, InstallPolicy
    from fnirs_flow.dependencies.policies import get_policy_manager

    plan_id = args.plan

    # Find the plan (search in compiled directories)
    plan_data = None
    for compiled_dir in Path(".").rglob("compiled"):
        pp = compiled_dir / "dependency_plan.json"
        if pp.exists():
            data = json.loads(pp.read_text(encoding="utf-8"))
            if data.get("plan_id") == plan_id:
                plan_data = data
                break

    if plan_data is None:
        print(f"Error: Plan '{plan_id}' not found")
        return 1

    plan = DependencyPlan.model_validate(plan_data)

    # Check if approved
    policy_manager = get_policy_manager()
    plan_key = f"{plan.plan_id}:{plan.revision}"
    if not policy_manager.is_approved(plan_key):
        print("Plan is not approved.")
        if plan.requires_user_approval:
            print(f"  Requirements: {len(plan.requirements)}")
            for req in plan.requirements:
                print(f"    - {req.package.distribution} ({req.status.value})")
            confirm = input("Approve this plan and install dependencies? [y/N] ").strip().lower()
            if confirm not in ("y", "yes"):
                print("Installation cancelled.")
                return 1
        policy_manager.approve_plan(plan_key)

    # Create approval record
    approval = ApprovalRecord(
        plan_id=plan.plan_id,
        plan_revision=plan.revision,
        decision=InstallPolicy.APPROVED_ONCE,
    )

    # Execute installation
    orchestrator = get_installation_orchestrator()
    print(f"Installing dependencies for plan: {plan_id}")
    print(f"  Profile: {plan.requirements[0].profile_id if plan.requirements else 'unknown'}")
    print()

    task = orchestrator.install_from_plan(plan, approval)

    print(f"Installation {task.status}")
    print(f"  Task ID: {task.task_id}")
    if task.error:
        print(f"  Error: {task.error}")
    if task.log_lines:
        print("  Log:")
        for line in task.log_lines[-10:]:
            print(f"    {line}")

    return 0 if task.status == "completed" else 1


def cmd_deps_status(args: argparse.Namespace) -> int:
    """Check dependency plan status."""
    plan_id = args.plan_id

    # Find the plan
    for compiled_dir in Path(".").rglob("compiled"):
        pp = compiled_dir / "dependency_plan.json"
        if pp.exists():
            data = json.loads(pp.read_text(encoding="utf-8"))
            if data.get("plan_id") == plan_id:
                print(f"Dependency Plan: {plan_id}")
                print(f"  Status:      {data.get('status', 'unknown')}")
                print(f"  Flow ID:     {data.get('flow_id', 'unknown')}")
                print(f"  Revision:    {data.get('revision', 1)}")
                print(f"  Requirements: {len(data.get('requirements', []))}")
                print(f"  Requires approval: {data.get('requires_user_approval', False)}")
                print(f"  Network required: {data.get('network_required', False)}")

                # Check approval status
                approval_path = compiled_dir / "approval_record.json"
                if approval_path.exists():
                    approval = json.loads(approval_path.read_text(encoding="utf-8"))
                    print(f"  Approved: {approval.get('decision', 'unknown')}")
                    print(f"  Approved at: {approval.get('approved_at', 'unknown')}")
                else:
                    print("  Approved: No")

                return 0

    print(f"Error: Plan '{plan_id}' not found")
    return 1


def cmd_deps_env_list(args: argparse.Namespace) -> int:
    """List all dependency environments."""
    from fnirs_flow.dependencies.installer import get_installation_orchestrator

    orchestrator = get_installation_orchestrator()
    envs = orchestrator.list_environments()

    if not envs:
        print("No dependency environments found.")
        return 0

    print("Dependency Environments:")
    print("=" * 60)
    for env in envs:
        print(f"  {env['environment_id']}")
        print(f"    Status:  {env['status']}")
        print(f"    Path:    {env['path']}")
        if env.get('created_at'):
            print(f"    Created: {env['created_at']}")
        print()

    return 0


def cmd_deps_env_remove(args: argparse.Namespace) -> int:
    """Remove a dependency environment."""
    from fnirs_flow.dependencies.installer import get_installation_orchestrator

    environment_id = args.environment_id
    parts = environment_id.split("/", 1)
    if len(parts) != 2:
        print(f"Error: Invalid environment_id format: {environment_id}")
        print("Expected format: profile_id/environment_revision")
        return 1

    orchestrator = get_installation_orchestrator()
    success = orchestrator.remove_environment(parts[0], parts[1])

    if success:
        print(f"Removed environment: {environment_id}")
        return 0
    else:
        print(f"Environment not found: {environment_id}")
        return 1


def cmd_webui(args: argparse.Namespace) -> int:
    """Start the WebUI server."""
    try:
        import uvicorn

        from fnirs_flow.api.app import app
        from fnirs_flow.settings import settings

        host = args.host or "127.0.0.1"
        port = args.port
        if not _is_loopback_host(host) and not settings.api_key:
            print("Error: binding WebUI to a non-localhost host requires FNIRS_API_KEY.")
            print("Set FNIRS_API_KEY or use --host 127.0.0.1 for local-only access.")
            return 1

        if args.dev:
            # Dev mode: start Vite dev server + backend concurrently
            import subprocess
            import sys

            webui_dir = _webui_dir()
            if not (webui_dir / "node_modules").exists():
                print("Installing frontend dependencies...")
                subprocess.run(["npm", "install"], cwd=webui_dir, check=True)

            print("Starting fnirs-flow in DEV mode")
            print(f"  Backend:  http://{host}:{port}")
            print("  Frontend: http://localhost:3000")
            print("Press Ctrl+C to stop")

            # Start Vite dev server in background
            vite_proc = subprocess.Popen(
                ["npm", "run", "dev"],
                cwd=webui_dir,
                shell=(sys.platform == "win32"),
            )

            try:
                uvicorn.run(app, host=host, port=port)
            finally:
                vite_proc.terminate()
                vite_proc.wait(timeout=5)
        else:
            # Production mode: serve built frontend from FastAPI
            if not _packaged_webui_ready():
                print("Error: packaged WebUI assets are missing from this installation.")
                print("Reinstall fnirs-flow; npm/Vite are only invoked with --dev.")
                return 1

            print(f"Starting fnirs-flow WebUI on http://{host}:{port}")
            print("Press Ctrl+C to stop")
            uvicorn.run(app, host=host, port=port)
        return 0
    except ImportError:
        print("Error: uvicorn is required for WebUI.")
        print("Install with: pip install fnirs-flow[full]")
        return 1


def cmd_rerun(args: argparse.Namespace) -> int:
    """Rerun an imported package after data relink."""
    from fnirs_flow.exporters.package_importer import rerun_package

    try:
        result = rerun_package(
            package_dir=args.package_dir,
            outdir=args.outdir,
            participant_labels=getattr(args, "participant_label", []) or [],
            task_labels=getattr(args, "task_label", []) or [],
            run_labels=getattr(args, "run_label", []) or [],
            continue_on_failure=getattr(args, "continue_on_failure", True),
        )
        print(f"Rerun complete for '{args.package_dir}'")
        print(f"  Attempt ID:     {result['attempt_id']}")
        print(f"  Total runs:     {result['total_runs']}")
        print(f"  Successful:     {result['successful_runs']}")
        print(f"  Failed:         {result['failed_runs']}")
        print(f"  Skipped:        {result['skipped_runs']}")
        if result["failure_ids"]:
            print(f"  Failure IDs:    {', '.join(result['failure_ids'])}")
        if result["reports"]:
            print(f"  Reports:        {', '.join(result['reports'])}")
        return 0 if result["failed_runs"] == 0 else 1
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fnirs-flow",
        description="fnirs-flow: evidence-driven fNIRS analysis workflow orchestration",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # User-facing commands
    p_validate = subparsers.add_parser("validate", help="Validate a flow JSON file")
    p_validate.add_argument("flow_json", help="Path to flow JSON file")
    p_validate.set_defaults(func=cmd_validate)

    p_compile = subparsers.add_parser("compile", help="Compile flow to plan/dag/manifests")
    p_compile.add_argument("flow_json", help="Path to flow JSON file")
    p_compile.add_argument("--outdir", required=True, help="Output directory")
    p_compile.set_defaults(func=cmd_compile)

    p_discover = subparsers.add_parser("discover", help="Discover a public dataset")
    p_discover.add_argument("dataset_id", help="Dataset identifier")
    p_discover.add_argument("--outdir", required=True, help="Output directory")
    p_discover.add_argument("--data-root", help="Local root directory for BIDS-NIRS data")
    p_discover.set_defaults(func=cmd_discover)

    p_dryrun = subparsers.add_parser("dry-run", help="Dry-run a compiled plan")
    p_dryrun.add_argument("plan_dir", help="Directory with compiled plan (or parent dir)")
    p_dryrun.add_argument("--outdir", required=True, help="Output directory")
    p_dryrun.add_argument("--participant-label", nargs="*", help="Filter by participant label")
    p_dryrun.add_argument("--session-label", nargs="*", help="Filter by session label")
    p_dryrun.add_argument("--task-label", nargs="*", help="Filter by task label")
    p_dryrun.add_argument("--run-label", nargs="*", help="Filter by run label")
    p_dryrun.set_defaults(func=cmd_dry_run)

    p_run = subparsers.add_parser("run", help="Execute analysis runs via adapter")
    p_run.add_argument("plan_dir", help="Directory with compiled plan (or parent dir)")
    p_run.add_argument("--outdir", required=True, help="Output directory")
    p_run.add_argument("--data-root", help="Root directory containing BIDS-NIRS data")
    p_run.add_argument("--participant-label", nargs="*", help="Filter by participant label")
    p_run.add_argument("--session-label", nargs="*", help="Filter by session label")
    p_run.add_argument("--task-label", nargs="*", help="Filter by task label")
    p_run.add_argument("--run-label", nargs="*", help="Filter by run label")
    p_run.add_argument(
        "--continue-on-failure",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Continue processing other runs if one fails (default: True). "
        "Use --no-continue-on-failure to stop on first failure.",
    )
    p_run.set_defaults(func=cmd_run)

    p_export = subparsers.add_parser("export", help="Export compiled project as package")
    p_export.add_argument("plan_dir", help="Directory with compiled plan (or parent dir)")
    p_export.add_argument("--outdir", required=True, help="Output directory for package")
    p_export.add_argument(
        "--profile",
        default="reproducibility_package",
        choices=["reproducibility_package", "submission_package", "reviewer_package"],
        help="Package profile (default: reproducibility_package)",
    )
    p_export.set_defaults(func=cmd_export)

    p_verify = subparsers.add_parser("verify-package", help="Verify a .fnirsflow.zip package")
    p_verify.add_argument("package_path", help="Path to .fnirsflow.zip file")
    p_verify.add_argument(
        "--profile",
        default=None,
        choices=["reproducibility_package", "submission_package", "reviewer_package"],
        help="Expected package profile (optional)",
    )
    p_verify.set_defaults(func=cmd_verify_package)

    p_import_package = subparsers.add_parser("import-package", help="Import a .fnirsflow.zip package")
    p_import_package.add_argument("package_path", help="Path to .fnirsflow.zip file")
    p_import_package.add_argument("--outdir", required=True, help="Directory for imported package files")
    p_import_package.add_argument("--data-root", help="Optional local data root for immediate relinking")
    p_import_package.set_defaults(func=cmd_import_package)

    p_relink = subparsers.add_parser("relink-data", help="Relink an imported package to local data")
    p_relink.add_argument("package_dir", help="Directory containing the imported package")
    p_relink.add_argument("--data-root", required=True, help="Local dataset root")
    p_relink.set_defaults(func=cmd_relink_data)

    p_rerun = subparsers.add_parser("rerun", help="Rerun an imported package after data relink")
    p_rerun.add_argument("package_dir", help="Directory containing the imported package")
    p_rerun.add_argument("--outdir", default=None, help="Output directory (defaults to package_dir)")
    p_rerun.add_argument("--participant-label", nargs="*", help="Filter by participant label")
    p_rerun.add_argument("--task-label", nargs="*", help="Filter by task label")
    p_rerun.add_argument("--run-label", nargs="*", help="Filter by run label")
    p_rerun.add_argument(
        "--continue-on-failure",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Continue on failure (default: True)",
    )
    p_rerun.set_defaults(func=cmd_rerun)

    # Backend adapter commands
    p_import_h3 = subparsers.add_parser(
        "import-homer3",
        help="Import Homer3 config (.cfg/.json) and convert to fnirs-flow atoms",
    )
    p_import_h3.add_argument("source", help="Path to Homer3 .cfg or .json file")
    p_import_h3.add_argument("--outdir", required=True, help="Output directory")
    p_import_h3.set_defaults(func=cmd_import_homer3)

    p_import_az = subparsers.add_parser(
        "import-analyzir",
        help="Import AnalyzIR R script (.R) or JSON and convert to fnirs-flow atoms",
    )
    p_import_az.add_argument("source", help="Path to AnalyzIR .R or .json file")
    p_import_az.add_argument("--outdir", required=True, help="Output directory")
    p_import_az.set_defaults(func=cmd_import_analyzir)

    p_export_h3 = subparsers.add_parser(
        "export-homer3",
        help="Export fnirs-flow atoms to Homer3 process config",
    )
    p_export_h3.add_argument("atoms_json", help="Path to atoms JSON file (e.g. imported_atoms.json)")
    p_export_h3.add_argument("--outdir", required=True, help="Output directory")
    p_export_h3.set_defaults(func=cmd_export_homer3)

    p_export_az = subparsers.add_parser(
        "export-analyzir",
        help="Export fnirs-flow atoms to AnalyzIR R script",
    )
    p_export_az.add_argument("atoms_json", help="Path to atoms JSON file (e.g. imported_atoms.json)")
    p_export_az.add_argument("--outdir", required=True, help="Output directory")
    p_export_az.add_argument(
        "--filename",
        default="fnirs_pipeline.R",
        help="R script filename (default: fnirs_pipeline.R)",
    )
    p_export_az.add_argument("--data-path", default="", help="Input data path for R script load command")
    p_export_az.add_argument("--output-dir", default="", help="Output directory path for R script save command")
    p_export_az.set_defaults(func=cmd_export_analyzir)

    # AI draft flow generation
    def cmd_generate_draft(args: argparse.Namespace) -> int:
        import json as json_mod
        import sys

        from fnirs_flow.ai.draft_generator import generate_draft_flow

        try:
            flow = generate_draft_flow(
                args.scenario,
                study_name=args.name or "",
                data_format=args.format,
                conditions=args.conditions.split(",") if args.conditions else None,
                model_name=args.model,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        output = json_mod.dumps(flow, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"Draft flow written to {args.output}")
        else:
            print(output)
        return 0

    p_draft = subparsers.add_parser(
        "generate-flow-draft",
        help="Generate a candidate flow from a scenario template (AI draft)",
    )
    p_draft.add_argument(
        "scenario",
        help="Scenario: task, resting_state, machine_learning, real_world, hyperscanning, multi_site",
    )
    p_draft.add_argument("--name", default="", help="Study name")
    p_draft.add_argument("--format", default="snirf", help="Data format (default: snirf)")
    p_draft.add_argument("--conditions", default="", help="Comma-separated experimental conditions")
    p_draft.add_argument("--model", default="template_based", help="Model identifier")
    p_draft.add_argument("--output", "-o", default="", help="Output file path (default: stdout)")
    p_draft.set_defaults(func=cmd_generate_draft)

    p_webui = subparsers.add_parser("webui", help="Start the WebUI server")
    p_webui.add_argument("--host", default=None, help="Host to bind to (default: 127.0.0.1)")
    p_webui.add_argument("--port", type=int, default=8000, help="Port to listen on")
    p_webui.add_argument("--dev", action="store_true", help="Dev mode: start Vite dev server alongside backend")
    p_webui.set_defaults(func=cmd_webui)

    p_backends = subparsers.add_parser("backends", help="Show backend status and capabilities")
    p_backends.set_defaults(func=cmd_backends)

    # Dependency management commands (§9.2)
    p_deps = subparsers.add_parser("deps", help="Dependency management commands")
    deps_subparsers = p_deps.add_subparsers(dest="deps_command", help="Dependency commands")

    # fnirs-flow deps resolve <flow-or-project>
    p_deps_resolve = deps_subparsers.add_parser("resolve", help="Resolve dependencies for a flow")
    p_deps_resolve.add_argument("flow_json", help="Path to flow JSON file or compiled directory")
    p_deps_resolve.set_defaults(func=cmd_deps_resolve)

    # fnirs-flow deps install --plan <plan-id>
    p_deps_install = deps_subparsers.add_parser("install", help="Install dependencies from a plan")
    p_deps_install.add_argument("--plan", required=True, help="Plan ID to install")
    p_deps_install.set_defaults(func=cmd_deps_install)

    # fnirs-flow deps status <plan-id>
    p_deps_status = deps_subparsers.add_parser("status", help="Check dependency plan status")
    p_deps_status.add_argument("plan_id", help="Plan ID to check")
    p_deps_status.set_defaults(func=cmd_deps_status)

    # fnirs-flow deps env list
    p_deps_env = deps_subparsers.add_parser("env", help="Manage dependency environments")
    env_subparsers = p_deps_env.add_subparsers(dest="env_command", help="Environment commands")
    p_env_list = env_subparsers.add_parser("list", help="List all environments")
    p_env_list.set_defaults(func=cmd_deps_env_list)
    p_env_remove = env_subparsers.add_parser("remove", help="Remove an environment")
    p_env_remove.add_argument("environment_id", help="Environment ID (profile_id/environment_revision)")
    p_env_remove.set_defaults(func=cmd_deps_env_remove)

    # Legacy aliases (backward compatibility)
    p_validate_legacy = subparsers.add_parser("validate-flow", help="[Deprecated] Use 'validate'")
    p_validate_legacy.add_argument("flow_json", help="Path to flow JSON file")
    p_validate_legacy.set_defaults(func=cmd_validate)

    p_compile_legacy = subparsers.add_parser("compile-flow", help="[Deprecated] Use 'compile'")
    p_compile_legacy.add_argument("flow_json", help="Path to flow JSON file")
    p_compile_legacy.add_argument("--outdir", required=True, help="Output directory")
    p_compile_legacy.set_defaults(func=cmd_compile)

    p_discover_legacy = subparsers.add_parser("discover-dataset", help="[Deprecated] Use 'discover'")
    p_discover_legacy.add_argument("dataset_id", help="Dataset identifier")
    p_discover_legacy.add_argument("--outdir", required=True, help="Output directory")
    p_discover_legacy.add_argument("--data-root", help="Local root directory for BIDS-NIRS data")
    p_discover_legacy.set_defaults(func=cmd_discover)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    command = cast(Callable[[argparse.Namespace], int], args.func)
    return command(args)


if __name__ == "__main__":
    raise SystemExit(main())
