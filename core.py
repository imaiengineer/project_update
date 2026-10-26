"""
Pure logic: read the attendance sheet layout and work out what must change on
the portal. No network, no browser - so it can be tested anywhere.

Mapping rule (same as the manual setup):
    the k-th lecture column in the sheet (left to right) = the k-th attendance
    session in the CULMS register (Lecture 1, Lecture 2, ...). Two lectures on
    the same day are simply two columns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

STATUS_MAP = {"P": "P", "PRESENT": "P", "A": "A", "ABSENT": "A"}
DATE_RE = re.compile(r"^\s*\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}\s*$")
LECTURE_RE = re.compile(r"^\s*(lec|lecture|session|class)\b", re.I)
PORTAL_BLANK = "-"
# Portal statuses we never overwrite (e.g. ML = medical leave set by the office).
PROTECTED_PORTAL = {"ML"}


def col_letter(idx: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm_name(text) -> str:
    return clean(text).upper()


@dataclass
class Student:
    roll: str          # digits only, "" if the sheet has none
    name: str
    statuses: list     # per lecture column: "P", "A" or None (blank / unknown)
    row_number: int    # 1-based sheet row, for messages


@dataclass
class SheetData:
    lecture_cols: list          # [(column letter, header text)]
    students: list              # [Student]
    header_row: int             # 1-based


def parse_sheet(rows: list) -> SheetData:
    """rows = list of lists of cell values, as returned by the Sheets API."""
    header_idx = None
    for i, row in enumerate(rows[:15]):
        if any(re.search(r"\broll\b", clean(c), re.I) for c in row):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Could not find a header row with a 'Roll No' column in the first 15 rows.")

    header = [clean(c) for c in rows[header_idx]]
    roll_idx = next(i for i, h in enumerate(header) if re.search(r"\broll\b", h, re.I))
    name_idx = next((i for i, h in enumerate(header) if re.search(r"student\s*name", h, re.I)), None)
    if name_idx is None:
        name_idx = next((i for i, h in enumerate(header)
                         if re.search(r"\bname\b", h, re.I) and not re.search(r"class|course", h, re.I)), None)
    if name_idx is None:
        raise ValueError("Could not find a 'Student Name' column in the header row.")

    first_data_col = max(roll_idx, name_idx) + 1
    lecture_idx = [i for i in range(first_data_col, len(header))
                   if DATE_RE.match(header[i]) or LECTURE_RE.match(header[i])]
    if not lecture_idx:
        raise ValueError("No lecture columns found. Lecture column headers should be dates like 10/7/2026.")

    students = []
    for r, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        cell = lambda i: row[i] if i < len(row) else ""
        roll = re.sub(r"\D", "", clean(cell(roll_idx)))
        name = clean(cell(name_idx))
        if not roll and not name:
            continue
        statuses = [STATUS_MAP.get(clean(cell(i)).upper()) for i in lecture_idx]
        students.append(Student(roll=roll, name=name, statuses=statuses, row_number=r))

    return SheetData(
        lecture_cols=[(col_letter(i), header[i]) for i in lecture_idx],
        students=students,
        header_row=header_idx + 1,
    )


@dataclass
class PortalGrid:
    sessions: list   # [(session name, edit url)] in register order
    learners: dict   # roll -> {"name": str, "cells": [status per session, "-" if blank]}


@dataclass
class Plan:
    changes: dict = field(default_factory=dict)        # session index -> {roll: "P"/"A"}
    not_on_portal: list = field(default_factory=list)  # [(roll, name)]
    name_matched: list = field(default_factory=list)   # [(sheet name, portal roll)]
    incomplete: list = field(default_factory=list)     # [(col letter, header, blanks)]
    no_session: list = field(default_factory=list)     # [(col letter, header)]
    protected: list = field(default_factory=list)      # [(session name, roll, portal value, sheet value)]

    def total_changes(self) -> int:
        return sum(len(v) for v in self.changes.values())


def make_plan(sheet: SheetData, portal: PortalGrid) -> Plan:
    plan = Plan()

    # Match sheet students to portal learners: by roll number, or by exact name
    # for sheet rows that have no roll number.
    by_name = {norm_name(v["name"]): roll for roll, v in portal.learners.items()}
    matched = []   # (Student, portal roll)
    for st in sheet.students:
        if st.roll and st.roll in portal.learners:
            matched.append((st, st.roll))
        elif not st.roll and norm_name(st.name) in by_name:
            roll = by_name[norm_name(st.name)]
            matched.append((st, roll))
            plan.name_matched.append((st.name, roll))
        else:
            plan.not_on_portal.append((st.roll, st.name))

    for k, (letter, head) in enumerate(sheet.lecture_cols):
        if k >= len(portal.sessions):
            if any(st.statuses[k] for st, _ in matched):
                plan.no_session.append((letter, head))
            continue

        session_name = portal.sessions[k][0]
        sheet_vals = {roll: st.statuses[k] for st, roll in matched}
        portal_vals = {roll: portal.learners[roll]["cells"][k] for _, roll in matched}
        blanks = sum(1 for v in sheet_vals.values() if v is None)
        session_empty = all(v == PORTAL_BLANK for v in portal_vals.values())

        if blanks and session_empty:
            # A new lecture that is only partly filled in: wait until it is complete.
            if blanks < len(sheet_vals):
                plan.incomplete.append((letter, head, blanks))
            continue

        diff = {}
        for roll, want in sheet_vals.items():
            have = portal_vals[roll]
            if want is None or want == have:
                continue
            if have in PROTECTED_PORTAL:
                plan.protected.append((session_name, roll, have, want))
                continue
            diff[roll] = want
        if diff:
            plan.changes[k] = diff
    return plan


def summarize(plan: Plan, sheet: SheetData, portal: PortalGrid) -> str:
    lines = []
    if plan.changes:
        lines.append("To mark on the portal:")
        for k, diff in sorted(plan.changes.items()):
            letter, head = sheet.lecture_cols[k]
            p = sum(1 for v in diff.values() if v == "P")
            lines.append(f"  - Column {letter} ({head}) -> {portal.sessions[k][0]}: "
                         f"{len(diff)} student(s) ({p} P, {len(diff) - p} A)")
    else:
        lines.append("Nothing to mark - the portal already matches the sheet.")
    if plan.incomplete:
        lines.append("Skipped, column not fully filled yet:")
        lines += [f"  - Column {l} ({h}): {b} blank" for l, h, b in plan.incomplete]
    if plan.no_session:
        lines.append("No matching portal session (register has too few sessions):")
        lines += [f"  - Column {l} ({h})" for l, h in plan.no_session]
    if plan.not_on_portal:
        lines.append("Not on the portal (cannot be marked):")
        lines += [f"  - {name} {('(' + roll + ')') if roll else '(no roll number)'}" for roll, name in plan.not_on_portal]
    if plan.name_matched:
        lines.append("Matched by name (no roll number in sheet):")
        lines += [f"  - {n} -> {r}" for n, r in plan.name_matched]
    if plan.protected:
        lines.append("Left unchanged (portal value is protected):")
        lines += [f"  - {s}, {r}: portal {h}, sheet {w}" for s, r, h, w in plan.protected]
    return "\n".join(lines)
