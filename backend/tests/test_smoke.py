import app


def test_package_exposes_version() -> None:
    assert app.__version__ == "0.1.0"
