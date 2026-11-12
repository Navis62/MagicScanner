import pytest
from fastapi.testclient import TestClient

from magicscanner.web.app import app


@pytest.mark.parametrize("path", ["/", "/static/js/main.js", "/static/js/edition.js", "/static/style.css"])
def test_the_interface_is_revalidated_on_every_load(path):
    """Une ancienne index.html gardée en cache tournait avec un JS plus récent : « set-pick » introuvable, la fiche de
    la carte restait vide. Page et fichiers doivent être revalidés ensemble."""
    response = TestClient(app).get(path)   # sans « with » : pas de démarrage (base, OCR)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_the_api_is_not_revalidated_by_the_interface_middleware():
    """Les routes « /api/ » restent hors du régime « no-cache » de l'interface. Toutes les routes réelles ont besoin
    de « svc » (base, OCR), absent sans lifespan : une route inexistante sous « /api/ » (404 FastAPI) traverse quand
    même le middleware, ce qui suffit à prouver l'exclusion."""
    response = TestClient(app).get("/api/inexistante")   # sans « with » : pas de démarrage (base, OCR)
    assert response.status_code == 404
    assert "cache-control" not in response.headers
