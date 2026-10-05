"""Create/reset a standalone demo DB. Never writes to database/office.db."""
import argparse
import csv
import getpass
import os
import sqlite3
import shutil
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from werkzeug.security import generate_password_hash
if __package__:
    from .reporting import CURRENT_DIVISIONS, set_division_authority, record_unit_parent
else:
    from reporting import CURRENT_DIVISIONS, set_division_authority, record_unit_parent

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'database' / 'office_demo.db'
ROSTER = ROOT / 'database' / 'demo_staff.csv'
MARKER = 'OMS_DEMO_V1'


def has_demo_marker(path):
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as connection:
        table = connection.execute("SELECT 1 FROM sqlite_master WHERE name='demo_metadata' AND type='table'").fetchone()
        return bool(table and connection.execute('SELECT 1 FROM demo_metadata WHERE marker=?', (MARKER,)).fetchone())


def populate(connection, password):
    """Insert coherent posts, responsibility links, histories, accounts and locations."""
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('CREATE TABLE demo_metadata (marker TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    connection.execute('INSERT INTO demo_metadata(marker) VALUES (?)', (MARKER,))
    posts = dict(connection.execute('SELECT name,id FROM posts'))
    designations = {}
    for name in ['Senior Engineer', 'Engineer', 'Assistant', 'Principal Account Officer', 'Principal Admin Officer']:
        cursor = connection.execute('INSERT INTO designations(name) VALUES (?)', (name,))
        designations[name] = cursor.lastrowid
    roles = dict(connection.execute('SELECT name,id FROM system_roles'))
    password_hash = generate_password_hash(password)
    rows = []
    employee_rows = {}
    serial = 9900000

    def unit(name, kind, parent=None):
        cursor = connection.execute('INSERT INTO organizational_units(name,unit_type,parent_id) VALUES (?,?,?)', (name,kind,parent))
        unit_id = cursor.lastrowid
        record_unit_parent(connection,unit_id,parent)
        connection.execute('INSERT INTO organizational_unit_name_history(organizational_unit_id,name,normalized_name) VALUES (?,?,?)', (unit_id,name,name.casefold()))
        return unit_id

    def employee(name, location, section=None, designation='Engineer', role='Employee'):
        nonlocal serial
        serial += 1
        pin = str(serial)
        cursor = connection.execute('''INSERT INTO employees(pin,name,designation_id,organizational_unit_id,extension_number)
            VALUES (?,?,?,?,?)''', (pin,'DEMO '+name,designations[designation],location,str(2000+serial-9900000)))
        employee_id = cursor.lastrowid
        connection.execute('INSERT INTO employee_designation_assignments(employee_id,designation_id) VALUES (?,?)', (employee_id,designations[designation]))
        connection.execute('INSERT INTO employee_location_assignments(employee_id,organizational_unit_id,section_id) VALUES (?,?,?)', (employee_id,location,section))
        account = connection.execute('INSERT INTO user_accounts(employee_id,password_hash,must_change_password) VALUES (?,?,1)', (employee_id,password_hash)).lastrowid
        connection.execute('INSERT INTO user_role_assignments(user_account_id,system_role_id) VALUES (?,?)', (account,roles[role]))
        row = {'pin':pin,'name':'DEMO '+name,'unit_id':location,'section_id':section or '', 'system_role':role, 'post':''}
        rows.append(row)
        employee_rows[employee_id] = row
        return employee_id

    def assign_post(employee_id, name, unit_id):
        assignment_id = connection.execute('''INSERT INTO employee_post_assignments(employee_id,post_id,organizational_unit_id)
            VALUES (?,?,?)''', (employee_id,posts[name],unit_id)).lastrowid
        connection.execute('INSERT INTO post_assignment_units(post_assignment_id,organizational_unit_id) VALUES (?,?)', (assignment_id,unit_id))
        employee_rows[employee_id]['post'] = name
        return assignment_id

    offices = {name:unit(name,'Office') for name in ['SD Office','PM Office','DPM Office']}
    divisions = {}
    for authority, names in CURRENT_DIVISIONS.items():
        for name in names:
            divisions[name] = unit(name,'Division')
            set_division_authority(connection,divisions[name],posts[authority])
    # PIN 9900001 is the dedicated demo Super Admin.
    employee('Super Admin',offices['SD Office'],designation='Assistant',role='Super Admin')
    authority_locations = {
        'Senior Director':offices['SD Office'],
        'Plant Manager':offices['PM Office'],
        'Deputy Plant Manager':offices['DPM Office'],
        'HLAO':divisions['Account'],
        'Principal Administrator':divisions['Admin'],
    }
    for post_name, location in authority_locations.items():
        designation = 'Principal Account Officer' if post_name=='HLAO' else ('Principal Admin Officer' if post_name=='Principal Administrator' else 'Senior Engineer')
        holder = employee(post_name,location,designation=designation)
        assign_post(holder,post_name,location)
    # Associate Director intentionally has no holder in the current scenario.
    for office, office_id in offices.items():
        for n in range(1,4):
            employee(f'{office} Staff {n}',office_id,designation='Assistant')
    for number,(name,division_id) in enumerate(divisions.items(),1):
        post_name = 'Acting Manager' if number%4==0 else 'Manager'
        holder = employee(f'{name} {post_name}',division_id,designation='Senior Engineer')
        assignment = assign_post(holder,post_name,division_id)
        connection.execute('''INSERT INTO division_management_assignments
            (employee_id,division_id,responsibility_type,is_primary,post_assignment_id)
            VALUES (?,?,?,?,?)''', (holder,division_id,post_name,1 if post_name=='Manager' else 0,assignment))
        for n in range(1,3):
            employee(f'{name} Division Staff {n}',division_id)
        section_names = ['CS&IT','C (Communication)'] if name=='CS&C' else [f'{name} Demo Section']
        for section_name in section_names:
            section_id = unit(section_name,'Section',division_id)
            role = 'Cyber Security' if section_name=='CS&IT' else 'Employee'
            holder = employee(f'{section_name} Head',division_id,section_id,designation='Senior Engineer',role=role)
            assignment = assign_post(holder,'Head',section_id)
            connection.execute('''INSERT INTO section_head_assignments(employee_id,section_id,post_assignment_id)
                VALUES (?,?,?)''', (holder,section_id,assignment))
            for n in range(1,3):
                staff_role = 'Technical Incharge' if section_name=='CS&IT' and n==1 else 'Employee'
                employee(f'{section_name} Staff {n}',division_id,section_id,role=staff_role)
    unit_names = dict(connection.execute('SELECT id,name FROM organizational_units'))
    for row in rows:
        row['unit'] = unit_names[row.pop('unit_id')]
        section_id = row.pop('section_id')
        row['section'] = unit_names.get(section_id,'')
    violations = connection.execute('PRAGMA foreign_key_check').fetchall()
    if violations:
        raise ValueError(f'Demo database foreign key checks failed: {violations}')
    connection.commit()
    return rows


def build_demo(password, reset=False):
    if TARGET.is_symlink():
        raise ValueError('The demo database path must not be a symbolic link.')
    if TARGET.exists():
        if not reset:
            raise ValueError('office_demo.db already exists. Your test changes were preserved. Use --reset to back it up and rebuild.')
        if not has_demo_marker(TARGET):
            raise ValueError('Existing office_demo.db is not a marked demo database; refusing to replace it.')
    with tempfile.TemporaryDirectory(dir=TARGET.parent,prefix='demo_build_') as stage_name:
        stage = Path(stage_name)
        (stage/'database').mkdir()
        result = subprocess.run([sys.executable,str(ROOT/'database/database.py')],cwd=stage,capture_output=True,text=True)
        if result.returncode:
            raise ValueError(result.stderr or result.stdout)
        staged_db = stage/'database'/'office.db'
        with closing(sqlite3.connect(staged_db)) as connection:
            rows = populate(connection,password)
        staged_csv=stage/'demo_staff.csv'
        with staged_csv.open('w',newline='',encoding='utf-8-sig') as file:
            writer=csv.DictWriter(file,fieldnames=['pin','name','unit','section','post','system_role'])
            writer.writeheader();writer.writerows(rows)
        if TARGET.exists():
            if not reset or not has_demo_marker(TARGET):
                raise ValueError('Demo database changed during setup. No files replaced.')
            backup=TARGET.with_name('office_demo_before_reset_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
            with closing(sqlite3.connect(TARGET)) as source, closing(sqlite3.connect(backup)) as destination:
                source.backup(destination)
            print('Demo backup:',backup.name)
            os.replace(staged_db,TARGET)
        else:
            # Exclusive publication prevents an accidental overwrite if a file appears mid-build.
            created = False
            try:
                with TARGET.open('xb') as destination, staged_db.open('rb') as source:
                    created = True
                    shutil.copyfileobj(source,destination)
            except BaseException:
                if created:
                    TARGET.unlink(missing_ok=True)
                raise
        os.replace(staged_csv,ROSTER)
    return rows


def demo_status():
    """Read-only verification, including after a failed temporary-file cleanup."""
    if not TARGET.exists():
        print('Demo database does not exist. No files changed.')
        return False
    if not has_demo_marker(TARGET):
        raise ValueError('office_demo.db is not a marked demo database. No files changed.')
    with closing(sqlite3.connect(f'{TARGET.as_uri()}?mode=ro', uri=True)) as connection:
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Demo database integrity check failed. Preserve the file for inspection.')
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Demo relationship integrity check failed. Preserve the file for inspection.')
        employees = connection.execute('SELECT COUNT(*) FROM employees').fetchone()[0]
        counts = dict(connection.execute('SELECT unit_type,COUNT(*) FROM organizational_units GROUP BY unit_type'))
        admin = connection.execute("SELECT 1 FROM employees e JOIN user_accounts a ON a.employee_id=e.id WHERE e.pin='9900001'").fetchone()
    print('Demo database found and integrity checks passed.')
    print(f"Employees: {employees}; Offices: {counts.get('Office',0)}; Divisions: {counts.get('Division',0)}; Sections: {counts.get('Section',0)}")
    if admin:
        print('Super Admin PIN: 9900001. The password entered during creation remains in effect.')
    print('Roster present: ' + ('yes' if ROSTER.exists() else 'no'))
    print('Status check only. No database changes made.')
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--create',action='store_true',help='Create the separate demo database.')
    parser.add_argument('--reset',action='store_true',help='Back up and rebuild an existing marked demo database.')
    parser.add_argument('--status',action='store_true',help='Check the existing demo database without changing it.')
    args=parser.parse_args()
    if sum((args.create,args.reset,args.status)) > 1:
        parser.error('Choose --create, --reset or --status.')
    if args.status:
        try:
            demo_status()
        except (ValueError,OSError,sqlite3.Error) as error:
            parser.exit(1,f'Error: {error}\n')
        return
    if not args.create and not args.reset:
        print('Preview: 3 Offices, 17 Divisions, 18 Sections, 120 fictional employees.')
        print('Destination: database/office_demo.db. Current office.db will not be changed.')
        print('Other Divisions receive explicitly named Demo Sections for testing.')
        print('ICD is used from the diagram; existing CCD in your original DB is not renamed.')
        print('Run python database/seed_demo.py --create to build the separate dataset.')
        return
    try:
        password=getpass.getpass('Temporary DEMO password (12+ characters): ')
        if len(password)<12:
            raise ValueError('Use a temporary password of at least 12 characters.')
        if password != getpass.getpass('Confirm DEMO password: '):
            raise ValueError('Passwords do not match.')
        rows=build_demo(password,reset=args.reset)
        print(f'Demo database created: {len(rows)} fictional employees.')
        print('Super Admin PIN: 9900001. Use the temporary password you just entered.')
        print('Accounts require a password change on first login.')
        print('Roster: database/demo_staff.csv (contains no passwords).')
        print('PowerShell: $env:OMS_DATABASE = "database/office_demo.db"')
        print('Then: flask --app app run --debug')
    except (ValueError,OSError,sqlite3.Error) as error:
        parser.exit(1,f'Error: {error}\n')


if __name__=='__main__':
    main()
