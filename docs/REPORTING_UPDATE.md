# Editable organization reporting — 05 October 2026

This update is based on GitHub commit `43ea984` (23 September 2026).
It enables direct PM reporting and database-managed authority relationships.
SD stays at the top. Authority seats do not automatically redirect their
Divisions when a holder leaves. Changing reporting is an explicit admin action.

## Install on the existing Windows project

Stop the Flask development server first. Activate your existing virtual
environment and use the project root (`I:\Python learning\it`). Keep your local
`database/office.db` and `instance` folder; neither is distributed in this update.

After checking out the update branch, run:

```powershell
flask --app app upgrade-reporting
flask --app app apply-current-hierarchy
```

The first command backs up the SQLite database and adds the reporting schema.
It preserves existing Divisions, employees, accounts, and assignment history.
The second command is a preview only: it prints the confirmed Division labels,
their target reporting authorities, and any missing Divisions.

Existing Division names match by case, whitespace and an optional `Division`
suffix only (for example, `Technical Division` matches `Technical`). Review
missing labels before creating anything. A differently named existing Division
can be assigned manually from Manage Units instead of creating a duplicate.
Ambiguous or inactive matches abort the entire application.

When all existing Divisions match the preview:

```powershell
flask --app app apply-current-hierarchy --apply
```

If the missing Divisions truly do not exist and should be created:

```powershell
flask --app app apply-current-hierarchy --apply --create-missing
```

Applying also creates a backup. It only updates the 17 confirmed Divisions and
the current PM/DPM chain; other units are preserved. Repeating it does not add
duplicate history. This command represents the 05 October snapshot: after future
organization changes, manage reporting in the admin screens rather than applying
this old snapshot again.

Restart:

```powershell
flask --app app run --debug
```

## Manage reporting later

- Admin Dashboard → Manage Reporting Posts: add a single-holder authority post
  or change an existing authority's immediate parent.
- Manage Units → Division Reporting Authority: assign SD, PM, DPM, Associate
  Director, or another active configured authority to a Division.
- View Hierarchy: the tree follows configured relationships and lists current
  Division/Section responsibilities. Unused authority seats stay in admin
  management. No vacancy or future-reporting labels appear in the hierarchy.
- The existing Section and Office placement controls remain available.

Only accounts with `organization.manage` permission can change reporting. The
new reporting forms require a session CSRF token. Root changes, cycles,
self-reporting, inactive authorities, and invalid choices are rejected.
Authority and Division changes preserve assignment history in transactions.

## Verification

```powershell
python -m unittest discover -s tests -v
```

Coverage includes the previous GitHub database schema, repeat migration,
preserved direct PM assignments, root/cycle protection, future Associate
Director reporting, new authority creation, role permissions, CSRF,
preview/apply rollback, backups and duplicate history prevention. These checks
use temporary test databases; they do not modify the user's office database.
