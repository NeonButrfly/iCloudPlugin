from importlib import import_module


def test_classifier_role_can_import_api_server():
    module = import_module("apps.classifier.api_server")

    assert hasattr(module, "APP")
