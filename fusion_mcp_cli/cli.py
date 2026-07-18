import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .offline_schema import load_offline_mcp_surface


ADDIN_NAME = "FusionMCP"
LEGACY_ADDIN_NAME = "Fusion MCP Addin"
SERVER_NAME = "autodesk-fusion-mcp"
REQUIRED_FILES = (
    "__init__.py",
    "FusionMCP.py",
    "FusionMCP.manifest",
    "best_practices.md",
    "workflow_guide.md",
    "help_context.json",
    "tool_profiles.json",
)
REQUIRED_DIRS = ("server", "tools", "mcp_primitives")
SOURCE_FINGERPRINT_FILES = (
    "FusionMCP.py",
    "FusionMCP.manifest",
    "tool_profiles.json",
    os.path.join("server", "mcp_server.py"),
    os.path.join("tools", "__init__.py"),
    os.path.join("tools", "features.py"),
    os.path.join("tools", "inspection.py"),
    os.path.join("tools", "utilities.py"),
    os.path.join("tools", "parametric.py"),
)
REQUIRED_LIVE_TOOLS = (
    "inspect_design",
    "recommend_mcp_workflow",
    "extract_reference_dimensions",
    "inspect_printability",
    "inspect_selection_sets",
    "inspect_3mf_archive",
    "plan_multibody_3mf_export",
    "plan_multicolor_3mf_export",
    "inspect_mesh_bodies",
    "plan_mesh_conversion",
    "repair_mesh_body",
    "reduce_mesh_body",
    "remesh_body",
    "inspect_design_configurations",
    "plan_design_variant",
    "apply_design_variant_parameters",
    "inspect_render_workspace",
    "plan_render_output",
    "render_viewport_output",
    "inspect_document_management_state",
    "plan_document_management_action",
    "export_document_copy",
    "get_physical_properties",
    "inspect_analysis_capabilities",
    "interference_check",
    "clearance_check",
    "verify_insert_alignment",
    "exact_interference_check",
    "exact_clearance_check",
    "inspect_sheet_metal_rules",
    "preflight_flat_pattern",
    "plan_sheet_metal_workflow",
    "export_flat_pattern",
    "inspect_surface_bodies",
    "plan_surface_repair",
    "inspect_drawing_documents",
    "preflight_drawing_creation",
    "plan_drawing_views",
    "inspect_electronics_workspace",
    "plan_pcb_enclosure_fit",
    "inspect_simulation_workspace",
    "list_simulation_studies",
    "plan_simulation_study",
    "inspect_manufacturing_workspace",
    "list_manufacturing_setups",
    "inspect_operation",
    "plan_manufacturing_operation",
    "create_manufacturing_setup",
    "create_manufacturing_operation",
    "generate_toolpaths",
    "post_process",
    "get_body_faces",
    "get_body_edges",
    "get_assembly_tree",
    "get_assembly_references",
    "get_assembly_joints",
    "plan_joint_limits",
    "list_appearances",
    "inspect_body_style",
    "get_timeline",
    "measure_entity",
    "validate_model",
    "assess_change_impact",
    "preflight_model_change",
    "edit_extrude_feature",
    "edit_fillet_radius",
    "edit_chamfer_distance",
    "edit_shell_thickness",
    "edit_pattern_parameter",
    "edit_hole_parameter",
    "offset_face_or_press_pull",
    "create_offset_plane",
    "create_construction_point",
    "create_construction_axis",
    "create_rigid_joint",
    "create_section_analysis",
    "create_revolute_joint",
    "create_slider_joint",
    "create_cylindrical_joint",
    "create_pin_slot_joint",
    "create_planar_joint",
    "create_ball_joint",
    "set_joint_limits",
    "create_flange",
    "create_bend",
    "unfold_sheet_metal",
    "refold_sheet_metal",
    "patch_surface",
    "stitch_surfaces",
    "thicken_surface",
    "trim_surface",
    "extend_surface",
    "create_ruled_surface",
    "add_sketch_constraint",
    "delete_sketch_constraint",
    "create_sketch_offset",
    "copy_profile_loop",
    "offset_profile_loop",
    "create_insert_socket",
    "create_parametric_feature",
    "extrude_existing_profile",
    "revolve_feature",
    "loft_feature",
    "sweep_feature",
    "create_rounded_rectangle_body",
    "create_rounded_slot_cut",
    "create_rounded_pocket",
    "create_hole_pattern",
    "create_counterbore_hole_pattern",
    "mirror_features_or_bodies",
    "pattern_feature",
    "apply_appearance",
    "convert_mesh_to_solid",
    "reorganize_body_to_component",
    "import_parameters_csv",
    "export_parameters_csv",
    "capture_view",
    "add_drawing_view",
    "add_drawing_dimension",
    "add_drawing_callout",
    "add_parts_list",
    "add_revision_table",
    "set_camera",
    "shell_body",
    "set_visibility",
    "capture_demo_sequence",
    "prompt_user",
    "list_documents",
    "create_design_document",
    "close_active_document",
    "delete_named_experiment",
    "set_timeline_marker",
    "clone_timeline_feature",
)
REQUIRED_FIXTURE_PROBES = (
    "health",
    "initialize",
    "tools_list",
    "fixture_creation",
    "offset_face_or_press_pull",
    "inspect_mesh_bodies",
    "plan_mesh_conversion",
    "inspect_design_configurations",
    "plan_design_variant",
    "apply_design_variant_parameters",
    "inspect_render_workspace",
    "plan_render_output",
    "render_viewport_output",
    "inspect_document_management_state",
    "plan_document_management_action",
    "export_document_copy",
    "inspect_analysis_capabilities",
    "exact_interference_check",
    "exact_clearance_check",
    "get_assembly_references",
    "plan_joint_limits",
    "create_revolute_joint",
    "create_slider_joint",
    "create_cylindrical_joint",
    "create_pin_slot_joint",
    "create_planar_joint",
    "create_ball_joint",
    "plan_surface_repair",
    "thicken_surface",
    "inspect_sheet_metal_rules",
    "plan_sheet_metal_workflow",
    "create_flange",
    "preflight_drawing_creation",
    "add_drawing_callout",
    "inspect_electronics_workspace",
    "plan_pcb_enclosure_fit",
    "inspect_simulation_workspace",
    "list_simulation_studies",
    "plan_simulation_study",
    "plan_manufacturing_operation",
    "generate_toolpaths",
    "post_process",
    "capture_demo_sequence",
    "fixture_cleanup",
)
ACCEPTED_FIXTURE_PROBE_STATUSES = {
    "passed",
    "unsupported",
    "preflight_blocked",
}


