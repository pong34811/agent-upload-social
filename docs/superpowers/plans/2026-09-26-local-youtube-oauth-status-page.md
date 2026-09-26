# Local YouTube OAuth Status Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** เปิดหน้า local แสดงสถานะ OAuth อัตโนมัติเมื่อคำสั่ง upload ไม่พบ credential แล้วเก็บ credential ใน Windows Credential Manager ก่อนตรวจ channel และอัปโหลดต่อ

**Architecture:** เพิ่ม HTTP status page อายุสั้นบน loopback ด้วย Python standard library แล้วเชื่อมเข้า callback ของ OAuth Desktop flow หลังตรวจ client file ผ่านแล้ว หน้ารายงานแค่ `waiting`, `connected`, `stopped`; CLI และ upload runner ยังคงรับผิดชอบ channel verification และทุก upload gate เดิม

**Tech Stack:** Python 3.13–3.14, `http.server`, `threading`, `secrets`, `webbrowser`, `urllib`, `google-auth-oauthlib` ที่มีอยู่, pytest ที่มีอยู่

**Spec:** `docs/superpowers/specs/2026-09-26-local-oauth-login-page-design.md`

## Global Constraints

- ผู้ใช้คนเดียว ใช้บน Windows ภายในเครื่อง `D:\agent-upload-social`.
- HTTP status page bind เฉพาะ `127.0.0.1` และใช้พอร์ตว่างจากระบบ.
- ใช้ OAuth Desktop client ที่เจ้าของเลือกจาก Google Cloud.
- ใช้ scope เดิมเท่านั้น: `youtube.upload` และ `youtube.readonly`.
- เก็บ OAuth credential ใน Windows Credential Manager; ห้ามเขียน token ลงไฟล์, log, URL หรือ HTML.
- ตรวจ configuration ก่อนเปิด browser; ใช้โฟลเดอร์และ channel ที่ผู้ใช้ระบุเท่านั้น.
- ใช้ Python standard library สำหรับหน้า local; ไม่มี frontend dependency, CDN, analytics หรือ resource จาก third party.
- ไม่เปลี่ยนข้อกำหนด Private pilot และการอนุมัติแยกก่อน batch เต็ม.
- OAuth consent ยังคงเป็นการกระทำของเจ้าของในหน้า Google; หาก OAuth ล้มเหลวหรือบันทึก credential ไม่สำเร็จต้องหยุดก่อน upload.

## Review Focus

- Request ที่มี Host ผิดหรือ route/session ID ที่เดาไม่ถูกต้องต้องไม่อ่านสถานะ และ response ต้องไม่มี OAuth credential — pin in Task 1.
- Browser ไม่ acknowledge หลังอ่านสถานะปลายทางต้องทำให้ local server ปิดภายใน timeout 5 วินาที — pin in Task 1.
- `webbrowser.open()` ที่คืน `False` หรือโยน exception ต้องปิด local server, หยุดก่อน Google OAuth และไม่มี upload — pin in Tasks 1–2.
- OAuth client ที่ไม่ใช่ Desktop installed-app JSON ต้องถูกปฏิเสธก่อนหน้า local หรือ Google OAuth เปิด — pin in Task 2.
- Google ปฏิเสธ consent หรือ Credential Manager บันทึกไม่ได้ต้องแสดง `stopped`, ไม่เปิดเผย exception/secret และไม่ upload — pin in Task 2.
- OAuth ผ่านแต่ไม่พบ channel เป้าหมายต้องหยุดก่อน video upload และคง credential ไว้ — pin in Tasks 2–3.

---

### Task 1: Local OAuth status page server

**Files:**
- Create: `src/katy404_youtube_agent/local_oauth_status.py`
- Create: `tests/test_local_oauth_status.py`

