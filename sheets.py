"""
Read a private Google Sheet with the trainer's own Google account
("Sign in with Google", read-only access).

Needs a Google OAuth *Desktop app* client file, client_secret.json, placed
next to AttendanceSync.exe (or bundled into it by build.bat). See the guide.
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
API = "https://sheets.googleapis.com/v4/spreadsheets/"


def sheet_id_from_url(url: str) -> str:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url or "")
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{25,}", (url or "").strip()):
        return url.strip()
    raise ValueError("That doesn't look like a Google Sheets link.")


def gid_from_url(url: str):
    m = re.search(r"[#&?]gid=(\d+)", url or "")
    return int(m.group(1)) if m else None


class GoogleSheets:
    def __init__(self, client_secret_path: str, token_path: str):
        self.client_secret_path = client_secret_path
        self.token_path = token_path
        self.creds = None

    def signed_in(self) -> bool:
        return self._load() is not None

    def _load(self):
        if self.creds and self.creds.valid:
            return self.creds
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    return None
                self._save(creds)
            if creds.valid:
                self.creds = creds
                return creds
        return None

    def _save(self, creds):
        with open(self.token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    def sign_in(self):
        """Opens the browser for Google sign-in (interactive, first time only)."""
        if not os.path.exists(self.client_secret_path):
            raise FileNotFoundError("client_secret.json not found next to the app. See the setup guide.")
        flow = InstalledAppFlow.from_client_secrets_file(self.client_secret_path, SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent",
                                      success_message="Signed in. You can close this tab and go back to Attendance Sync.")
        self._save(creds)
        self.creds = creds

    def sign_out(self):
        self.creds = None
        if os.path.exists(self.token_path):
            os.remove(self.token_path)

    def _session(self) -> AuthorizedSession:
        creds = self._load()
        if creds is None:
            raise PermissionError("Not signed in to Google (or the sign-in expired). Open the app and click 'Sign in with Google'.")
        return AuthorizedSession(creds)

    def tabs(self, sheet_id: str) -> list:
        """[(sheetId gid, title)]"""
        r = self._session().get(API + sheet_id, params={"fields": "properties.title,sheets.properties(sheetId,title)"})
        if r.status_code == 404:
            raise ValueError("Sheet not found - check the link.")
        if r.status_code == 403:
            raise PermissionError("Your Google account can't open this sheet.")
        r.raise_for_status()
        return [(p["properties"]["sheetId"], p["properties"]["title"]) for p in r.json()["sheets"]]

    def values(self, sheet_id: str, tab: str) -> list:
        rng = quote(f"'{tab}'", safe="")
        r = self._session().get(API + sheet_id + "/values/" + rng,
                                params={"valueRenderOption": "FORMATTED_VALUE"})
        r.raise_for_status()
        return r.json().get("values", [])
