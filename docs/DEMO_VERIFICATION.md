# Demo workflow verification — 05 October 2026

The organization and account workflows were tested on temporary fictional databases using the current Flask application. This update is based on the hierarchy/demo patches already installed, following GitHub base commit `43ea984`.

## Confirmed defects corrected

| Problem | Corrected behavior |
| --- | --- |
| Authenticated employees could open and change legacy admin records | Admin endpoints enforce the corresponding active role permission before reading or changing records |
| Cyber Security could change organization records | Organization viewing and management require separate permissions |
| A generic Head post could be linked to an Office | Head requires active Sections; Manager and Acting Manager require active Divisions |
| Moving a Section discarded its previous parent relationship | Current and previous Division relationships are stored and displayed in Edit Section |
| DVD requests could name another employee as requester | Requests are restricted to the signed-in employee with an active placement |
| DVD details could be opened by another ordinary employee | Own-request or explicit view-all permission is required |
| Invalid DVD categories caused a database error | Invalid categories and Permanent source types receive a validation response |
| Reporting backups left a SQLite handle open | Backup connection closes explicitly, matching the earlier Windows demo creation fix |

## Automated verification

31 tests pass. Coverage includes:

- Rendering 20 existing management/account/request pages with the demo banner.
- Normal Employee and Cyber Security access boundaries.
- Login lockout, password change, logout, and revocation for inactive employees.
- Atomic invalid transfers, duplicate transfer prevention, and retained location history.
- Head eligibility, cross-Division transfers, responsibility endings, and active post retention.
- Section moves blocked while dependencies exist, then recorded with parent history.
- Office, Division, and Section deactivation and controlled reactivation.
- One active employee post, single-holder senior posts, and post/unit compatibility.
- Primary Manager limits, additional Acting charges without a second post, and ending all related charges.
- Duplicate unit names, rename history, and protection for designations still in use.
- SD root/cycle protection, configurable authority reporting, and reporting history.
- Migration from the previous GitHub schema, repeat upgrades, backups, rollback, and reporting form CSRF checks.
- Demo creation, reset safeguards, original database preservation, connection closure, and read-only status checks.
- Upgrading an existing demo twice: all pre-existing table rows and the changed password hash remain identical; parent history is backfilled once.
- Own DVD prototype requests, requester identity, detail access, and invalid categories.

Run from the project root with the existing virtual environment:

```powershell
python -m unittest discover -s tests -v
```

These tests create temporary databases. They do not modify the local office or demo database.

## Install on the existing demo

1. Stop Flask with Ctrl+C. Extract the update and copy its contents into `I:\Python learning\it`, replacing matching code files.
2. In the activated virtual environment, explicitly select the existing demo and upgrade it:

```powershell
$env:OMS_DATABASE = "database/office_demo.db"
flask --app app upgrade-reporting
flask --app app run --debug
```

The upgrade prints a backup path and preserves existing data and passwords. Do not recreate or reset the demo. Do not run `apply-current-hierarchy` for this patch: it would reapply the old organization snapshot.

Parent history starts with the current relationship at upgrade time. Earlier Section moves that the old version never recorded cannot be reconstructed. Demo seeding now marks Acting responsibilities non-primary, matching the application; this does not rewrite existing demo responsibilities.

## Remaining verification and development

This is server-side test-client and database verification on Linux. It is not a visual browser check, a native Windows test, or a check of the user's actual local database. Browser layout and the Windows update must still be verified on the running local demo.

After installation, check the demo banner and current hierarchy, try one staff transfer, end one Acting charge, deactivate/reactivate a test Section, and confirm historical records remain. Also verify a Normal Employee is denied admin access. Keep these actions inside the marked demo.

The CD/DVD module remains a prototype. Submission-time immutable snapshots, approval routing, issue numbering, and the faulty/shred/replacement/closure lifecycle are not yet implemented. These are subsequent development tasks; this test result does not certify a completed DVD workflow or production readiness.
