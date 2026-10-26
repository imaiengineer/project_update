"""
CULMS (D2L Brightspace) automation with Playwright, driving Microsoft Edge
(already installed on every Windows PC, so no browser download is needed).

Page facts this relies on (checked on culms.chitkara.edu.in, Oct 2026):
- Login form: #userName, #password, button "Log In".
- Register list:   /d2l/lms/attendance/registers/registers_list.d2l?ou=<course>
- Attendance grid: /d2l/lms/attendance/attendance/data_list.d2l?registerId=<id>&ou=<course>
  rows "<roll>, <NAME>" then one cell per session ("-" when blank, else P/A/ML),
  and links titled "Enter attendance data for <session name>" -> data_edit.d2l?SessionId=...
- Edit page: one <select name="SL_Status_<id>"> per learner (None/P/A/ML), a
  "Results Per Page" select (default 20 - we switch to 200) and a "Save" button.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from core import PortalGrid


class LoginError(Exception):
    pass


class PortalError(Exception):
    pass


GRID_JS = r"""
() => {
  const sessions = [...document.querySelectorAll('a[href*="data_edit.d2l"]')].map(a => {
    const t = (a.getAttribute('title') || a.getAttribute('aria-label') || a.textContent || '').trim();
    return [t.replace(/^Enter attendance data for\s*/i, '').trim(), a.href];
  });
  const learners = {};
  for (const tr of document.querySelectorAll('tr')) {
    const cells = [...tr.querySelectorAll('th,td')].map(c => c.textContent.replace(/\s+/g, ' ').trim());
    const i = cells.findIndex(x => /^\d{5,},/.test(x));
    if (i < 0) continue;
    const m = cells[i].match(/^(\d{5,}),\s*(.*)$/);
    learners[m[1]] = { name: m[2], cells: cells.slice(i + 1, i + 1 + sessions.length) };
  }
  return { sessions, learners };
}
"""

FILL_JS = r"""
(changes) => {
  const sels = [...document.querySelectorAll('select[name^="SL_Status_"]')];
  const seen = new Set(); const problems = [];
  for (const s of sels) {
    const m = (s.closest('tr')?.innerText || '').match(/(\d{5,})/);
    if (!m) continue;
    const roll = m[1]; seen.add(roll);
    const want = changes[roll];
    if (!want) continue;
    const opt = [...s.options].find(o => o.text.trim() === want);
    if (!opt) { problems.push(roll + ': no option ' + want); continue; }
    s.value = opt.value;
    s.dispatchEvent(new Event('change', { bubbles: true }));
  }
  const missing = Object.keys(changes).filter(r => !seen.has(r));
  return { total: sels.length, missing, problems };
}
"""


class Culms:
    def __init__(self, base_url: str, profile_dir: str, headless: bool = True, log=print):
        self.base = base_url.rstrip("/")
        self.profile_dir = profile_dir
        self.headless = headless
        self.log = log
        self._pw = self._ctx = self.page = None

    # ------------------------------------------------------------ lifecycle
    def __enter__(self):
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            self.profile_dir, channel="msedge", headless=self.headless,
            viewport={"width": 1366, "height": 900})
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self.page.set_default_timeout(45000)
        return self

    def __exit__(self, *exc):
        try:
            self._ctx.close()
        finally:
            self._pw.stop()

    def _goto(self, path: str):
        self.page.goto(urljoin(self.base + "/", path.lstrip("/")), wait_until="domcontentloaded")
        self.page.wait_for_load_state("networkidle")
        if "/d2l/login" in self.page.url:
            raise LoginError("Signed out of CULMS")

    # ------------------------------------------------------------ login
    def login(self, username: str, password: str):
        self.page.goto(self.base + "/d2l/home", wait_until="domcontentloaded")
        self.page.wait_for_load_state("networkidle")
        if "/d2l/login" not in self.page.url:
            return  # session still valid
        if not username or not password:
            raise LoginError("CULMS username/password not saved")
        self.log("Signing in to CULMS...")
        self.page.locator("#userName").fill(username)
        self.page.locator("#password").fill(password)
        self.page.get_by_role("button", name="Log In").click()
        try:
            self.page.wait_for_url(lambda u: "/d2l/login" not in u, timeout=30000)
        except Exception:
            raise LoginError("CULMS login failed - check the username and password "
                             "(or the portal now asks for an extra verification step).")
        self.page.wait_for_load_state("networkidle")

    # ------------------------------------------------------------ discovery
    def courses(self) -> list:
        """[(ou id, name, code)] of the user's course offerings."""
        items, bookmark = [], ""
        while True:
            url = "/d2l/api/lp/1.30/enrollments/myenrollments/?orgUnitTypeId=3"
            if bookmark:
                url += "&bookmark=" + bookmark
            data = self.page.evaluate("u => fetch(u).then(r => r.json())", url)
            for it in data.get("Items", []):
                ou = it["OrgUnit"]
                items.append((str(ou["Id"]), ou["Name"], ou.get("Code") or ""))
            paging = data.get("PagingInfo") or {}
            if not paging.get("HasMoreItems"):
                break
            bookmark = paging.get("Bookmark", "")
        return items

    def registers(self, ou: str) -> list:
        """[(register id, name)] for a course."""
        self._goto(f"/d2l/lms/attendance/registers/registers_list.d2l?ou={ou}")
        regs = self.page.evaluate(r"""() => [...document.querySelectorAll('a[href*="data_list.d2l?registerId="]')]
            .map(a => [ (a.href.match(/registerId=(\d+)/)||[])[1],
                        (a.getAttribute('title')||a.textContent||'').replace(/^View attendance data in\s*/i,'').trim() ])""")
        out, seen = [], set()
        for rid, name in regs:
            if rid and rid not in seen:
                seen.add(rid)
                out.append((rid, name))
        return out

    # ------------------------------------------------------------ grid
    def _show_all(self):
        """Switch the 'Results Per Page' list to 200 so every learner is on one page."""
        sel = self.page.locator("select:has(option:text-is('200 per page'))").first
        if sel.count() == 0:
            return
        current = sel.evaluate("s => s.options[s.selectedIndex].text.trim()")
        if current != "200 per page":
            sel.select_option(label="200 per page")
            self.page.wait_for_load_state("networkidle")
            time.sleep(1.5)

    def read_grid(self, ou: str, register_id: str) -> PortalGrid:
        self._goto(f"/d2l/lms/attendance/attendance/data_list.d2l?registerId={register_id}&ou={ou}")
        self._show_all()
        data = self.page.evaluate(GRID_JS)
        if not data["sessions"]:
            raise PortalError("No attendance sessions found in this register.")
        return PortalGrid(sessions=[tuple(s) for s in data["sessions"]], learners=data["learners"])

    # ------------------------------------------------------------ marking
    def mark_session(self, session_name: str, edit_url: str, changes: dict, expected_learners: int):
        """Set the given {roll: 'P'/'A'} on one session's edit page and click Save."""
        self.page.goto(edit_url, wait_until="domcontentloaded")
        self.page.wait_for_load_state("networkidle")
        if "/d2l/login" in self.page.url:
            raise LoginError("Signed out of CULMS")
        self._show_all()

        body = self.page.inner_text("body")
        if not re.search(re.escape(session_name) + r"(?!\d)", body):
            raise PortalError(f"Opened the wrong page for {session_name} - stopped before changing anything.")

        res = self.page.evaluate(FILL_JS, changes)
        if res["total"] != expected_learners:
            raise PortalError(f"{session_name}: page shows {res['total']} learners, expected "
                              f"{expected_learners} - stopped before saving.")
        if res["missing"] or res["problems"]:
            raise PortalError(f"{session_name}: could not set {res['missing'] + res['problems']} - not saved.")

        self.page.get_by_role("button", name="Save", exact=True).click()
        self.page.wait_for_load_state("networkidle")
        time.sleep(2)
