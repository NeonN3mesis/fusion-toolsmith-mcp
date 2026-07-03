"""
Fusion MCP Add-In
Clean Entry Point
"""

import adsk.core, adsk.fusion, traceback
import threading

# Import server and task manager logic
try:
    from .server.mcp_server import start_server, stop_server
    from .server.task_manager import start_task_manager, stop_task_manager
except ImportError:
    from server.mcp_server import start_server, stop_server
    from server.task_manager import start_task_manager, stop_task_manager

app = None
ui = None
backgroundThread = None

def run(context):
    global app, ui, backgroundThread
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        app.log("Starting Fusion MCP Add-In")

        # Start the TaskManager (registers custom event and handler)
        if not start_task_manager():
            raise Exception("Failed to start TaskManager")

        # Start HTTP/SSE server in a background daemon thread
        backgroundThread = threading.Thread(target=start_server, daemon=True, name="FusionMCP-ServerThread")
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

        # Stop HTTP server and clean up sockets/files
        stop_server()

        # Stop TaskManager custom event handler
        stop_task_manager()

        if backgroundThread and backgroundThread.is_alive():
            backgroundThread.join(timeout=2.0)
        backgroundThread = None

        if app:
            app.log("Fusion MCP Add-In stopped successfully.")
    except Exception as e:
        if ui:
            ui.messageBox(f'Failed to stop Fusion MCP Add-In cleanly:\n{str(e)}\n{traceback.format_exc()}')
        elif app:
            app.log(f'Failed to stop Fusion MCP Add-In cleanly:\n{str(e)}\n{traceback.format_exc()}')
