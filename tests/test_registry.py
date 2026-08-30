import pytest
from proxify.plugins.base import BasePlugin
from proxify.plugins.registry import register_plugin, get_all_plugin_classes, discover_plugins

def test_plugin_registration():
    # Record initial state
    initial_plugins = len(get_all_plugin_classes())
    
    # Define a dummy plugin
    @register_plugin("dummy_test_plugin")
    class DummyPlugin(BasePlugin):
        name = "Dummy"
        
    plugins = get_all_plugin_classes()
    
    assert "dummy_test_plugin" in plugins
    assert plugins["dummy_test_plugin"] == DummyPlugin
    assert len(plugins) == initial_plugins + 1

def test_discover_plugins():
    # Calling discover_plugins should load at least Zalo, Facebook, YouTube
    discover_plugins()
    plugins = get_all_plugin_classes()
    
    assert "zalo" in plugins
    assert "facebook" in plugins
    assert "youtube" in plugins
    assert issubclass(plugins["zalo"], BasePlugin)
