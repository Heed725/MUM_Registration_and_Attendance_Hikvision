# MUM Registration and Attendance

A green, logo-branded Streamlit application for the **Muslim University of Morogoro**, using **one Hikvision terminal**. The terminal address is intentionally unconfigured until its public IP or reachable host is available. This repository contains no real terminal credentials or administrator password.

## Registration

1. Sign in as an administrator; the app loads the terminal’s employee list.
2. Filter by department and type into the searchable employee-name dropdown.
3. Check the terminal employee number. Employees without a number in the source export require a unique number. Leading zeros are preserved.
4. Upload a JPEG face photograph. Stand beside the terminal and click **Capture fingerprint** for the selected finger slot.
5. Click **Save registration**. The app verifies the existing identity or creates the person, sends the photograph and fingerprint, and reads both back before reporting success.

Capture holds a template in the current administrator session until Save; it does not attach the fingerprint to a person by itself. Changing the selected employee clears the pending fingerprint. Saving successfully, signing out or session expiry clears the pending template. No photograph or fingerprint is written to a local file or committed to this repository. The session expires after 30 minutes without interaction. Close or sign out of unattended administrator sessions.

A save can partially succeed if the device disconnects between operations. The app reports incomplete registration and leaves the profile in place for a retry. It never deletes people or overwrites a number assigned to another name. If firmware does not permit photo/template read-back, successful enrollment cannot be confirmed automatically; use the terminal management interface to check the employee.

## Imported roster and existing registrations

The supplied employee-number and department exports are reconciled by exact employee name into **163 staff**, across **42 department labels**. Six source records have no employee number. Only employee names, employee numbers, department paths, and the screenshot’s existing-registration mapping are included. Avatar data, phone numbers and manager details are omitted.

All 163 people remain in attendance. The 15 people shown in the supplied terminal screenshot are excluded from registration, leaving 148 initial candidates. Other employees with both face and fingerprint credentials on the live terminal are also excluded after a refresh. Partially enrolled staff remain available to retry.

The screenshot and exports contain differences. These explicit mappings preserve the screenshot’s terminal numbers and display names; the app still checks live names before saving or matching events:

| Source employee | Export number | Screenshot terminal number | Screenshot display name |
| --- | --- | --- | --- |
| Prof. Yusuf Ismail Ally Koleleni | 255 | 37 | Yusuf Koleleni |
| Prof. Hamza Mustafa Njozi | 37 | 037 | Hamza Mustafa Njozi |
| Mossi Kalagila | 43 | 49 | Mossi Kalagila |
| Hussein Issa Chanzi | 215 | 215 | Hussein Chanzi |
| Dr.Hamis Salum Haji | 76 | 76 | Salum Haji Hamisi |
| Aeshi Jumanne | 54 | 54 | Aeshi J Kachemela |
| Khadija Shaban Juma | 284 | 284 | Hadija Shaban |

The other screenshot staff are likewise mapped in `data/employees.json`. Names and numbers should be reconciled with the physical terminal when connected. A number alone never establishes identity. `37` and `037` are distinct; the app will not merge them. An ambiguous or mismatched profile is reported instead of guessing. Full original department paths remain visible in the roster; reports group by the final department label. Unassigned departments have their own group.

## Attendance reports

Open **Attendance → Report options** to select:

- **Full attendance**: every roster employee, for each selected calendar date.
- **Early attendance**: arrivals strictly before the configured check-in time.
- **Checked in only**: everyone with an arrival, including employees with no checkout.
- **Absentees**: matched terminal employees with no successful attendance scan. Today’s absences remain provisional.

Default hours are **08:00–16:30**, using Tanzania time (`Africa/Dar_es_Salaam`, UTC+3). Hours can be changed for the report. Check-in is the first successful scan that day. Checkout is the first distinct subsequent scan at or after the configured checkout time; an earlier scan does not count as checkout. No checkout is invented for a single scan. Minutes late use whole elapsed minutes after the check-in threshold.

Select all departments or one department, and optionally include a department-by-department breakdown. **Download Reports** and **View Reports** use the same selected rows. Downloads include green headings and the MUM logo in **Excel, PDF and Word**.

Reports include every selected calendar date (including weekends); no university holiday or workweek calendar was supplied. Future dates and ranges beyond 93 days are rejected. Staff who are unenrolled or whose terminal identity cannot be matched are labelled **Not enrolled / unmatched**, rather than falsely counted as absent. A failed or incomplete device query produces no absence report. Unknown employee numbers or invalid event timestamps are flagged. Attendance events are restricted to successful card, fingerprint and face verification events (major 5; minor 1, 38 and 75); door alarms and rejected authentications do not count as arrivals.

## Run locally

Requires Python 3.12 or later.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python make_password.py
```

Copy `secrets.example.toml` to `.streamlit/secrets.toml`. Set your administrator username and the generated password hash. Add the reachable terminal address, username and password when ready. The real secrets file is ignored by Git. Environment variables with the same names are also supported.

```bash
streamlit run app.py
```

The application starts with configuration guidance while terminal settings are absent. It does not generate sample attendance or attempt to connect to a guessed address. There is no default administrator password.

TLS certificate verification is enabled by default. For a terminal with a self-signed certificate, install a trusted certificate or deliberately set `HIKVISION_VERIFY_TLS = false` only if required for your connection. Configure network access so the app host can reach the terminal’s ISAPI service. Do not publish device credentials in GitHub.

## Deploy to Streamlit Community Cloud

1. Create a Streamlit app from `Heed725/MUM_Registration_and_Attendance_Hikvision`, branch `main`, entrypoint **`app.py`**.
2. Set the values from `secrets.example.toml` in **App settings → Secrets**.
3. Save the terminal public address when it is available, then sign in and use **Check terminal compatibility** before enrolling staff.

GitHub stores the source; this repository does not create a hosted Streamlit deployment automatically. Fingerprint capture requires a person at the machine and firmware with ISAPI capture/upload support. Terminal access, firmware behavior and real biometric matching must be verified after connection.

## Validation

```bash
pip install pytest
python -m pytest -q
```

Tests cover roster reconciliation, screenshot exclusions, leading-zero IDs, identity conflicts, partial enrollment, biometric request formats and read-back, shift boundaries, report filters, export safety, passwords, and Streamlit startup without any real terminal requests. GitHub Actions runs the same test suite.