**Interfaces:**
- Produces `OAuthPageState = Literal["waiting", "connected", "stopped"]`.
- Produces `OAuthStatusPageError(RuntimeError)` for local server/browser startup failures.
- Produces `LocalOAuthStatusPage(*, browser_open: Callable[[str], bool] | None = None, terminal_read_timeout_seconds: float = 5.0)`.
- `start() -> None` binds `127.0.0.1` on an OS-selected port, starts a daemon server thread, and opens the generated local page URL; it raises `OAuthStatusPageError` and cleans up if bind or browser opening fails.
- Read-only properties `url: str` and `status_url: str` expose only the local page URLs containing a per-instance `secrets.token_urlsafe(24)` route nonce.
- `set_state(state: OAuthPageState) -> None` accepts only the three declared states.
- `finish() -> None` waits for a same-origin `POST /<nonce>/ack` after the page reads a terminal state, for at most `terminal_read_timeout_seconds`, then shuts down the server; `close() -> None` performs immediate idempotent cleanup.

- [x] **Step 1: Write the failing status page tests**

Create tests for static content, each exact status JSON value, loopback-only URL, nonce-protected routes, security headers, no external resources, no request logging, terminal acknowledgement, timeout shutdown after terminal status was read without acknowledgement, invalid state rejection, and browser opener returning `False` or raising. The page must POST to `/<nonce>/ack` only after it reads and displays a terminal state; an acknowledgement while the server is still `waiting` must not complete the wait. For either browser opener failure, assert `start()` raises `OAuthStatusPageError` and closes the bound server. Start with this representative test:

```python
def test_status_page_serves_only_fixed_state_and_static_html():
    opened_urls = []
    page = LocalOAuthStatusPage(browser_open=lambda url: opened_urls.append(url) or True)
    try:
        page.start()
        page.set_state("waiting")
        with urllib.request.urlopen(page.url) as response:
            html = response.read().decode("utf-8")
        with urllib.request.urlopen(page.status_url) as response:
            status = json.load(response)
        assert urllib.parse.urlparse(opened_urls[0]).hostname == "127.0.0.1"
        assert status == {"state": "waiting"}
        assert "app.js" in html
        assert "https://" not in html
        assert "refresh-value" not in html
    finally:
        page.close()
```

- [x] **Step 2: Run the new tests and confirm they fail before implementation**

Run: `pytest tests/test_local_oauth_status.py -q`
Expected: collection fails because `katy404_youtube_agent.local_oauth_status` does not exist yet.

- [x] **Step 3: Implement the page and bounded server lifecycle**

Use `ThreadingHTTPServer(("127.0.0.1", 0), handler)` and a daemon `serve_forever` thread. The handler must serve `GET /<nonce>/`, `GET /<nonce>/status`, same-origin static JavaScript/CSS, and `POST /<nonce>/ack`; reject other hosts/routes with 404; emit `Content-Security-Policy`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, and `Referrer-Policy: no-referrer`; suppress access logs; return only `{"state": "waiting|connected|stopped"}` from status; accept a bodyless acknowledgement only after a terminal state; and set an in-memory event after responding to that acknowledgement. The static page maps these fixed states to Thai messages, polls status every 500 ms, displays terminal status, posts acknowledgement once, and stops polling on `connected` or `stopped`. Do not include dynamic OAuth data in HTML, status JSON, or acknowledgement response.

- [x] **Step 4: Run the full new page test module**

Run: `pytest tests/test_local_oauth_status.py -q`
Expected: all tests in this module pass, including invalid Host/path, terminal acknowledgement, and timeout shutdown.

- [x] **Step 5: Commit the page module**

```powershell
git add src/katy404_youtube_agent/local_oauth_status.py tests/test_local_oauth_status.py
git commit -m "feat: add local OAuth status page"
```

### Task 2: Connect the status page to OAuth Desktop authorization

