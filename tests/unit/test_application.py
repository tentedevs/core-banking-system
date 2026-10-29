import importlib


def test_layer_packages_are_importable() -> None:
    for name in ("domain", "application", "ports", "api", "infrastructure"):
        assert importlib.import_module(name).__file__ is not None