def repo_root():
    return Path(__file__).resolve().parents[1]


def source_fingerprint(root):
    root = Path(root)
    digest = hashlib.sha256()
    files = []
    for rel_path in SOURCE_FINGERPRINT_FILES:
        normalized = rel_path.replace("\\", "/")
        path = root / rel_path
        item = {
            "path": normalized,
            "exists": path.exists(),
        }
        digest.update(normalized.encode("utf-8"))
        if path.exists():
            try:
                data = path.read_bytes()
                digest.update(data)
                item["sizeBytes"] = len(data)
                item["sha256"] = hashlib.sha256(data).hexdigest()
            except Exception as exc:
                item["error"] = str(exc)
                digest.update(str(exc).encode("utf-8"))
        else:
            digest.update(b"<missing>")
        files.append(item)
    return {
        "algorithm": "sha256",
        "fingerprint": digest.hexdigest(),
        "fileCount": len(files),
        "files": files,
    }


def default_addins_root():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not set; pass --addins-root explicitly.")
    return Path(appdata) / "Autodesk" / "Autodesk Fusion 360" / "API" / "AddIns"


def disabled_addins_root(addins_root):
    return Path(addins_root).parent / "AddInsDisabled"


def discovery_path():
    return Path.home() / ".fusion_mcp.json"


def antigravity_config_path():
    return Path.home() / ".gemini" / "config" / "mcp_config.json"


def load_json(path):
    if not Path(path).exists():
        raise FileNotFoundError(f"{path} does not exist. Start the FusionMCP add-in first or pass --discovery-path.")
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_optional_json(path):
    path = Path(path)
    result = {"path": str(path), "exists": path.exists()}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                result["payload"] = json.load(handle)
        except Exception as exc:
            result["error"] = str(exc)
    return result