**Files:**
- Modify: `src/katy404_youtube_agent/auth.py`
- Modify: `src/katy404_youtube_agent/cli.py`
- Modify: `tests/test_auth.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- `authorize_desktop(client_secrets_path, credential_store, *, on_authorization_started: Callable[[], None] | None = None) -> Credentials` validates the Desktop client first, initializes the existing `InstalledAppFlow`, then invokes the optional callback immediately before `run_local_server()` opens Google OAuth.
- `OAuthService(status_page_factory: Callable[[], LocalOAuthStatusPage] = LocalOAuthStatusPage)` creates the page lazily from `on_authorization_started`, updates the state to `waiting`, calls the existing OAuth flow, updates to `connected` only after `CredentialStore.save()` completes, updates to `stopped` on error, and calls `finish()` in `finally` if the page started.
- `CliApp._upload` continues to call `OAuthService.authorize()` only when `CredentialStore.load("owner")` returns `None`; stored credentials and refresh behavior remain unchanged.

- [x] **Step 1: Write failing OAuth lifecycle and CLI ordering tests**

In `tests/test_auth.py`, assert that `on_authorization_started` is called only after a valid Desktop installed-app client is parsed and is not called for malformed JSON. In `tests/test_cli.py`, use a recording status-page fake and mocked `authorize_desktop` to assert success calls `start → waiting → connected → finish`, while OAuth exceptions call `start → waiting → stopped → finish`. Also test that an existing credential skips OAuth; with `credentials.load("owner")` returning `None`, verify `authorize` happens before API construction/upload; when the status page opener returns `False` or raises, verify the OAuth callback/Google flow, API construction, and upload do not run; when Google consent is denied or Credential Manager save raises a secret-like exception, verify the page ends in `stopped`, API construction/upload do not run, and the exception body is absent from output; and when OAuth succeeds but the requested channel is absent, verify the upload stops and the newly stored credential remains available.

Implement `RecordingOAuthStatusPage` with `start()` setting a `started` flag, `set_state(state)` appending to `states`, and `finish()` setting a `finished` flag. Inject it through `OAuthService(status_page_factory=...)`; invoke `authorize_desktop` through the `auth.py` import path so the `on_authorization_started` callback starts the fake page.

```python
def test_oauth_service_reports_success_in_page_states(monkeypatch):
    page = RecordingOAuthStatusPage()
    credentials = object()
    monkeypatch.setattr(
        "katy404_youtube_agent.auth.authorize_desktop",
        lambda path, store, *, on_authorization_started: (
            on_authorization_started(), credentials
        )[1],
    )
    service = OAuthService(status_page_factory=lambda: page)

    result = service.authorize(Path("client.json"), object())

    assert result is credentials
    assert page.states == ["waiting", "connected"]
    assert page.finished is True
```

For the channel mismatch case, use the existing `CliHarness` fixture, make `credentials.load("owner")` return `None` for the first load, have the OAuth stub persist and return a credential object, and have `runner.upload` raise `ChannelResolutionError` for the unowned channel. Assert the command returns the existing pre-upload error code and the credential can still be loaded afterward. Task 3's runner test pins that channel resolution happens before video transport.

- [x] **Step 2: Run the auth/OAuthService tests and confirm they fail before implementation**

Run: `pytest tests/test_auth.py tests/test_cli.py -k "authorization_started or oauth_service_reports or oauth_service_marks_stopped or missing_credential_authorizes or oauth_page_open_failure or oauth_failure_stops or existing_credential_skips_oauth or channel_mismatch_after_authorization or rejects_old_upload_project" -q`
Expected: the new tests fail because the callback and status-page lifecycle do not exist.

- [x] **Step 3: Add the post-validation OAuth callback and OAuthService lifecycle**

Keep `_validate_desktop_client()` as the first operation in `authorize_desktop()`. Call `on_authorization_started()` only after that validation and flow construction, directly before `flow.run_local_server(port=0, access_type="offline", prompt="consent")`. In `OAuthService.authorize()`, create the status page only inside this callback; if `start()` fails, do not call Google OAuth. Set `connected` only after `authorize_desktop()` returns (credential storage has succeeded). On any exception after page startup, set `stopped`, re-raise, and call `finish()` from `finally`; never serialize credentials into page state.

- [x] **Step 4: Run focused OAuth tests**

Run: `pytest tests/test_auth.py tests/test_cli.py -k "authorization_started or oauth_service_reports or oauth_service_marks_stopped or missing_credential_authorizes or oauth_page_open_failure or oauth_failure_stops or existing_credential_skips_oauth or channel_mismatch_after_authorization or rejects_old_upload_project" -q`
Expected: all selected tests pass; the old project test confirms the page-start callback was not called.

- [x] **Step 5: Commit the OAuth integration**

```powershell
git add src/katy404_youtube_agent/auth.py src/katy404_youtube_agent/cli.py tests/test_auth.py tests/test_cli.py
git commit -m "feat: show local status during YouTube OAuth"
```

### Task 3: Pin upload ordering and document the first-login experience

**Files:**
- Modify: `tests/test_setup_docs.py`
- Modify: `tests/test_runner.py`
- Modify: `README.md`
- Modify: `docs/setup.md`
- Modify: `docs/operations.md`
- Modify: `docs/superpowers/specs/2026-09-26-local-oauth-login-page-design.md` (update approval status)

**Interfaces:**
- `CliApp._upload` keeps its existing order: validate the profile, load Credential Manager, authorize only when no credential exists, build API, verify the exact requested channel, then start the upload runner.
- User-facing docs explain that the local status page appears only for the missing-credential branch; Google still handles password/consent; credential storage remains Credential Manager; channel errors are reported by CLI; a failed/revoked authorization stops that upload invocation.

- [x] **Step 1: Write a failing documentation regression test**

Extend `test_setup_docs.py` with a test that asserts README/setup describe the local page, Google consent, and Credential Manager without claiming the page displays a token. Add a runner regression test that proves channel resolution failure after OAuth cannot call the video upload API; the CLI ordering/failure tests are in Task 2 because they pin the OAuth integration.

```python
def test_setup_docs_describe_local_status_page_for_missing_token():
    readme = Path("README.md").read_text(encoding="utf-8")
    setup = Path("docs/setup.md").read_text(encoding="utf-8")
    section = setup.split("### หน้าเข้าสู่ระบบในเครื่อง", 1)[1].split("## ", 1)[0]
    assert "Credential Manager" in setup
    assert "Google OAuth" in setup
    assert "status page" in readme.casefold()
    assert "ไม่แสดง access/refresh token" in section
