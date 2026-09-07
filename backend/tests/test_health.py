from fastapi.testclient import TestClient

from redactpdf.main import app
from redactpdf.presets import DEFAULT_REGION


def test_health_ok() -> None:
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_config_exposes_the_default_region() -> None:
    """L'UI a besoin de la région pour que son aperçu du preset téléphone
    corresponde à ce que le backend caviardera réellement."""
    client = TestClient(app)
    for prefix in ("", "/api"):
        resp = client.get(f"{prefix}/config")
        assert resp.status_code == 200, prefix
        assert resp.json()["default_region"] == DEFAULT_REGION