def installed_metadata_path(health):
    candidates = []
    source_root = health.get("source_root") if isinstance(health, dict) else None
    if source_root:
        candidates.append(Path(source_root) / ".fusion_mcp_install.json")
    try:
        candidates.append(default_addins_root() / ADDIN_NAME / ".fusion_mcp_install.json")
    except RuntimeError:
        pass
    candidates.append(repo_root() / ".fusion_mcp_install.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(temp_path, path)


def validate_addin_payload(source):
    for name in REQUIRED_FILES:
        path = source / name
        if not path.is_file():
            raise RuntimeError(f"Required file missing: {path}")
    for name in REQUIRED_DIRS:
        path = source / name
        if not path.is_dir():
            raise RuntimeError(f"Required directory missing: {path}")


def quarantine_legacy_addin(addins_root, legacy_name=LEGACY_ADDIN_NAME):
    addins_root = Path(addins_root).resolve()
    legacy_path = (addins_root / legacy_name).resolve()
    if not legacy_path.exists():
        return None
    if not legacy_path.is_dir():
        raise RuntimeError(f"Legacy add-in path exists but is not a directory: {legacy_path}")
    if addins_root not in legacy_path.parents:
        raise RuntimeError(f"Refusing to move legacy add-in outside AddIns root: {legacy_path}")

    disabled_root = disabled_addins_root(addins_root)
    disabled_root.mkdir(parents=True, exist_ok=True)
    base_target = disabled_root / f"{legacy_name}.disabled-legacy"
    target = base_target
    suffix = 1
    while target.exists():
        suffix += 1
        target = disabled_root / f"{legacy_name}.disabled-legacy-{suffix}"
    shutil.move(str(legacy_path), str(target))
    return target


def iter_addin_payload(source):
    for name in REQUIRED_FILES:
        yield source / name, Path(name)
    for name in REQUIRED_DIRS:
        root = source / name
        for path in root.rglob("*"):
            if path.is_dir():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            yield path, Path(name) / path.relative_to(root)


def command_install_addin(args):
    source = repo_root()
    addins_root = Path(args.addins_root) if args.addins_root else default_addins_root()
    target = addins_root / args.addin_name
    validate_addin_payload(source)
    target.mkdir(parents=True, exist_ok=True)
    if not args.keep_legacy_addin:
        quarantined = quarantine_legacy_addin(addins_root, args.legacy_addin_name)
        if quarantined:
            print(f"Moved legacy Fusion MCP add-in outside Fusion scan path: {quarantined}")
    for name in REQUIRED_FILES:
        shutil.copy2(source / name, target / name)
    for name in REQUIRED_DIRS:
        target_dir = target / name
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source / name, target_dir)
    for cache_dir in target.rglob("__pycache__"):
        shutil.rmtree(cache_dir, ignore_errors=True)
    install_metadata = {
        "installedAt": datetime.now(timezone.utc).isoformat(),
        "sourceRoot": str(source),
        "targetRoot": str(target),
        "sourceFingerprint": source_fingerprint(source),
    }
    write_json(target / ".fusion_mcp_install.json", install_metadata)

    print(f"Installed FusionMCP add-in to: {target}")
    print("FusionMCP remains opt-in; start it from Fusion 360 Utilities > Add-Ins.")
    return 0


def command_package_addin(args):
    source = repo_root()
    validate_addin_payload(source)
    output = Path(args.output) if args.output else source / "dist" / f"{args.addin_name}-addin.zip"
    output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, relative in iter_addin_payload(source):
            archive_name = Path(args.addin_name) / relative
            archive.write(path, str(archive_name).replace("\\", "/"))

    print(f"Wrote FusionMCP add-in package: {output}")
    return 0


