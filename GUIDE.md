# Attendance Sync – Google Sheet to CULMS

A Windows app that copies P/A from a trainer's Google Sheet to the CULMS attendance register, checks every save, and can run by itself every day. It doesn't use Claude or any AI, so it costs nothing to run.

**How it maps lectures:** the 1st lecture column in the sheet goes to the 1st session in the register (Lecture 1), the 2nd column to Lecture 2, and so on. Two lectures on one day means two columns with the same date. Each run compares the sheet with the portal and only fills or fixes cells that differ, so running it twice is harmless and a missed day catches up.

**What it never does:** overwrite an ML (medical leave) set on the portal, mark a new lecture column that still has blank cells, or touch students who aren't in the sheet.

---

## Part A – One-time, for the person building the app (you)

### A1. Create the "Sign in with Google" client (about 10 min, free)

1. Go to <https://console.cloud.google.com> and sign in with your Gmail.
2. Click the project picker at the top → **New project** → name it `Attendance Sync` → **Create**, then select it.
3. Search for **Google Sheets API** → **Enable**.
4. Search for **Google Auth Platform** (it may be called **OAuth consent screen**) → **Get started**:
   - App name `Attendance Sync`, user support email = your email → **Next**
   - Audience: **External** → **Next**
   - Contact email = your email → agree → **Create**
5. Open **Audience** and click **Publish app** → **Confirm**.
   This matters: while the app is in "Testing", Google sign-ins expire every 7 days and the daily run would stop.
6. Open **Clients** → **Create client** → Application type **Desktop app** → name `Attendance Sync` → **Create** → **Download JSON**.
7. Rename the downloaded file to exactly `client_secret.json` and put it in the `AttendanceSync` folder, next to `build.bat`.

Because the app isn't verified by Google, trainers will see a **"Google hasn't verified this app"** screen the first time they sign in. They click **Advanced** → **Go to Attendance Sync (unsafe)** → **Continue**. The app asks only for **read-only** access to their sheets. Unverified apps are limited to 100 users, which is plenty for your trainers.

### A2. Build the .exe (about 10 min, once)

1. Install Python from <https://www.python.org/downloads/> and tick **Add python.exe to PATH**. Skip this if you already have it.
2. Double-click **build.bat**. It installs what it needs and builds the app.
3. When it finishes, a folder opens with **dist\AttendanceSync.exe**. That single file is what you share. It already contains `client_secret.json`.

Windows SmartScreen may warn the first time someone runs it, because the .exe isn't code-signed. Click **More info** → **Run anyway**.

---

## Part B – For each trainer (about 5 min)

**Needs:** a Windows PC with Microsoft Edge (installed on every Windows PC), their CULMS login, and an attendance sheet in this layout:

| … | Roll No | … | Student Name | … | 10/7/2026 | 10/8/2026 | 10/8/2026 | … |
|---|---|---|---|---|---|---|---|---|
| | 2620992738 | | PALAK | | P | A | A | |

- The header row must contain a **Roll No** column and a **Student Name** column.
- Each lecture is one column with a **date header**, to the right of those columns. Add one column per lecture, always on the right.
- Each cell is **P** or **A**.

**Setup:**

1. Put `AttendanceSync.exe` anywhere, for example in Documents, and open it.
2. **Step 1 – CULMS login:** enter your username and password → **Save & sign in**. Your courses load.
3. **Step 2:** pick your **course**. The register is picked automatically if there's only one.
4. **Step 3:** click **Sign in with Google** (see the warning note in A1), paste your **sheet link** → **Load tabs** → pick the tab.
5. **Step 4:** click **Preview (no changes)**. Read the summary: which columns go to which lecture, and which students aren't on the portal.
6. Click **Sync now** → **Yes**. Every lecture is saved and then checked. Open CULMS once and spot-check a few students.
7. Choose the time and days → **Turn on daily run**.

**Every day after that:** fill in your sheet. At the chosen time, the PC must be **on and signed in to Windows**. A locked screen is fine; sleep or shutdown is not. A popup reports what was marked. If nothing was new, it stays quiet.

---

## Troubleshooting

| What you see | What to do |
|---|---|
| "CULMS sign-in failed" popup | Your password changed. Open the app, type the new password in Step 1 → **Save & sign in**. |
| "Not signed in to Google" | Open the app → **Sign in with Google** again. If this happens every week, the Google app is still in Testing (see A1 step 5). |
| A column is "not fully filled yet" | Fill every student's P/A in that column. The next run picks it up. |
| Students "Not on the portal" | They aren't enrolled in the CULMS course. Ask the coordinator to add them; the next run fills all their past lectures. |
| "Opened the wrong page" / "expected N learners" | The app stopped **before** saving anything. Click **Sync now** again; if it repeats, the portal layout may have changed. |
| Want to see what happened | **Open logs** in the app (`%APPDATA%\AttendanceSync\logs`). |
| Stop the daily run | **Turn off** in the app. |

**Privacy:** the CULMS password is stored only in Windows Credential Manager on that PC. The Google sign-in token and settings are in `%APPDATA%\AttendanceSync`. Each trainer's data stays on their own PC. Confirm with the university that automated marking on CULMS is allowed.
