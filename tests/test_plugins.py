import asyncio

from app.plugins.manager import PluginManager


def test_plugin_manager_loads_universal_style_plugin(tmp_path):
    plugin_path = tmp_path / "sample.py"
    plugin_path.write_text(
        "NAME = 'sample'\nseen = []\n"
        "async def handler(*args): seen.append(args)\n"
        "EVENT_HANDLERS = {'NEW_MESSAGE': [handler]}\n",
        encoding="utf-8",
    )
    manager = PluginManager(str(tmp_path))
    plugins = manager.load()
    asyncio.run(manager.dispatch("NEW_MESSAGE", "event"))
    assert plugins[0].module.seen == [("event",)]