def command_sync_config(args):
    config_path = Path(args.config_path) if args.config_path else antigravity_config_path()
    discovery = load_json(Path(args.discovery_path) if args.discovery_path else discovery_path())
    sse_url = discovery.get("sse_url")
    if not sse_url:
        raise RuntimeError("Discovery file does not contain sse_url.")

    config = load_json(config_path) if config_path.exists() else {}
    if not isinstance(config, dict):
        raise RuntimeError(f"MCP config must be a JSON object: {config_path}")
    mcp_servers = config.setdefault("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        raise RuntimeError("mcpServers must be a JSON object.")
    server_config = mcp_servers.setdefault(args.server_name, {})
    if not isinstance(server_config, dict):
        raise RuntimeError(f"mcpServers.{args.server_name} must be a JSON object.")
    server_config["serverUrl"] = sse_url
    server_config["disabled"] = False
    write_json(config_path, config)
    print(f"Updated {args.server_name} serverUrl to {sse_url}")
    return 0


def command_doctor(args):
    discovery = load_json(Path(args.discovery_path) if args.discovery_path else discovery_path())
    streamable_url = discovery.get("streamable_http_url")
    bearer_url = discovery.get("bearer_sse_url")
    auth_header = discovery.get("authorization_header")
    sse_url = discovery.get("sse_url")
    url = streamable_url or bearer_url or sse_url
    if not url:
        raise RuntimeError("Discovery file does not contain streamable_http_url, bearer_sse_url, or sse_url.")

    parsed_url = urlparse(url)
    health_url = f"{parsed_url.scheme}://{parsed_url.netloc}/health"
    with urllib.request.urlopen(health_url, timeout=args.timeout) as response:
        health = json.loads(response.read().decode("utf-8"))
    print(json.dumps({"health": health}, indent=2))

    def post_jsonrpc(req_id, method, params=None, session_id=None):
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        if auth_header and (streamable_url or bearer_url):
            request.add_header("Authorization", auth_header)
        if session_id:
            request.add_header("Mcp-Session-Id", session_id)
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                return json.loads(response.read().decode("utf-8")), response.headers.get("Mcp-Session-Id")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{method} failed with HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}")

    payload, session_id = post_jsonrpc(1, "initialize")
    print(json.dumps({"initialize": payload, "sessionId": session_id}, indent=2))
    missing_required_tools = []
    fingerprint_mismatch = False
    installed_mismatch = False
    if session_id:
        tools_payload, _ = post_jsonrpc(2, "tools/list", session_id=session_id)
        if tools_payload.get("error"):
            raise RuntimeError(f"tools/list failed: {json.dumps(tools_payload['error'])}")
        tool_names = sorted({
            tool.get("name")
            for tool in tools_payload.get("result", {}).get("tools", [])
            if tool.get("name")
        })
        required = list(REQUIRED_LIVE_TOOLS)
        missing_required_tools = [name for name in required if name not in tool_names]
        tools_report = {
            "count": len(tool_names),
            "requiredCount": len(required),
            "missingRequiredTools": missing_required_tools,
            "restartRecommended": bool(missing_required_tools),
        }
        if missing_required_tools:
            tools_report["action"] = (
                "Stop and run the FusionMCP add-in again from Fusion 360 Utilities > Add-Ins, "
                "or restart Fusion so it reloads Python modules."
            )
        print(json.dumps({"tools": tools_report}, indent=2))
        diagnostics_text = None
        try:
            diagnostics_payload, _ = post_jsonrpc(3, "tools/call", {
                "name": "get_runtime_diagnostics",
                "arguments": {"required_tools": required},
            }, session_id=session_id)
            try:
                diagnostics_text = diagnostics_payload["result"]["content"][0]["text"]
                diagnostics = json.loads(diagnostics_text)
            except Exception:
                diagnostics = {"error": "Could not parse get_runtime_diagnostics response.", "raw": diagnostics_text}
        except Exception as exc:
            diagnostics = {"error": f"get_runtime_diagnostics failed: {exc}"}
        diagnostics_fingerprint = (((diagnostics.get("result") or {}).get("runtime") or {}).get("sourceFingerprint") or {})
        health_fingerprint = health.get("source_fingerprint") or {}
        live_fingerprint = health_fingerprint or diagnostics_fingerprint
        checkout_fingerprint = source_fingerprint(repo_root())
        install = load_optional_json(installed_metadata_path(health))
        installed_fingerprint = (((install.get("payload") or {}).get("sourceFingerprint")) or {})
        fingerprint_mismatch = bool(
            live_fingerprint.get("fingerprint")
            and live_fingerprint.get("fingerprint") != checkout_fingerprint.get("fingerprint")
        )
        installed_mismatch = bool(
            installed_fingerprint.get("fingerprint")
            and installed_fingerprint.get("fingerprint") != checkout_fingerprint.get("fingerprint")
        )
        print(json.dumps({
            "sourceFingerprint": {
                "checkout": checkout_fingerprint,
                "installed": {
                    "metadata": install,
                    "matchesCheckout": bool(installed_fingerprint.get("fingerprint") == checkout_fingerprint.get("fingerprint")) if installed_fingerprint.get("fingerprint") else None,
                },
                "live": {
                    "fromHealth": health_fingerprint,
                    "fromDiagnostics": diagnostics_fingerprint,
                    "effective": live_fingerprint,
                },
                "matches": bool(live_fingerprint.get("fingerprint") == checkout_fingerprint.get("fingerprint")) if live_fingerprint.get("fingerprint") else None,
                "diagnosticsError": diagnostics.get("error"),
                "restartRecommended": fingerprint_mismatch or installed_mismatch,
                "action": (
                    "Live FusionMCP source fingerprint differs from this checkout. Reinstall and restart/reload the FusionMCP add-in."
                    if fingerprint_mismatch else
                    "Installed FusionMCP source fingerprint differs from this checkout. Run fusion-mcp install-addin, then restart/reload the add-in."
                    if installed_mismatch else None
                ),
            }
        }, indent=2))
    if session_id:
        delete_request = urllib.request.Request(url, method="DELETE")
        delete_request.add_header("Mcp-Session-Id", session_id)
        if auth_header and (streamable_url or bearer_url):
            delete_request.add_header("Authorization", auth_header)
        try:
            urllib.request.urlopen(delete_request, timeout=args.timeout).close()
        except Exception:
            pass
    return 1 if missing_required_tools or fingerprint_mismatch or installed_mismatch else 0


