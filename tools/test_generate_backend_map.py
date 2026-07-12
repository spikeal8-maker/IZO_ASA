from __future__ import annotations

from pathlib import Path

from tools.generate_backend_map import parse_source, render


def test_route_and_auth_detection(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
class App:
    def get(self, path):
        return lambda function: function

app = App()

def require_trusted_admin(request):
    return request

@app.get('/api/admin/example')
async def example(request):
    require_trusted_admin(request)
    return {'ok': True}
""".strip(),
        encoding="utf-8",
    )

    symbols, routes = parse_source(source)

    assert any(symbol.name == "example" for symbol in symbols)
    assert len(routes) == 1
    assert routes[0].method == "GET"
    assert routes[0].path == "/api/admin/example"
    assert routes[0].auth == "admin"
    assert "`/api/admin/example`" in render(source, symbols, routes)


def test_operational_route_without_gate_is_marked_for_review(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
class App:
    def post(self, path):
        return lambda function: function

app = App()

@app.post('/api/telegram/set-webhook')
async def set_webhook():
    return {'ok': True}
""".strip(),
        encoding="utf-8",
    )

    _, routes = parse_source(source)

    assert routes[0].auth == "REVIEW: operational route without detected gate"
