import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from katy404_youtube_agent.local_oauth_status import (
    LocalOAuthStatusPage,
    OAuthStatusPageError,
)


def _read(url):
    with urllib.request.urlopen(url, timeout=2) as response:
        return response, response.read()


def _post(url):
    request = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=2) as response:
        return response, response.read()


def _request_with_host(url, host):
    parsed = urllib.parse.urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        connection.putrequest("GET", parsed.path, skip_host=True)
        connection.putheader("Host", host)
        connection.endheaders()
        return connection.getresponse()
    except Exception:
        connection.close()
        raise


def _assert_server_closed(url):
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(url, timeout=0.25)


def test_status_page_serves_only_fixed_state_and_static_html(capsys):
    opened_urls = []
    page = LocalOAuthStatusPage(browser_open=lambda url: opened_urls.append(url) or True)
    try:
        page.start()
        html_response, html_bytes = _read(page.url)
        html = html_bytes.decode("utf-8")
        status_response, status_bytes = _read(page.status_url)

        assert urllib.parse.urlparse(opened_urls[0]).hostname == "127.0.0.1"
        assert urllib.parse.urlparse(opened_urls[0]).port > 0
        assert html_response.status == 200
        assert json.loads(status_bytes) == {"state": "waiting"}
        assert "app.js" in html
        assert "style.css" in html
        assert "https://" not in html
        assert "access_token" not in html
        assert "refresh_token" not in html
        assert "refresh-value" not in html
        assert status_response.headers["Cache-Control"] == "no-store"
        assert status_response.headers["X-Content-Type-Options"] == "nosniff"
        assert status_response.headers["Referrer-Policy"] == "no-referrer"
        assert "default-src 'none'" in status_response.headers["Content-Security-Policy"]
        logs = capsys.readouterr()
        assert logs.out == ""
        assert logs.err == ""
    finally:
        page.close()


@pytest.mark.parametrize("state", ["waiting", "connected", "stopped"])
def test_status_endpoint_returns_only_the_selected_fixed_state(state):
    page = LocalOAuthStatusPage(browser_open=lambda _url: True)
    try:
        page.start()
        page.set_state(state)

        response, payload = _read(page.status_url)

        assert response.status == 200
        assert response.headers["Content-Type"].startswith("application/json")
        assert json.loads(payload) == {"state": state}
    finally:
        page.close()


def test_page_and_same_origin_static_assets_use_security_headers_and_local_urls():
    page = LocalOAuthStatusPage(browser_open=lambda _url: True)
    try:
        page.start()
        response, body = _read(page.url)
        html = body.decode("utf-8")
        local_origin = f"http://127.0.0.1:{urllib.parse.urlparse(page.url).port}/"
        script_path = re.search(r'<script[^>]+src="([^"]+)"', html).group(1)
        style_path = re.search(r'<link[^>]+href="([^"]+\.css)"', html).group(1)
        script_url = urllib.parse.urljoin(page.url, script_path)
        style_url = urllib.parse.urljoin(page.url, style_path)

        assert urllib.parse.urljoin(page.url, script_path).startswith(local_origin)
        assert urllib.parse.urljoin(page.url, style_path).startswith(local_origin)
        assert "http://" not in html
        assert "https://" not in html
        assert response.headers["Content-Security-Policy"]
        for asset_url in (script_url, style_url):
            asset_response, asset_body = _read(asset_url)
            assert asset_response.status == 200
            assert asset_response.headers["Cache-Control"] == "no-store"
            assert "http://" not in asset_body.decode("utf-8")
            assert "https://" not in asset_body.decode("utf-8")
            if asset_url == script_url:
                assert 'fetch("ack"' in asset_body.decode("utf-8")
    finally:
        page.close()


def test_unknown_host_and_nonce_routes_cannot_read_status():
    page = LocalOAuthStatusPage(browser_open=lambda _url: True)
    try:
        page.start()
        parsed = urllib.parse.urlparse(page.status_url)
        wrong_host = _request_with_host(page.status_url, f"example.test:{parsed.port}")
        assert wrong_host.status == 404
        wrong_host.read()

        wrong_nonce_url = urllib.parse.urlunparse(
            parsed._replace(path=f"/wrong-session{parsed.path.rsplit('/', 1)[-1]}")
        )
        with pytest.raises(urllib.error.HTTPError) as wrong_nonce:
            urllib.request.urlopen(wrong_nonce_url, timeout=2)
        assert wrong_nonce.value.code == 404

        wrong_route_url = urllib.parse.urlunparse(parsed._replace(path=f"{parsed.path}/extra"))
        with pytest.raises(urllib.error.HTTPError) as wrong_route:
            urllib.request.urlopen(wrong_route_url, timeout=2)
        assert wrong_route.value.code == 404
    finally:
        page.close()


def test_terminal_status_read_acknowledges_and_closes_server_promptly():
    page = LocalOAuthStatusPage(
        browser_open=lambda _url: True,
        terminal_read_timeout_seconds=2,
    )
    page.start()
    page.set_state("connected")
    _, payload = _read(page.status_url)
    assert json.loads(payload) == {"state": "connected"}
    ack_response, ack_payload = _post(urllib.parse.urljoin(page.url, "ack"))
    assert ack_response.status == 204
    assert ack_payload == b""

    started = time.monotonic()
    page.finish()
    elapsed = time.monotonic() - started

    assert elapsed < 1
    _assert_server_closed(page.url)


def test_terminal_state_times_out_and_closes_server_without_browser_acknowledgement():
    page = LocalOAuthStatusPage(
        browser_open=lambda _url: True,
        terminal_read_timeout_seconds=0.05,
    )
    page.start()
    page.set_state("stopped")
    _, payload = _read(page.status_url)
    assert json.loads(payload) == {"state": "stopped"}

    started = time.monotonic()
    page.finish()
    elapsed = time.monotonic() - started
    page.close()

    assert 0.04 <= elapsed < 2
    _assert_server_closed(page.url)


def test_acknowledgement_while_waiting_does_not_finish_page():
    page = LocalOAuthStatusPage(
        browser_open=lambda _url: True,
        terminal_read_timeout_seconds=0.05,
    )
    page.start()
    ack_url = urllib.parse.urljoin(page.url, "ack")
    with pytest.raises(urllib.error.HTTPError) as acknowledgement:
        _post(ack_url)
    assert acknowledgement.value.code == 409

    started = time.monotonic()
    page.finish()
    elapsed = time.monotonic() - started

    assert 0.04 <= elapsed < 2
    _assert_server_closed(page.url)


def test_invalid_state_is_rejected_without_changing_current_status():
    page = LocalOAuthStatusPage(browser_open=lambda _url: True)
    try:
        page.start()
        with pytest.raises(ValueError):
            page.set_state("authorizing")  # type: ignore[arg-type]

        _, payload = _read(page.status_url)
        assert json.loads(payload) == {"state": "waiting"}
    finally:
        page.close()


@pytest.mark.parametrize("failure", [False, RuntimeError("private browser error")])
def test_browser_open_failure_raises_and_closes_server(failure):
    opened_urls = []

    def browser_open(url):
        opened_urls.append(url)
        if isinstance(failure, Exception):
            raise failure
        return failure

    page = LocalOAuthStatusPage(browser_open=browser_open)
    with pytest.raises(OAuthStatusPageError) as error:
        page.start()

    assert opened_urls
    assert "private browser error" not in str(error.value)
    _assert_server_closed(opened_urls[0])
    page.close()