def command_print_config(args):
    discovery = load_json(Path(args.discovery_path) if args.discovery_path else discovery_path())
    legacy = {
        args.server_name: {
            "serverUrl": discovery.get("sse_url"),
            "disabled": False,
        }
    }
    bearer = {
        args.server_name: {
            "serverUrl": discovery.get("streamable_http_url") or discovery.get("bearer_sse_url"),
            "headers": {"Authorization": discovery.get("authorization_header")},
            "disabled": False,
        }
    }
    print(json.dumps({"legacyQueryToken": legacy, "bearerPreferred": bearer}, indent=2))
    return 0


def command_list_profiles(args):
    profiles = load_json(repo_root() / "tool_profiles.json")
    print(json.dumps(profiles, indent=2))
    return 0


def command_dump_schemas(args):
    payload = load_offline_mcp_surface()
    if args.output:
        write_json(Path(args.output), payload)
        print(f"Wrote FusionMCP MCP schemas: {args.output}")
    else:
        print(json.dumps(payload, indent=2))
    return 0


def command_test_live(args):
    script = repo_root() / "scripts" / "test_fusion_mcp_live.ps1"
    completed = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=str(repo_root()),
        check=False,
    )
    return completed.returncode


def command_test_fixture(args):
    script = repo_root() / "scripts" / "test_fusion_mcp_inspection_fixture.ps1"
    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-ExpectedPort",
        str(args.expected_port),
        "-TimeoutSec",
        str(args.timeout),
    ]
    if args.discovery_path:
        command.extend(["-DiscoveryPath", args.discovery_path])
    if args.report_path:
        command.extend(["-ReportPath", args.report_path])
    if args.skip_fixture_creation:
        command.append("-SkipFixtureCreation")
    if args.keep_fixture_document:
        command.append("-KeepFixtureDocument")
    completed = subprocess.run(
        command,
        cwd=str(repo_root()),
        check=False,
    )
    return completed.returncode


def command_test_3mf_fixture(args):
    script = repo_root() / "scripts" / "test_fusion_mcp_3mf_fixture.ps1"
    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-ExpectedPort",
        str(args.expected_port),
        "-TimeoutSec",
        str(args.timeout),
    ]
    if args.discovery_path:
        command.extend(["-DiscoveryPath", args.discovery_path])
    if args.export_path:
        command.extend(["-ExportPath", args.export_path])
    if args.keep_fixture_document:
        command.append("-KeepFixtureDocument")
    completed = subprocess.run(
        command,
        cwd=str(repo_root()),
        check=False,
    )
    return completed.returncode


