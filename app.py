"""
Attendance Sync - copies P/A from a Google Sheet to the CULMS attendance register.

    AttendanceSync.exe          open the setup window
    AttendanceSync.exe --run    scheduled run (no window; shows a summary popup)
"""

from __future__ import annotations

import ctypes
import datetime as dt
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import engine
import settings
from culms import Culms, LoginError
from sheets import GoogleSheets, gid_from_url, sheet_id_from_url

TASK_NAME = "AttendanceSync"
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


# ---------------------------------------------------------------- scheduling
def exe_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --run'
    return f'"{sys.executable}" "{__file__}" --run'


def schedule_task(time_hhmm: str, days: list):
    subprocess.run(["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "WEEKLY",
                    "/D", ",".join(days), "/ST", time_hhmm, "/TR", exe_command()],
                   check=True, capture_output=True, text=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def unschedule_task():
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], capture_output=True, text=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def task_exists() -> bool:
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode == 0


# ---------------------------------------------------------------- scheduled run
def popup(title: str, text: str, error=False):
    try:
        ctypes.windll.user32.MessageBoxW(0, text[:1800], title, 0x40000 | (0x10 if error else 0x40))
    except Exception:
        print(title, text)


def scheduled_run():
    lines = [f"=== Scheduled run {dt.datetime.now():%Y-%m-%d %H:%M} ==="]
    log = lambda m: lines.append(m)
    try:
        res = engine.run(settings.load_config(), apply=True, headless=True, log=log)
        lines.append(res.summary)
        if res.failed:
            msg = "Some lectures could not be saved:\n" + "\n".join(f"- {n}: {r}" for n, r in res.failed)
            msg += "\n\nOpen Attendance Sync and click 'Sync now' to retry."
            popup("Attendance Sync - needs attention", msg, error=True)
        elif res.marked:
            popup("Attendance Sync - done", "Marked and verified:\n" +
                  "\n".join(f"- {n}: {c} student(s)" for n, c in res.marked) + "\n\n" + res.summary)
        # nothing new -> stay quiet
    except LoginError as e:
        lines.append(str(e))
        popup("Attendance Sync - CULMS sign-in failed",
              f"{e}\n\nOpen Attendance Sync, update your CULMS password and click 'Sync now'.", error=True)
    except Exception as e:
        lines.append(f"ERROR: {e}")
        popup("Attendance Sync - error", f"{e}\n\nOpen Attendance Sync to check the setup.", error=True)
    finally:
        engine.write_log(lines)


