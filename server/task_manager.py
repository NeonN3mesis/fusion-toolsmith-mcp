"""
Task Manager Module for FusionMCP
"""

import json
import uuid
import threading
import time
from typing import Dict, Callable, Any, Optional

try:
    import adsk.core
    app = adsk.core.Application.get()
except ImportError:
    app = None


def safe_log(message: str):
    import threading
    global app
    if app and threading.current_thread() == threading.main_thread():
        app.log(message)
    else:
        print(message)


class TaskManager:
    """
    TaskManager class for handling custom events and task execution.
    """

    _instance = None
    _event_handler = None
    _custom_event = None
    _pending_tasks: Dict[str, Dict[str, Any]] = {}
    _pending_tasks_lock = threading.Lock()
    _is_running = False
    TASK_TIMEOUT_SECONDS = 60.0
    MAX_PENDING_TASKS = 8

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TaskManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._event_handler = None
            self._custom_event = None
            self._pending_tasks = {}
            self._is_running = False
            self._initialized = True

    @classmethod
    def start(cls) -> bool:
        global app
        if not app:
            app = adsk.core.Application.get()
        if not app:
            print("TaskManager: Fusion 360 application not available")
            return False

        if cls._is_running:
            return True

        try:
            cls._custom_event = app.registerCustomEvent('FusionMCP.TaskManagerEvent')
            cls._event_handler = TaskEventHandler(cls._pending_tasks)
            cls._custom_event.add(cls._event_handler)
            cls._is_running = True
            safe_log("TaskManager: Started successfully")
            return True
        except Exception as e:
            print(f"TaskManager: Failed to start - {str(e)}")
            safe_log(f"TaskManager: Failed to start - {str(e)}")
            return False

    @classmethod
    def stop(cls) -> bool:
        if not cls._is_running:
            return True

        try:
            if cls._custom_event and cls._event_handler:
                cls._custom_event.remove(cls._event_handler)
                cls._event_handler = None
                try:
                    app.unregisterCustomEvent('FusionMCP.TaskManagerEvent')
                except Exception as unreg_err:
                    if app:
                        app.log(f"TaskManager: Failed to unregister custom event: {unreg_err}")
                cls._custom_event = None

            with cls._pending_tasks_lock:
                cls._pending_tasks.clear()
            cls._is_running = False
            safe_log("TaskManager: Stopped successfully")
            return True
        except Exception as e:
            print(f"TaskManager: Failed to stop - {str(e)}")
            safe_log(f"TaskManager: Failed to stop - {str(e)}")
            return False

    @classmethod
    def post(cls, command: str, callback: Callable[[Dict[str, Any]], None], data: Dict[str, Any]) -> Optional[str]:
        global app
        if not cls._is_running:
            print("TaskManager: Not running, cannot post task")
            return None

        if not callable(callback):
            print("TaskManager: Callback must be callable")
            return None

        try:
            if not app:
                print("TaskManager: Application not initialized")
                return None
            cls.prune_stale_tasks()
            task_id = str(uuid.uuid4())
            with cls._pending_tasks_lock:
                if len(cls._pending_tasks) >= cls.MAX_PENDING_TASKS:
                    print("TaskManager: Too many pending tasks, rejecting new task")
                    return None
                cls._pending_tasks[task_id] = {
                    'command': command,
                    'callback': callback,
                    'data': data,
                    'created_at': time.time(),
                }
            event_data = {
                'task_id': task_id,
                'command': command,
                'data': data
            }
            app.fireCustomEvent(cls._custom_event.eventId, json.dumps(event_data))
            safe_log(f"TaskManager: Posted task {task_id} with command '{command}'")
            return task_id
        except Exception as e:
            if 'task_id' in locals():
                with cls._pending_tasks_lock:
                    cls._pending_tasks.pop(task_id, None)
            print(f"TaskManager: Failed to post task - {str(e)}")
            safe_log(f"TaskManager: Failed to post task - {str(e)}")
            return None

    @classmethod
    def is_running(cls) -> bool:
        return cls._is_running

    @classmethod
    def get_pending_task_count(cls) -> int:
        cls.prune_stale_tasks()
        with cls._pending_tasks_lock:
            return len(cls._pending_tasks)

    @classmethod
    def prune_stale_tasks(cls, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        removed = 0
        with cls._pending_tasks_lock:
            for task_id, task_info in list(cls._pending_tasks.items()):
                created_at = task_info.get('created_at')
                if created_at is None:
                    continue
                if now - created_at > cls.TASK_TIMEOUT_SECONDS:
                    cls._pending_tasks.pop(task_id, None)
                    removed += 1
        if removed:
            safe_log(f"TaskManager: Pruned {removed} stale pending task(s)")
        return removed

    @classmethod
    def get_pending_task_stats(cls, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        cls.prune_stale_tasks(now=now)
        with cls._pending_tasks_lock:
            ages = []
            tasks = []
            for task_id, task_info in cls._pending_tasks.items():
                created_at = task_info.get('created_at')
                age = None if created_at is None else max(0.0, now - created_at)
                if age is not None:
                    ages.append(age)
                tasks.append({
                    'task_id': task_id,
                    'command': task_info.get('command'),
                    'ageSeconds': round(age, 3) if age is not None else None,
                })
            pending_count = len(cls._pending_tasks)
        return {
            'pendingTasks': pending_count,
            'oldestTaskAgeSeconds': round(max(ages), 3) if ages else 0.0,
            'taskTimeoutSeconds': cls.TASK_TIMEOUT_SECONDS,
            'maxPendingTasks': cls.MAX_PENDING_TASKS,
            'backpressureActive': pending_count >= cls.MAX_PENDING_TASKS,
            'tasks': tasks,
        }


class TaskEventHandler(adsk.core.CustomEventHandler):
    def __init__(self, pending_tasks: Dict[str, Dict[str, Any]]):
        super().__init__()
        self._pending_tasks = pending_tasks

    def notify(self, args: adsk.core.CustomEventArgs):
        try:
            event_data = json.loads(args.additionalInfo)
            task_id = event_data.get('task_id')
            command = event_data.get('command')
            
            with TaskManager._pending_tasks_lock:
                if not task_id or task_id not in self._pending_tasks:
                    safe_log(f"TaskManager: Unknown task ID {task_id}")
                    return
                task_info = self._pending_tasks[task_id]
                callback = task_info['callback']
                task_data = task_info['data']

            try:
                callback(task_data)
                safe_log(f"TaskManager: Executed task {task_id} with command '{command}'")
            except Exception as callback_error:
                print(f"TaskManager: Callback error for task {task_id}: {str(callback_error)}")
                safe_log(f"TaskManager: Callback error for task {task_id}: {str(callback_error)}")

            with TaskManager._pending_tasks_lock:
                if task_id in self._pending_tasks:
                    del self._pending_tasks[task_id]

        except json.JSONDecodeError as e:
            print(f"TaskManager: Failed to parse event data: {str(e)}")
        except Exception as e:
            print(f"TaskManager: Event handler error: {str(e)}")


def start_task_manager() -> bool:
    return TaskManager.start()


def stop_task_manager() -> bool:
    return TaskManager.stop()