def validate_fixture_report(report, required_probes=None, require_passed=None):
    required_probes = tuple(required_probes or REQUIRED_FIXTURE_PROBES)
    require_passed = set(require_passed or ())
    errors = []
    warnings = []
    if not isinstance(report, dict):
        return {"ok": False, "errors": ["Fixture report must be a JSON object."], "warnings": []}
    if report.get("status") != "passed":
        errors.append(f"Report status is {report.get('status')!r}, expected 'passed'.")
    if report.get("fixtureDocumentOpen"):
        errors.append("Fixture report says the temporary fixture document is still open.")
    if report.get("failure"):
        errors.append(f"Fixture report includes failure: {report.get('failure')}")
    probes = report.get("probes")
    if not isinstance(probes, list):
        errors.append("Fixture report probes must be a list.")
        probes = []
    probe_by_name = {}
    duplicate_names = set()
    for probe in probes:
        if not isinstance(probe, dict):
            errors.append("Fixture report contains a non-object probe entry.")
            continue
        name = probe.get("name")
        status = probe.get("status")
        if not name:
            errors.append("Fixture report contains a probe without a name.")
            continue
        if name in probe_by_name:
            duplicate_names.add(name)
        probe_by_name[name] = probe
        if status not in ACCEPTED_FIXTURE_PROBE_STATUSES:
            errors.append(f"Probe {name!r} has unexpected status {status!r}.")
    if duplicate_names:
        errors.append(f"Fixture report contains duplicate probe names: {', '.join(sorted(duplicate_names))}.")
    missing = [name for name in required_probes if name not in probe_by_name]
    if missing:
        errors.append(f"Fixture report is missing required probes: {', '.join(missing)}.")
    failed = [
        f"{probe.get('name')}={probe.get('status')}"
        for probe in probes
        if isinstance(probe, dict) and probe.get("status") not in ACCEPTED_FIXTURE_PROBE_STATUSES
    ]
    if failed:
        errors.append(f"Fixture report has failed probes: {', '.join(failed)}.")
    not_passed = [
        f"{name}={probe_by_name.get(name, {}).get('status')}"
        for name in sorted(require_passed)
        if probe_by_name.get(name, {}).get("status") != "passed"
    ]
    if not_passed:
        errors.append(f"Fixture report probes were not fully passed: {', '.join(not_passed)}.")
    for name, probe in sorted(probe_by_name.items()):
        if probe.get("status") in {"unsupported", "preflight_blocked"}:
            warnings.append(f"{name}: {probe.get('status')}")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "probeCount": len(probe_by_name),
        "requiredProbeCount": len(required_probes),
    }


def command_validate_fixture_report(args):
    report = load_json(Path(args.report_path))
    validation = validate_fixture_report(report, require_passed=args.require_passed)
    print(json.dumps(validation, indent=2))
    return 0 if validation["ok"] else 1


def fixture_report_matrix(report_paths):
    runs = []
    probe_names = list(REQUIRED_FIXTURE_PROBES)
    for index, report_path in enumerate(report_paths, start=1):
        path = Path(report_path)
        report = load_json(path)
        validation = validate_fixture_report(report)
        probe_by_name = {
            probe.get("name"): probe
            for probe in report.get("probes", [])
            if isinstance(probe, dict) and probe.get("name")
        }
        statuses = {
            probe_name: (probe_by_name.get(probe_name) or {}).get("status", "missing")
            for probe_name in probe_names
        }
        extra_probes = sorted(set(probe_by_name) - set(probe_names))
        run = {
            "label": path.stem or f"report-{index}",
            "path": str(path),
            "ok": validation["ok"],
            "status": report.get("status"),
            "startedAt": report.get("startedAt"),
            "completedAt": report.get("completedAt"),
            "mcpPath": report.get("mcpPath"),
            "probeCount": validation.get("probeCount", 0),
            "requiredProbeCount": validation.get("requiredProbeCount", len(probe_names)),
            "errors": validation.get("errors", []),
            "warnings": validation.get("warnings", []),
            "statuses": statuses,
            "extraProbes": extra_probes,
        }
        runs.append(run)
    return {
        "ok": all(run["ok"] for run in runs),
        "probeNames": probe_names,
        "runCount": len(runs),
        "runs": runs,
    }


def fixture_report_matrix_markdown(matrix):
    labels = [run["label"] for run in matrix.get("runs", [])]
    headers = ["Probe"] + labels
    rows = [headers, ["---"] * len(headers)]
    for probe_name in matrix.get("probeNames", []):
        row = [probe_name]
        for run in matrix.get("runs", []):
            row.append(run.get("statuses", {}).get(probe_name, "missing"))
        rows.append(row)
    summary = [
        f"# FusionMCP Fixture Report Matrix",
        "",
        f"- Overall status: {'ok' if matrix.get('ok') else 'failed'}",
        f"- Runs: {matrix.get('runCount', 0)}",
        "",
    ]
    table_lines = [
        "| " + " | ".join(str(cell) for cell in row) + " |"
        for row in rows
    ]
    return "\n".join(summary + table_lines) + "\n"


