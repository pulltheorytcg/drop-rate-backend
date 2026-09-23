from pathlib import Path


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "backend" / "app" / "static"


def test_dashboard_assets_exist() -> None:
    for name in ("index.html", "styles.css", "app.js"):
        path = STATIC / name
        assert path.is_file()
        assert path.stat().st_size > 500


def test_dashboard_has_auth_and_inventory_controls() -> None:
    html = (STATIC / "index.html").read_text()
    for element_id in (
        "login-form",
        "request-reset-form",
        "new-password-form",
        "dashboard-view",
        "inventory-body",
        "editor-dialog",
        "bulk-dialog",
        "issue-buttons",
        "logout-button",
    ):
        assert f'id="{element_id}"' in html


def test_client_does_not_contain_privileged_credentials() -> None:
    combined = "\n".join((STATIC / name).read_text() for name in ("index.html", "styles.css", "app.js"))
    assert "service_role" not in combined
    assert "TCG_DATABASE_URL" not in combined
    assert "postgresql://" not in combined
