"""
The sync itself: sheet -> plan -> mark each session -> re-read portal and verify.
Used by both the window (Preview / Sync now) and the scheduled run (--run).
"""

from __future__ import annotations

import datetime as dt

import settings
from core import make_plan, parse_sheet, summarize
from culms import Culms, PortalError
from sheets import GoogleSheets


class SyncResult:
    def __init__(self):
        self.summary = ""
        self.marked = []     # [(session name, count)]
        self.failed = []     # [(session name, reason)]
        self.ok = True


def _sheet(cfg, log):
    gs = GoogleSheets(settings.resource_path("client_secret.json"), str(settings.TOKEN_FILE))
    log(f"Reading Google Sheet tab '{cfg['tab']}'...")
    rows = gs.values(cfg["sheet_id"], cfg["tab"])
    sheet = parse_sheet(rows)
    log(f"Sheet: {len(sheet.students)} students, {len(sheet.lecture_cols)} lecture columns "
        f"({sheet.lecture_cols[0][0]}..{sheet.lecture_cols[-1][0]}).")
    return sheet


def check_ready(cfg):
    missing = [k for k in ("username", "course_ou", "register_id", "sheet_id", "tab") if not cfg.get(k)]
    if missing:
        raise ValueError("Setup is not finished (missing: " + ", ".join(missing) + "). Open the app and complete it.")


def run(cfg: dict, apply: bool, headless: bool = True, log=print) -> SyncResult:
    check_ready(cfg)
    res = SyncResult()
    sheet = _sheet(cfg, log)
    pw = settings.get_password(cfg["username"])

    with Culms(cfg["base_url"], str(settings.PROFILE_DIR), headless=headless, log=log) as portal:
        portal.login(cfg["username"], pw)
        log("Reading the CULMS attendance register...")
        grid = portal.read_grid(cfg["course_ou"], cfg["register_id"])
        log(f"Portal: {len(grid.learners)} learners, {len(grid.sessions)} sessions.")
        plan = make_plan(sheet, grid)
        res.summary = summarize(plan, sheet, grid)
        if not apply or not plan.changes:
            return res

        n_learners = len(grid.learners)
        for k, diff in sorted(plan.changes.items()):
            name, url = grid.sessions[k]
            letter, head = sheet.lecture_cols[k]
            done = False
            for attempt in (1, 2):
                try:
                    log(f"{name} (column {letter}, {head}): setting {len(diff)} student(s)"
                        + (" - retry" if attempt == 2 else "") + "...")
                    portal.mark_session(name, url, diff, n_learners)
                    after = portal.read_grid(cfg["course_ou"], cfg["register_id"])
                    wrong = [r for r, v in diff.items() if after.learners.get(r, {}).get("cells", [None] * (k + 1))[k] != v]
                    if not wrong:
                        log(f"{name}: saved and verified.")
                        res.marked.append((name, len(diff)))
                        done = True
                        break
                    log(f"{name}: {len(wrong)} value(s) did not save.")
                except PortalError as e:
                    log(str(e))
                    res.failed.append((name, str(e)))
                    break
            if not done and not any(f[0] == name for f in res.failed):
                res.failed.append((name, "values did not save after 2 attempts"))
            if not done:
                res.ok = False
                log("Stopping here so nothing is marked out of order.")
                break
    return res


def write_log(lines: list):
    path = settings.LOG_DIR / f"sync-{dt.date.today():%Y-%m}.log"
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")
    return path
