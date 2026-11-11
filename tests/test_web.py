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
