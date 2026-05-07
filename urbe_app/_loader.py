from importlib import util
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent


def load_root_module(module_name: str, relative_path: str):
    """Load a legacy root-level module under the urbe_app package namespace.

    This keeps the existing root files working while the deploy entrypoint uses
    `python -m urbe_app.server`. Relative imports inside those files resolve
    against the real `urbe_app` package.
    """
    module_path = ROOT_DIR / relative_path
    spec = util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {relative_path} as {module_name}")

    module = util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def export_public(module, namespace: dict):
    for name, value in module.__dict__.items():
        if name.startswith("__") and name not in {"__doc__"}:
            continue
        namespace[name] = value
