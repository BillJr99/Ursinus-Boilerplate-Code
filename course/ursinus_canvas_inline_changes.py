#!/usr/bin/env python3
# Moved to course/inline_changes/ursinus_canvas_inline_changes.py; this entry point runs it unchanged.
import importlib.util
import os
import sys

_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "inline_changes", "ursinus_canvas_inline_changes.py")
_spec = importlib.util.spec_from_file_location("ursinus_canvas_inline_changes", _path)
_impl = importlib.util.module_from_spec(_spec)
sys.modules["ursinus_canvas_inline_changes"] = _impl  # an import of this file gets the real module
_spec.loader.exec_module(_impl)

if __name__ == "__main__":
    sys.exit(_impl.main())
