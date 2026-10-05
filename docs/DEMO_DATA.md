# Fictional organization sandbox

The demo uses `database/office_demo.db`. It never seeds, resets or overwrites
`database/office.db`. The existing local organization changes stay in the
original database. All fictional employee names begin with `DEMO` and their
PINs start at `9900001`.

## Dataset

- Three Offices: SD Office, PM Office and DPM Office.
- Seventeen Divisions with the current SD/PM/DPM reporting relationships.
- CS&C Division under SD with CS&IT and C (Communication) Sections.
- Each other Division has one explicitly named Demo Section. These are testing
  placeholders, not assertions about the office's real Sections.
- 120 fictional employees with employee/designation/location histories.
- One Manager or Acting Manager for each Division; one Head for each Section.
- SD, PM, DPM, HLAO and Principal Administrator holders. Associate Director
  remains unassigned in the current scenario.
- A dedicated demo Super Admin (PIN 9900001), normal employees, a Cyber Security
  role on the CS&IT Head and a separate Technical Incharge account.
- A generated `database/demo_staff.csv` lists PINs, names, placements, posts and
  software roles. It contains no passwords.

The demo uses ICD from the confirmed diagram. The existing CCD in the original
local database is left untouched; whether CCD should be renamed is unresolved.

## Setup from PowerShell

Stop Flask and activate the existing virtual environment in the project root.
Apply the files from this update ZIP, preserving their folder structure.

Preview (no database creation):

```powershell
python database/seed_demo.py
```

Create:

```powershell
python database/seed_demo.py --create
```

Enter a temporary password of 12 or more characters twice. It is initially
used for the demo accounts only. The script stores password hashes, and every
account requires a change on first login. Do not send the password in chat.

Run the demo:

```powershell
$env:OMS_DATABASE = "database/office_demo.db"
flask --app app run --debug
```

Use PIN **9900001** and the temporary demo password. The demo has a separate
session cookie from the original database. A yellow DEMO DATABASE banner
appears on HTML pages. The existing role dashboards/approval workflow are not
implemented by this seeder; it populates the organization and account roles.

## Practice and reset

Try an employee transfer, ending a post assignment, assigning a replacement
Head/Manager, changing a Division's authority, and unit deactivation/reactivation.
Verify the current relationship changes and the old record remains in history.
Linked records use the existing safeguards; a Section move may require ending
its current Head responsibility or transferring its staff first. Errors from
those safeguards are expected test outcomes, not proof of database corruption.
Use deactivate/end instead of deleting linked history records.

To rebuild after experiments, stop Flask and run:

```powershell
python database/seed_demo.py --reset
```

The script backs up the marked demo database before rebuilding it. It refuses
to reset an unmarked file or overwrite an existing demo on ordinary `--create`.
It prompts for a new temporary password. Roster contents are regenerated.

Return to the original database by stopping Flask and clearing the environment
variable in the same terminal:

```powershell
Remove-Item Env:OMS_DATABASE
flask --app app run --debug
```

The setting applies to this terminal session only. A new terminal uses the
original database unless `OMS_DATABASE` is set again.

## Verification

Ten automated tests passed for the hierarchy and sandbox changes. Checks include
fresh database seeding, all relationship constraints, demo login and banner,
actual employee transfer and post-ending routes, preservation of history,
reset backups, overwrite refusal and an unchanged original-database checksum.
Tests use temporary databases.
