# OAuth Loopback Callback IPv4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make Google OAuth Desktop callbacks reach the local server when Windows resolves localhost to IPv6 before IPv4.

**Architecture:** Keep the existing InstalledAppFlow.run_local_server flow and ephemeral port. Pass host=127.0.0.1 so the redirect URI and listener use the IPv4 loopback address together; keep scopes, account prompts, credential storage, and timeout unchanged.

**Tech Stack:** Python, google-auth-oauthlib, pytest.

**Spec:** Approved in-chat bounded design on 2026-09-29 (no standalone spec, following the bounded brainstorming path).

## Global Constraints

- Keep OAuth callbacks loopback-only and use 127.0.0.1 for the redirect host.
- Keep the ephemeral port (port=0), current OAuth scopes, offline access, account-specific prompt, and 600-second timeout.
- Do not print or log OAuth tokens, client secrets, resumable session URLs, or API response bodies.
- Store named credentials under the same account-specific token filename.

## Review Focus

The relevant inputs are covered: the owner-flow test verifies its consent prompt and callback parameters; the named-account test verifies the armigon prompt, callback parameters, and per-account save. The implementation changes only the redirect/listener host; scope selection, offline access, and timeout handling stay at their existing call sites.

---

### Task 1: Bind OAuth callback to IPv4 loopback

**Files:**
- Modify: src/katy404_youtube_agent/auth.py:393-398
- Test: tests/test_auth.py

**Interfaces:**
- Consumes: authorize_desktop(client_secrets_path, credential_store, *, account_key="owner", on_authorization_started=None) -> Credentials
- Produces: the same public function signature; run_local_server receives host=127.0.0.1 while preserving the current port, scopes, prompt, and timeout behavior.

- [x] **Step 1: Write the failing regression test**
  - Update both existing run_local_server.assert_called_once_with expectations to include host=127.0.0.1.
  - Add test_authorize_named_account_uses_ipv4_loopback_callback. Run authorize_desktop(..., account_key="armigon"); assert run_local_server receives host=127.0.0.1, port=0, access_type=offline, prompt=select_account consent, and timeout_seconds=600; assert the credential is saved under armigon.

- [x] **Step 2: Run the regression test and verify it fails for the missing host**

  Run: .\.venv\Scripts\python.exe -m pytest tests/test_auth.py::test_authorize_named_account_uses_ipv4_loopback_callback -q
  Expected: FAIL because the current run_local_server call omits host=127.0.0.1.

- [x] **Step 3: Pass the IPv4 loopback host**
  - In authorize_desktop, add host=127.0.0.1 to the run_local_server call. Leave the port, scopes, prompts, timeout, and credential storage unchanged.

- [x] **Step 4: Run focused OAuth tests**

  Run: .\.venv\Scripts\python.exe -m pytest tests/test_auth.py -q
  Expected: PASS with 0 failures.

- [x] **Step 5: Run the full test suite**

  Run: .\.venv\Scripts\python.exe -m pytest -q
  Expected: PASS with 0 failures.

- [x] **Step 6: Commit the task**

  Run: git add src/katy404_youtube_agent/auth.py tests/test_auth.py docs/superpowers/plans/2026-09-29-oauth-loopback-ipv4.md
  Then run: git commit -m "fix: bind OAuth callback to IPv4 loopback"
