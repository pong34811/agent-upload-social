"""OAuth and API construction behind one seam so commands run offline in tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..auth import OWNER_ACCOUNT_KEY, CredentialStore, oauth
from ..auth.status_page import LocalOAuthStatusPage
from ..jobs.store import JobStore
from ..youtube.client import YouTubeApi


class OAuthService:
    """Indirection point so command behavior can be exercised without OAuth/network access."""

    def __init__(
        self,
        status_page_factory: Callable[[], LocalOAuthStatusPage] = LocalOAuthStatusPage,
    ) -> None:
        self._status_page_factory = status_page_factory

    def authorize(
        self,
        client_secrets_path: Path,
        credential_store: CredentialStore,
        account_key: str = OWNER_ACCOUNT_KEY,
    ) -> Any:
        status_page: LocalOAuthStatusPage | None = None
        page_started = False

        def start_status_page() -> None:
            nonlocal status_page, page_started
            status_page = self._status_page_factory()
            status_page.start()
            page_started = True
            status_page.set_state("waiting")

        try:
            credentials = oauth.authorize_desktop(
                client_secrets_path,
                credential_store,
                account_key=account_key,
                on_authorization_started=start_status_page,
            )
            if page_started and status_page is not None:
                status_page.set_state("connected")
            return credentials
        except KeyboardInterrupt:
            if page_started and status_page is not None:
                status_page.set_state("stopped")
            raise
        except Exception:
            if page_started and status_page is not None:
                status_page.set_state("stopped")
            raise
        finally:
            if page_started and status_page is not None:
                status_page.finish()

    def refresh(self, account_key: str, credential_store: CredentialStore, credentials: Any) -> Any:
        return oauth.refresh_credentials(account_key, credential_store, credentials)

    def build_api(self, credentials: Any, store: JobStore) -> Any:
        return YouTubeApi(credentials, store=store)
