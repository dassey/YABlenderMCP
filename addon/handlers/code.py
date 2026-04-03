"""execute_code handler - runs arbitrary Python inside Blender."""

import io
import traceback
from contextlib import redirect_stdout

import bpy

from . import register_handler


def execute_code(code: str) -> dict:
    namespace = {"bpy": bpy}
    capture = io.StringIO()
    try:
        with redirect_stdout(capture):
            exec(code, namespace)
        return {"executed": True, "result": capture.getvalue()}
    except Exception:
        return {"executed": False, "error": traceback.format_exc(), "result": capture.getvalue()}


register_handler("execute_code", execute_code)
