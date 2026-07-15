"""
Fusion MCP Add-In
Clean Entry Point
"""

import adsk.core, adsk.fusion, traceback
import importlib
import os
import sys
import threading

app = None
ui = None
backgroundThread = None
mcp_server_module = None
task_manager_module = None


def _addin_root():
    return os.path.dirname(os.path.abspath(__file__))


def _runtime_prefixes():
    prefixes = ["server", "tools", "mcp_primitives"]
    package = __package__
    if package:
        prefixes.extend([
            f"{package}.server",
            f"{package}.tools",
            f"{package}.mcp_primitives",
        ])
    return tuple(prefixes)


def _clear_runtime_modules():
    for name in sorted(list(sys.modules), key=len, reverse=True):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in _runtime_prefixes()):
            sys.modules.pop(name, None)


def _ensure_addin_root_on_path():
    addin_root = _addin_root()
    if addin_root and addin_root not in sys.path:
        sys.path.insert(0, addin_root)
    return addin_root


def _load_runtime_modules(force_reload=False):
    global mcp_server_module, task_manager_module
    if force_reload:
        _clear_runtime_modules()
    _ensure_addin_root_on_path()
    importlib.invalidate_caches()
    if __package__:
        mcp_server_module = importlib.import_module(".server.mcp_server", __package__)
        task_manager_module = importlib.import_module(".server.task_manager", __package__)
    else:
        mcp_server_module = importlib.import_module("server.mcp_server")
        task_manager_module = importlib.import_module("server.task_manager")
    return mcp_server_module, task_manager_module


def start_server():
    server_module, _ = _load_runtime_modules(force_reload=False)
    return server_module.start_server()


def stop_server():
    server_module, _ = _load_runtime_modules(force_reload=False)
    return server_module.stop_server()


def start_task_manager():
    _, manager_module = _load_runtime_modules(force_reload=False)
    return manager_module.start_task_manager()


def stop_task_manager():
    _, manager_module = _load_runtime_modules(force_reload=False)
    return manager_module.stop_task_manager()


def _try_stop_runtime_modules():
    stopped_any = False
    errors = []
    server_module = mcp_server_module
    manager_module = task_manager_module
    if server_module is None or manager_module is None:
        try:
            server_module, manager_module = _load_runtime_modules(force_reload=False)
        except Exception as exc:
            return stopped_any, [f"runtime modules unavailable during stop: {exc}"]

    if server_module:
        try:
            server_module.stop_server()
            stopped_any = True
        except Exception as exc:
            errors.append(f"stop_server failed: {exc}")
    if manager_module:
        try:
            manager_module.stop_task_manager()
            stopped_any = True
        except Exception as exc:
            errors.append(f"stop_task_manager failed: {exc}")
    return stopped_any, errors


def run(context):
    global app, ui, backgroundThread
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface
        server_module, manager_module = _load_runtime_modules(force_reload=True)
        mcp_server_module.app = app
        task_manager_module.app = app

        app.log("Starting Fusion MCP Add-In")

        # Start the TaskManager (registers custom event and handler)
        if not manager_module.start_task_manager():
            raise Exception("Failed to start TaskManager")

        # Start HTTP/SSE server in a background daemon thread
        backgroundThread = threading.Thread(target=server_module.start_server, daemon=True, name="FusionMCP-ServerThread")
        backgroundThread.start()

        app.log("Fusion MCP Add-In started successfully!")
    except Exception as e:
        if ui:
            ui.messageBox(f'Failed to start Fusion MCP Add-In:\n{str(e)}\n{traceback.format_exc()}')
        elif app:
            app.log(f'Failed to start Fusion MCP Add-In:\n{str(e)}\n{traceback.format_exc()}')

def stop(context):
    global backgroundThread, app, ui
    try:
        if app:
            app.log("Stopping Fusion MCP Add-In")
        stopped_runtime, stop_errors = _try_stop_runtime_modules()
        for stop_error in stop_errors:
            if app:
                app.log(f"Fusion MCP Add-In stop warning: {stop_error}")

        if backgroundThread and backgroundThread.is_alive():
            backgroundThread.join(timeout=2.0)
        backgroundThread = None

        if app:
            if stopped_runtime:
                app.log("Fusion MCP Add-In stopped successfully.")
            else:
                app.log("Fusion MCP Add-In stopped without loaded runtime modules.")
    except Exception as e:
        if ui:
            ui.messageBox(f'Failed to stop Fusion MCP Add-In cleanly:\n{str(e)}\n{traceback.format_exc()}')
        elif app:
            app.log(f'Failed to stop Fusion MCP Add-In cleanly:\n{str(e)}\n{traceback.format_exc()}')
