import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

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
REQUIRED_LIVE_TOOLS = (
    "inspect_design",
    "recommend_mcp_workflow",
    "extract_reference_dimensions",
    "inspect_printability",
    "get_physical_properties",
    "get_body_faces",
    "get_body_edges",
    "get_assembly_tree",
    "get_assembly_references",
    "get_assembly_joints",
    "list_appearances",
    "inspect_body_style",
    "get_timeline",
    "measure_entity",
    "validate_model",
    "assess_change_impact",
    "preflight_model_change",
    "offset_face_or_press_pull",
    "create_offset_plane",
    "create_construction_point",
    "create_construction_axis",
    "create_rigid_joint",
    "add_sketch_constraint",
    "delete_sketch_constraint",
    "create_sketch_offset",
    "create_parametric_feature",
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
    "set_camera",
    "shell_body",
    "set_visibility",
    "capture_demo_sequence",
    "prompt_user",
    "list_documents",
    "set_timeline_marker",
    "clone_timeline_feature",
)


def repo_root():
    return Path(__file__).resolve().parents[1]


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
    bearer_url = discovery.get("bearer_sse_url")
    auth_header = discovery.get("authorization_header")
    sse_url = discovery.get("sse_url")
    url = bearer_url or sse_url
    if not url:
        raise RuntimeError("Discovery file does not contain bearer_sse_url or sse_url.")

    health_url = url.split("/sse", 1)[0] + "/health"
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
        if bearer_url and auth_header:
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
    if session_id:
        delete_request = urllib.request.Request(url, method="DELETE")
        delete_request.add_header("Mcp-Session-Id", session_id)
        if bearer_url and auth_header:
            delete_request.add_header("Authorization", auth_header)
        try:
            urllib.request.urlopen(delete_request, timeout=args.timeout).close()
        except Exception:
            pass
    return 1 if missing_required_tools else 0


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
            "serverUrl": discovery.get("bearer_sse_url"),
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
