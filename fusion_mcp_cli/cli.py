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


ADDIN_NAME = "FusionMCP"
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


def repo_root():
    return Path(__file__).resolve().parents[1]


def default_addins_root():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not set; pass --addins-root explicitly.")
    return Path(appdata) / "Autodesk" / "Autodesk Fusion 360" / "API" / "AddIns"


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

    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    }).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if bearer_url and auth_header:
        request.add_header("Authorization", auth_header)
    session_id = None
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            session_id = response.headers.get("Mcp-Session-Id")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Initialize failed with HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}")
    print(json.dumps({"initialize": payload, "sessionId": session_id}, indent=2))
    if session_id:
        delete_request = urllib.request.Request(url, method="DELETE")
        delete_request.add_header("Mcp-Session-Id", session_id)
        if bearer_url and auth_header:
            delete_request.add_header("Authorization", auth_header)
        try:
            urllib.request.urlopen(delete_request, timeout=args.timeout).close()
        except Exception:
            pass
    return 0


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


def command_test_live(args):
    script = repo_root() / "scripts" / "test_fusion_mcp_live.ps1"
    completed = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=str(repo_root()),
        check=False,
    )
    return completed.returncode


def build_parser():
    parser = argparse.ArgumentParser(prog="fusion-mcp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install-addin")
    install.add_argument("--addins-root")
    install.add_argument("--addin-name", default=ADDIN_NAME)
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