def command_fixture_report_matrix(args):
    matrix = fixture_report_matrix(args.report_paths)
    if args.output:
        if args.format == "markdown":
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(fixture_report_matrix_markdown(matrix), encoding="utf-8")
        else:
            write_json(Path(args.output), matrix)
        print(f"Wrote FusionMCP fixture report matrix: {args.output}")
    else:
        if args.format == "markdown":
            print(fixture_report_matrix_markdown(matrix), end="")
        else:
            print(json.dumps(matrix, indent=2))
    return 0 if matrix["ok"] else 1


def command_mock_server(args):
    from .mock_server import serve_mock_server

    serve_mock_server(host=args.host, port=args.port)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="fusion-mcp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install-addin")
    install.add_argument("--addins-root")
    install.add_argument("--addin-name", default=ADDIN_NAME)
    install.add_argument("--legacy-addin-name", default=LEGACY_ADDIN_NAME)
    install.add_argument("--keep-legacy-addin", action="store_true")
    install.set_defaults(func=command_install_addin)

    package = subparsers.add_parser("package-addin")
    package.add_argument("--output")
    package.add_argument("--addin-name", default=ADDIN_NAME)
    package.set_defaults(func=command_package_addin)

    sync = subparsers.add_parser("sync-config")
    sync.add_argument("--config-path")
    sync.add_argument("--discovery-path")
    sync.add_argument("--server-name", default=SERVER_NAME)
    sync.set_defaults(func=command_sync_config)

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--discovery-path")
    doctor.add_argument("--timeout", type=int, default=5)
    doctor.set_defaults(func=command_doctor)

    print_config = subparsers.add_parser("print-client-config")
    print_config.add_argument("--discovery-path")
    print_config.add_argument("--server-name", default=SERVER_NAME)
    print_config.set_defaults(func=command_print_config)

    profiles = subparsers.add_parser("list-profiles")
    profiles.set_defaults(func=command_list_profiles)

    schemas = subparsers.add_parser("dump-schemas")
    schemas.add_argument("--output")
    schemas.set_defaults(func=command_dump_schemas)

    mock = subparsers.add_parser("mock-server")
    mock.add_argument("--host", default="127.0.0.1")
    mock.add_argument("--port", type=int, default=9101)
    mock.set_defaults(func=command_mock_server)

    test_live = subparsers.add_parser("test-live")
    test_live.set_defaults(func=command_test_live)

    test_fixture = subparsers.add_parser("test-fixture")
    test_fixture.add_argument("--discovery-path")
    test_fixture.add_argument("--expected-port", type=int, default=9100)
    test_fixture.add_argument("--timeout", type=int, default=10)
    test_fixture.add_argument("--report-path")
    test_fixture.add_argument("--skip-fixture-creation", action="store_true")
    test_fixture.add_argument("--keep-fixture-document", action="store_true")
    test_fixture.set_defaults(func=command_test_fixture)

    test_3mf_fixture = subparsers.add_parser("test-3mf-fixture")
    test_3mf_fixture.add_argument("--discovery-path")
    test_3mf_fixture.add_argument("--expected-port", type=int, default=9100)
    test_3mf_fixture.add_argument("--timeout", type=int, default=20)
    test_3mf_fixture.add_argument("--export-path")
    test_3mf_fixture.add_argument("--keep-fixture-document", action="store_true")
    test_3mf_fixture.set_defaults(func=command_test_3mf_fixture)

    validate_fixture = subparsers.add_parser("validate-fixture-report")
    validate_fixture.add_argument("report_path")
    validate_fixture.add_argument(
        "--require-passed",
        action="append",
        default=[],
        help="Require a specific probe name to have status 'passed'. Can be repeated.",
    )
    validate_fixture.set_defaults(func=command_validate_fixture_report)

    matrix = subparsers.add_parser("fixture-report-matrix")
    matrix.add_argument("report_paths", nargs="+")
    matrix.add_argument("--output")
    matrix.add_argument("--format", choices=("json", "markdown"), default="json")
    matrix.set_defaults(func=command_fixture_report_matrix)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"fusion-mcp: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
