from contextlib import closing
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app import app
from database.reporting import upgrade_reporting, set_post_parent, set_division_authority, current_structure_plan

REPO = Path(__file__).resolve().parents[1]


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'database' / 'office.db'
        self.db.parent.mkdir()
        subprocess.run([sys.executable, str(REPO / 'database/database.py')], cwd=self.temp.name, check=True, capture_output=True)
        self.connection = sqlite3.connect(self.db)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.ids = {row['name']: row['id'] for row in self.connection.execute('SELECT id,name FROM posts')}
        self.connection.execute("INSERT INTO organizational_units(name,unit_type) VALUES ('Technical Division','Division')")
        self.division = self.connection.execute('SELECT last_insert_rowid()').fetchone()[0]
        self.connection.execute("INSERT INTO designations(name) VALUES ('Engineer')")
        self.connection.execute("INSERT INTO employees(pin,name,designation_id,organizational_unit_id) VALUES ('123','Test User',1,?)", (self.division,))
        self.connection.execute("INSERT INTO user_accounts(employee_id,password_hash,must_change_password) VALUES (1,'unused',0)")
        self.connection.execute("INSERT INTO user_role_assignments(user_account_id,system_role_id) SELECT 1,id FROM system_roles WHERE name='Super Admin'")
        self.connection.commit()
        app.config.update(TESTING=True,DATABASE=str(self.db),SECRET_KEY='test-only')
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['user_account_id'] = 1

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_upgrade_preserves_legacy_pm_and_history(self):
        set_division_authority(self.connection,self.division,self.ids['Plant Manager'])
        self.connection.commit()
        before = [tuple(r) for r in self.connection.execute('SELECT * FROM division_reporting_assignments')]
        for _ in range(2):
            upgrade_reporting(self.connection)
        self.connection.commit()
        self.assertEqual(before, [tuple(r) for r in self.connection.execute('SELECT * FROM division_reporting_assignments')])
        self.assertEqual(5,self.connection.execute('SELECT COUNT(*) FROM post_reporting_assignments').fetchone()[0])
        self.assertEqual(1,self.connection.execute('SELECT COUNT(*) FROM employees').fetchone()[0])

    def test_first_upgrade_from_previous_github_schema(self):
        old_dir=Path(self.temp.name)/'legacy'
        (old_dir/'database').mkdir(parents=True)
        old_script=subprocess.check_output(['git','show','43ea984:database/database.py'],cwd=REPO)
        (old_dir/'database/database.py').write_bytes(old_script)
        subprocess.run([sys.executable,str(old_dir/'database/database.py')],cwd=old_dir,check=True,capture_output=True)
        with closing(sqlite3.connect(old_dir/'database/office.db')) as legacy, legacy:
            legacy.execute("INSERT INTO organizational_units(name,unit_type) VALUES ('QC','Division')")
            legacy.execute("INSERT INTO division_reporting_assignments(division_id,authority_post_id) SELECT 1,id FROM posts WHERE name='Plant Manager'")
            before=legacy.execute('SELECT * FROM division_reporting_assignments').fetchall()
            legacy.execute("BEGIN IMMEDIATE") if not legacy.in_transaction else None
            upgrade_reporting(legacy)
            self.assertEqual(before,legacy.execute('SELECT * FROM division_reporting_assignments').fetchall())
            self.assertEqual(1,legacy.execute("SELECT is_reporting_authority FROM posts WHERE name='Plant Manager'").fetchone()[0])
            self.assertEqual(1,legacy.execute("SELECT max_active_holders FROM posts WHERE name='Associate Director'").fetchone()[0])
            self.assertFalse(legacy.execute('PRAGMA foreign_key_check').fetchall())

    def test_cycle_root_and_invalid_posts_rejected(self):
        for child,parent in [('Plant Manager','Deputy Plant Manager'),('Senior Director','Plant Manager'),('Plant Manager','Plant Manager'),('Plant Manager','Head')]:
            with self.assertRaises(ValueError):
                set_post_parent(self.connection,self.ids[child],self.ids[parent])
        self.assertEqual(5,self.connection.execute('SELECT COUNT(*) FROM post_reporting_assignments').fetchone()[0])

    def test_future_authority_reparenting_and_history(self):
        with self.connection:
            set_post_parent(self.connection,self.ids['Deputy Plant Manager'],self.ids['Associate Director'])
            set_division_authority(self.connection,self.division,self.ids['Plant Manager'])
            set_division_authority(self.connection,self.division,self.ids['Associate Director'])
            self.assertFalse(set_division_authority(self.connection,self.division,self.ids['Associate Director']))
        self.assertEqual(2,self.connection.execute('SELECT COUNT(*) FROM division_reporting_assignments').fetchone()[0])
        ended=self.connection.execute('SELECT * FROM division_reporting_assignments WHERE is_active=0').fetchone()
        self.assertTrue(ended['end_date'])
        self.assertEqual(6,self.connection.execute('SELECT COUNT(*) FROM post_reporting_assignments').fetchone()[0])
        upgrade_reporting(self.connection)
        parent=self.connection.execute('SELECT parent_post_id FROM post_reporting_assignments WHERE post_id=? AND is_active=1',(self.ids['Deputy Plant Manager'],)).fetchone()[0]
        self.assertEqual(self.ids['Associate Director'],parent)
        page=self.client.get('/admin/organization-hierarchy')
        self.assertIn(b'Associate Director',page.data)

    def test_forms_permissions_csrf_and_new_authority(self):
        self.assertEqual(200,self.client.get('/admin/reporting-posts').status_code)
        with self.client.session_transaction() as session:
            csrf=session['reporting_csrf_token']
        self.assertEqual(400,self.client.post('/admin/reporting-posts',data={'name':'Director Technical','parent_post_id':self.ids['Senior Director']}).status_code)
        response=self.client.post('/admin/reporting-posts',data={'name':'Director Technical','parent_post_id':self.ids['Senior Director'],'csrf_token':csrf})
        self.assertEqual(302,response.status_code)
        self.assertEqual(400,self.client.post('/admin/reporting-posts',data={'name':'director technical','parent_post_id':self.ids['Senior Director'],'csrf_token':csrf}).status_code)
        response=self.client.get(f'/admin/divisions/{self.division}/reporting-authority')
        self.assertEqual(200,response.status_code)
        self.assertIn(b'Plant Manager',response.data)
        self.assertIn(b'Associate Director',response.data)
        self.assertEqual(302,self.client.post(f'/admin/divisions/{self.division}/reporting-authority',data={'authority_post_id':self.ids['Plant Manager'],'csrf_token':csrf}).status_code)
        self.connection.execute('UPDATE user_role_assignments SET is_active=0')
        self.connection.commit()
        self.assertEqual(403,self.client.get('/admin/reporting-posts').status_code)
        self.assertEqual(403,self.client.post(f'/admin/divisions/{self.division}/reporting-authority',data={'authority_post_id':self.ids['Senior Director'],'csrf_token':csrf}).status_code)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual('/login',self.client.get('/admin/reporting-posts').location)

    def test_current_hierarchy_preview_apply_idempotence_and_backup(self):
        runner=app.test_cli_runner()
        self.assertEqual(0,runner.invoke(args=['upgrade-reporting']).exit_code)
        preview=runner.invoke(args=['apply-current-hierarchy'])
        self.assertEqual(0,preview.exit_code)
        self.assertEqual(1,self.connection.execute('SELECT COUNT(*) FROM organizational_units').fetchone()[0])
        blocked=runner.invoke(args=['apply-current-hierarchy','--apply'])
        self.assertNotEqual(0,blocked.exit_code)
        self.assertEqual(0,self.connection.execute('SELECT COUNT(*) FROM division_reporting_assignments').fetchone()[0])
        applied=runner.invoke(args=['apply-current-hierarchy','--apply','--create-missing'])
        self.assertEqual(0,applied.exit_code,applied.output)
        self.assertEqual(17,self.connection.execute('SELECT COUNT(*) FROM division_reporting_assignments WHERE is_active=1').fetchone()[0])
        repeated=runner.invoke(args=['apply-current-hierarchy','--apply','--create-missing'])
        self.assertEqual(0,repeated.exit_code,repeated.output)
        self.assertEqual(17,self.connection.execute('SELECT COUNT(*) FROM division_reporting_assignments').fetchone()[0])
        self.assertTrue(list(self.db.parent.glob('*before_reporting*.db')))
        page=self.client.get('/admin/organization-hierarchy')
        self.assertEqual(200,page.status_code)
        self.assertNotIn(b'vacant',page.data.lower())
        self.assertNotIn(b'Associate Director',page.data)
        for label in [b'QC',b'SCS',b'GSD',b'ESD',b'HP &amp; OS']:
            self.assertIn(label,page.data)

    def test_ambiguous_name_aborts(self):
        self.connection.execute("INSERT INTO organizational_units(name,unit_type) VALUES (' Technical  Division ','Division')")
        self.connection.commit()
        with self.assertRaises(ValueError):
            current_structure_plan(self.connection)
        result=app.test_cli_runner().invoke(args=['apply-current-hierarchy','--apply','--create-missing'])
        self.assertNotEqual(0,result.exit_code)
        self.assertEqual(0,self.connection.execute('SELECT COUNT(*) FROM division_reporting_assignments').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
