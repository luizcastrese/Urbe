from ._loader import export_public, load_root_module

module = load_root_module("urbe_app._legacy_store", "store.py")
export_public(module, globals())