```

Use the existing `runner`, `fake_api`, and `media_folder` fixtures for the channel regression:

```python
from katy404_youtube_agent.auth import ChannelResolutionError


def test_unknown_requested_channel_stops_before_video_upload(runner, fake_api, media_folder):
    with pytest.raises(ChannelResolutionError):
        runner.upload(media_folder, "@not-my-channel", limit=1, force_private=True)

    fake_api.list_owned_channels.assert_called_once_with()
    assert fake_api.begin_upload.call_count == 0
    assert fake_api.upload_chunk.call_count == 0
```

- [x] **Step 2: Run the documentation regression and confirm it fails before doc updates**

Run: `pytest tests/test_setup_docs.py -k "local_status_page" -q`
Expected: the new documentation assertion fails because the current docs do not describe the local status page.

Run: `pytest tests/test_runner.py -k "unknown_requested_channel" -q`
Expected: the channel regression passes against the existing runner, confirming the channel gate stops before video transport.

- [x] **Step 3: Update README, setup, and operations guidance**

Explain the first-upload flow in Thai: the local page opens only when no OAuth credential is stored; complete sign-in and consent on Google; the local page confirms only OAuth success/failure; the CLI then checks the requested channel; credential stays in Windows Credential Manager; canceling or mismatching the channel sends no video; dry-run remains offline. Do not add a page that accepts Google passwords or displays/downloads tokens. Update the spec status line to say the user approved the design in chat and this file is the implementation plan.

- [x] **Step 4: Run focused regression tests and the complete test suite**

Run: `pytest tests/test_cli.py tests/test_setup_docs.py tests/test_runner.py -q`
Expected: focused CLI, documentation, and channel gate tests pass.

Run: `pytest -q`
Expected: the full suite passes with all existing upload, pilot, channel, and retry gates intact.

- [x] **Step 5: Review whitespace and commit documentation/regressions**

Run: `git diff --check`
Expected: no whitespace errors.

```powershell
git add tests/test_setup_docs.py tests/test_runner.py README.md docs/setup.md docs/operations.md docs/superpowers/specs/2026-09-26-local-oauth-login-page-design.md
git commit -m "docs: explain automatic YouTube OAuth login"
```