# ---------------------------------------------------------------- window
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Attendance Sync - Google Sheet to CULMS")
        self.geometry("760x760")
        self.minsize(680, 640)
        self.cfg = settings.load_config()
        self.q = queue.Queue()
        self.busy = False
        self.gs = GoogleSheets(settings.resource_path("client_secret.json"), str(settings.TOKEN_FILE))
        self.courses = []
        self.registers = []
        self.tabs = []
        self._build()
        self.after(100, self._drain)

    # ---------- layout
    def _build(self):
        pad = {"padx": 10, "pady": 4}
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        r = 0

        def section(text):
            nonlocal r
            ttk.Label(root, text=text, font=("Segoe UI", 11, "bold")).grid(row=r, column=0, columnspan=3, sticky="w", pady=(12, 2))
            r += 1

        section("1. CULMS login")
        ttk.Label(root, text="Portal address").grid(row=r, column=0, sticky="w", **pad)
        self.base_var = tk.StringVar(value=self.cfg.get("base_url", settings.DEFAULT_BASE))
        ttk.Entry(root, textvariable=self.base_var).grid(row=r, column=1, columnspan=2, sticky="ew", **pad); r += 1
        ttk.Label(root, text="Username").grid(row=r, column=0, sticky="w", **pad)
        self.user_var = tk.StringVar(value=self.cfg.get("username", ""))
        ttk.Entry(root, textvariable=self.user_var).grid(row=r, column=1, columnspan=2, sticky="ew", **pad); r += 1
        ttk.Label(root, text="Password").grid(row=r, column=0, sticky="w", **pad)
        self.pw_var = tk.StringVar(value="********" if settings.get_password(self.cfg.get("username")) else "")
        ttk.Entry(root, textvariable=self.pw_var, show="*").grid(row=r, column=1, sticky="ew", **pad)
        ttk.Button(root, text="Save & sign in", command=self.on_login).grid(row=r, column=2, sticky="ew", **pad); r += 1
        ttk.Label(root, text="The password is kept in Windows Credential Manager on this PC only.",
                  foreground="#666").grid(row=r, column=1, columnspan=2, sticky="w", padx=10); r += 1

        section("2. Course and attendance register")
        ttk.Label(root, text="Course").grid(row=r, column=0, sticky="w", **pad)
        self.course_cb = ttk.Combobox(root, state="readonly")
        self.course_cb.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
        self.course_cb.bind("<<ComboboxSelected>>", lambda e: self.on_course())
        if self.cfg.get("course_name"):
            self.course_cb.set(self.cfg["course_name"])
        r += 1
        ttk.Label(root, text="Register").grid(row=r, column=0, sticky="w", **pad)
        self.reg_cb = ttk.Combobox(root, state="readonly")
        self.reg_cb.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
        self.reg_cb.bind("<<ComboboxSelected>>", lambda e: self.on_register())
        if self.cfg.get("register_name"):
            self.reg_cb.set(self.cfg["register_name"])
        r += 1

        section("3. Google Sheet")
        self.g_status = tk.StringVar(value="Signed in to Google" if self.gs.signed_in() else "Not signed in")
        ttk.Label(root, textvariable=self.g_status).grid(row=r, column=0, columnspan=2, sticky="w", **pad)
        ttk.Button(root, text="Sign in with Google", command=self.on_google).grid(row=r, column=2, sticky="ew", **pad); r += 1
        ttk.Label(root, text="Sheet link").grid(row=r, column=0, sticky="w", **pad)
        self.url_var = tk.StringVar(value=self.cfg.get("sheet_url", ""))
        ttk.Entry(root, textvariable=self.url_var).grid(row=r, column=1, sticky="ew", **pad)
        ttk.Button(root, text="Load tabs", command=self.on_tabs).grid(row=r, column=2, sticky="ew", **pad); r += 1
        ttk.Label(root, text="Tab").grid(row=r, column=0, sticky="w", **pad)
        self.tab_cb = ttk.Combobox(root, state="readonly")
        self.tab_cb.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
        self.tab_cb.bind("<<ComboboxSelected>>", lambda e: self._save_sheet())
        if self.cfg.get("tab"):
            self.tab_cb.set(self.cfg["tab"])
        r += 1

        section("4. Sync")
        bar = ttk.Frame(root)
        bar.grid(row=r, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Button(bar, text="Preview (no changes)", command=lambda: self.on_sync(False)).pack(side="left")
        ttk.Button(bar, text="Sync now", command=lambda: self.on_sync(True)).pack(side="left", padx=8)
        self.show_browser = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show browser while syncing", variable=self.show_browser).pack(side="left", padx=8)
        r += 1

        sched = ttk.Frame(root)
        sched.grid(row=r, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(sched, text="Daily run at").pack(side="left")
        self.time_var = tk.StringVar(value=self.cfg.get("schedule_time", "17:00"))
        ttk.Entry(sched, textvariable=self.time_var, width=6).pack(side="left", padx=4)
        self.day_vars = {}
        saved_days = self.cfg.get("schedule_days", DAYS[:6])
        for d in DAYS:
            v = tk.BooleanVar(value=d in saved_days)
            self.day_vars[d] = v
            ttk.Checkbutton(sched, text=d.title(), variable=v).pack(side="left")
        r += 1
        sched2 = ttk.Frame(root)
        sched2.grid(row=r, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Button(sched2, text="Turn on daily run", command=self.on_schedule).pack(side="left")
        ttk.Button(sched2, text="Turn off", command=self.on_unschedule).pack(side="left", padx=8)
        self.sched_status = tk.StringVar(value="Daily run: ON" if task_exists() else "Daily run: off")
        ttk.Label(sched2, textvariable=self.sched_status).pack(side="left", padx=8)
        ttk.Button(sched2, text="Open logs", command=lambda: subprocess.Popen(["explorer", str(settings.LOG_DIR)])).pack(side="right")
        r += 1

        self.out = tk.Text(root, height=14, wrap="word", font=("Consolas", 9))
        self.out.grid(row=r, column=0, columnspan=3, sticky="nsew", **pad)
        root.rowconfigure(r, weight=1)

    # ---------- helpers
    def say(self, msg):
        self.q.put(("log", msg))

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.out.insert("end", payload + "\n")
                    self.out.see("end")
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def ui(self, fn):
        self.q.put(("call", fn))

    def work(self, fn):
        if self.busy:
            messagebox.showinfo("Busy", "Please wait for the current step to finish.")
            return
        self.busy = True

        def wrapper():
            try:
                fn()
            except Exception as e:
                self.say(f"ERROR: {e}")
                self.ui(lambda: messagebox.showerror("Attendance Sync", str(e)))
            finally:
                self.busy = False
        threading.Thread(target=wrapper, daemon=True).start()

    def _save(self):
        settings.save_config(self.cfg)

    # ---------- step 1
    def on_login(self):
        user = self.user_var.get().strip()
        pw = self.pw_var.get()
        if not user:
            messagebox.showwarning("Attendance Sync", "Enter your CULMS username.")
            return
        if pw and pw != "********":
            settings.save_password(user, pw)
            self.pw_var.set("********")
        self.cfg.update(base_url=self.base_var.get().strip().rstrip("/"), username=user)
        self._save()

        def job():
            self.say("Opening CULMS...")
            with Culms(self.cfg["base_url"], str(settings.PROFILE_DIR), headless=not self.show_browser.get(), log=self.say) as p:
                p.login(user, settings.get_password(user))
                self.say("Signed in. Loading your courses...")
                self.courses = p.courses()
            self.say(f"Found {len(self.courses)} course(s). Pick yours in step 2.")
            self.ui(lambda: self.course_cb.configure(values=[f"{n}  [{c}]" for _, n, c in self.courses]))
        self.work(job)

    # ---------- step 2
    def on_course(self):
        i = self.course_cb.current()
        if i < 0:
            return
        ou, name, code = self.courses[i]
        self.cfg.update(course_ou=ou, course_name=f"{name}  [{code}]", register_id="", register_name="")
        self._save()
        self.reg_cb.set("")

        def job():
            with Culms(self.cfg["base_url"], str(settings.PROFILE_DIR), headless=True, log=self.say) as p:
                p.login(self.cfg["username"], settings.get_password(self.cfg["username"]))
                self.registers = p.registers(ou)
            if not self.registers:
                self.say("This course has no attendance register.")
                return
            self.ui(lambda: self.reg_cb.configure(values=[n for _, n in self.registers]))
            if len(self.registers) == 1:
                self.ui(lambda: (self.reg_cb.current(0), self.on_register()))
            self.say(f"Found {len(self.registers)} register(s).")
        self.work(job)

    def on_register(self):
        i = self.reg_cb.current()
        if i < 0:
            return
        rid, name = self.registers[i]
        self.cfg.update(register_id=rid, register_name=name)
        self._save()
        self.say(f"Register selected: {name}")

    # ---------- step 3
    def on_google(self):
        def job():
            self.say("Opening Google sign-in in your browser...")
            self.gs.sign_in()
            self.ui(lambda: self.g_status.set("Signed in to Google"))
            self.say("Signed in to Google.")
        self.work(job)

    def on_tabs(self):
        url = self.url_var.get().strip()

        def job():
            sid = sheet_id_from_url(url)
            self.tabs = self.gs.tabs(sid)
            gid = gid_from_url(url)
            self.cfg.update(sheet_url=url, sheet_id=sid)
            self._save()

            def show():
                self.tab_cb.configure(values=[t for _, t in self.tabs])
                pick = next((i for i, (g, _) in enumerate(self.tabs) if g == gid), 0 if len(self.tabs) == 1 else -1)
                if pick >= 0:
                    self.tab_cb.current(pick)
                    self._save_sheet()
            self.ui(show)
            self.say(f"Sheet has {len(self.tabs)} tab(s).")
        self.work(job)

    def _save_sheet(self):
        if self.tab_cb.get():
            self.cfg["tab"] = self.tab_cb.get()
            self._save()
            self.say(f"Tab selected: {self.cfg['tab']}")

    # ---------- step 4
    def on_sync(self, apply: bool):
        def job():
            self.say(f"--- {'Sync' if apply else 'Preview'} {dt.datetime.now():%H:%M} ---")
            res = engine.run(self.cfg, apply=False, headless=not self.show_browser.get(), log=self.say)
            self.say(res.summary)
            if not apply or "Nothing to mark" in res.summary:
                return
            ev = threading.Event()
            answer = {}

            def ask():
                answer["ok"] = messagebox.askyesno("Confirm", res.summary + "\n\nMark these on CULMS now?")
                ev.set()
            self.ui(ask)
            ev.wait()
            if not answer.get("ok"):
                self.say("Cancelled - nothing changed.")
                return
            lines = [f"=== Manual sync {dt.datetime.now():%Y-%m-%d %H:%M} ==="]

            def both(m):
                lines.append(m)
                self.say(m)
            res2 = engine.run(self.cfg, apply=True, headless=not self.show_browser.get(), log=both)
            engine.write_log(lines + [res2.summary])
            if res2.failed:
                self.ui(lambda: messagebox.showerror("Attendance Sync", "Some lectures were not saved:\n" +
                                                     "\n".join(f"- {n}: {r}" for n, r in res2.failed)))
            else:
                self.ui(lambda: messagebox.showinfo("Attendance Sync", "Done - every change was saved and verified."))
        self.work(job)

    def on_schedule(self):
        days = [d for d, v in self.day_vars.items() if v.get()]
        t = self.time_var.get().strip()
        try:
            dt.datetime.strptime(t, "%H:%M")
        except ValueError:
            messagebox.showwarning("Attendance Sync", "Time must be like 17:00 (24-hour).")
            return
        if not days:
            messagebox.showwarning("Attendance Sync", "Pick at least one day.")
            return
        try:
            engine.check_ready(self.cfg)
            schedule_task(t, days)
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Attendance Sync", f"Could not create the Windows scheduled task:\n{e.stderr}")
            return
        except Exception as e:
            messagebox.showerror("Attendance Sync", str(e))
            return
        self.cfg.update(schedule_time=t, schedule_days=days)
        self._save()
        self.sched_status.set("Daily run: ON")
        self.say(f"Daily run turned on: {t} on {', '.join(days)}. The PC must be on and you must be signed in to Windows.")

    def on_unschedule(self):
        unschedule_task()
        self.sched_status.set("Daily run: off")
        self.say("Daily run turned off.")


def main():
    if "--run" in sys.argv:
        scheduled_run()
    else:
        App().mainloop()


if __name__ == "__main__":
    main()
