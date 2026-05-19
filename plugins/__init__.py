"""Auto-loader for GA plugins. Drop a .py into plugins/ and it activates on startup.

Each plugin decides internally whether to activate (e.g. check config exists).
If a plugin raises on import, it is caught and logged — never blocks GA startup.
"""
import os, importlib, sys

_PLUGINS_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_all():
    for fname in sorted(os.listdir(_PLUGINS_DIR)):
        if fname.startswith('_') or not fname.endswith('.py'):
            continue
        mod_name = f"plugins.{fname[:-3]}"
        try:
            importlib.import_module(mod_name)
        except Exception as e:
            print(f"[Plugins] ⚠️ {mod_name} failed: {e}")

# Only auto-load when GA imports us (not during pip install / docs generation)
if os.environ.get('GA_PLUGIN_SKIP'):
    pass
else:
    _load_all()
