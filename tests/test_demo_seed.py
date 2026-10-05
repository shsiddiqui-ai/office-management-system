from contextlib import closing
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from database import seed_demo


class DemoSeedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.target=self.folder/'office_demo.db'
        self.roster=self.folder/'demo_staff.csv'
        self.original=self.folder/'office.db'
        with closing(sqlite3.connect(self.original)) as connection, connection:
            connection.execute('CREATE TABLE sentinel(value)')
            connection.execute("INSERT INTO sentinel VALUES ('original data')")
        self.original_hash=hashlib.sha256(self.original.read_bytes()).hexdigest()
        self.patches=[patch.object(seed_demo,'TARGET',self.target),patch.object(seed_demo,'ROSTER',self.roster)]
        for item in self.patches:item.start()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def test_full_dataset_and_original_is_untouched(self):
        rows=seed_demo.build_demo('Example-demo-Password-2026')
        self.assertEqual(120,len(rows))
        self.assertEqual(self.original_hash,hashlib.sha256(self.original.read_bytes()).hexdigest())
        with closing(sqlite3.connect(self.target)) as connection, connection:
            self.assertFalse(connection.execute('PRAGMA foreign_key_check').fetchall())
            for table,count in [('employees',120),('user_accounts',120),('employee_location_assignments',120),('employee_designation_assignments',120),('division_management_assignments',17),('section_head_assignments',18)]:
                self.assertEqual(count,connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],table)
            for kind,count in [('Office',3),('Division',17),('Section',18)]:
                self.assertEqual(count,connection.execute('SELECT COUNT(*) FROM organizational_units WHERE unit_type=?',(kind,)).fetchone()[0])
            self.assertEqual(2,connection.execute("SELECT COUNT(*) FROM organizational_units s JOIN organizational_units d ON s.parent_id=d.id WHERE d.name='CS&C'").fetchone()[0])
            self.assertEqual(0,connection.execute("SELECT COUNT(*) FROM organizational_units WHERE name='CS & IT'").fetchone()[0])
            self.assertEqual(0,connection.execute("SELECT COUNT(*) FROM employee_post_assignments a JOIN posts p ON p.id=a.post_id WHERE p.name='Associate Director'").fetchone()[0])
            self.assertFalse(connection.execute('SELECT employee_id FROM employee_post_assignments WHERE is_active=1 GROUP BY employee_id HAVING COUNT(*)>1').fetchall())
            self.assertFalse(connection.execute('''SELECT p.id FROM posts p JOIN employee_post_assignments a ON a.post_id=p.id AND a.is_active=1
                WHERE p.max_active_holders=1 GROUP BY p.id HAVING COUNT(*)>1''').fetchall())
            self.assertEqual(120,connection.execute('SELECT COUNT(*) FROM user_accounts WHERE must_change_password=1').fetchone()[0])
        self.assertNotIn('Example-demo-Password-2026',self.roster.read_text(encoding='utf-8-sig'))
        with self.assertRaises(ValueError):seed_demo.build_demo('Another-demo-password')

    def test_demo_login_banner_transfer_and_end_assignment(self):
        seed_demo.build_demo('Example-demo-Password-2026')
        app.config.update(TESTING=True,DATABASE=str(self.target),SECRET_KEY='test-demo')
        client=app.test_client()
        result=client.post('/login',data={'pin':'9900001','password':'Example-demo-Password-2026'})
        self.assertEqual(302,result.status_code)
        self.assertIn('/change-password',result.location)
        with closing(sqlite3.connect(self.target)) as connection, connection:
            connection.execute('UPDATE user_accounts SET must_change_password=0 WHERE employee_id=1')
        result=client.get('/admin/organization-hierarchy')
        self.assertEqual(200,result.status_code)
        self.assertIn(b'DEMO DATABASE',result.data)
        self.assertIn(b'CS&amp;C',result.data)
        self.assertNotIn(b'Associate Director',result.data)
        with closing(sqlite3.connect(self.target)) as connection, connection:
            employee=connection.execute("SELECT id,pin,name,designation_id FROM employees WHERE name='DEMO QA Division Staff 1'").fetchone()
            target_division=connection.execute("SELECT id FROM organizational_units WHERE name='Technical'").fetchone()[0]
            head_assignment=connection.execute('SELECT post_assignment_id FROM section_head_assignments LIMIT 1').fetchone()[0]
        response=client.post(f'/admin/employees/edit/{employee[0]}',data={'pin':employee[1],'name':employee[2],'designation_id':employee[3],'organizational_unit_id':target_division,'section_id':'','extension_number':'2233','is_active':'1'})
        self.assertEqual(302,response.status_code,response.data)
        with closing(sqlite3.connect(self.target)) as connection, connection:
            self.assertEqual(2,connection.execute('SELECT COUNT(*) FROM employee_location_assignments WHERE employee_id=?',(employee[0],)).fetchone()[0])
            self.assertEqual(target_division,connection.execute('SELECT organizational_unit_id FROM employee_location_assignments WHERE employee_id=? AND is_active=1',(employee[0],)).fetchone()[0])
        response=client.post(f'/admin/posts/end/{head_assignment}')
        self.assertEqual(302,response.status_code)
        with closing(sqlite3.connect(self.target)) as connection, connection:
            self.assertEqual(0,connection.execute('SELECT is_active FROM employee_post_assignments WHERE id=?',(head_assignment,)).fetchone()[0])
            self.assertEqual(0,connection.execute('SELECT is_active FROM section_head_assignments WHERE post_assignment_id=?',(head_assignment,)).fetchone()[0])
        self.assertEqual(self.original_hash,hashlib.sha256(self.original.read_bytes()).hexdigest())

    def test_every_seed_connection_closes_before_file_cleanup(self):
        real_connect=sqlite3.connect
        opened=[]
        class TrackedConnection(sqlite3.Connection):
            closed=False
            def close(self):
                self.closed=True
                return super().close()
        def tracked_connect(*args,**kwargs):
            kwargs['factory']=TrackedConnection
            connection=real_connect(*args,**kwargs)
            opened.append(connection)
            return connection
        with patch.object(seed_demo.sqlite3,'connect',side_effect=tracked_connect):
            seed_demo.build_demo('Example-demo-Password-2026')
            seed_demo.build_demo('Another-demo-password',reset=True)
            self.assertTrue(seed_demo.demo_status())
        self.assertTrue(opened)
        self.assertTrue(all(connection.closed for connection in opened))
        self.assertFalse(list(self.folder.glob('demo_build_*')))

    def test_status_is_read_only_after_creation(self):
        self.assertFalse(seed_demo.demo_status())
        seed_demo.build_demo('Example-demo-Password-2026')
        before=hashlib.sha256(self.target.read_bytes()).hexdigest()
        self.assertTrue(seed_demo.demo_status())
        self.assertEqual(before,hashlib.sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(self.original_hash,hashlib.sha256(self.original.read_bytes()).hexdigest())

    def test_reset_backs_up_and_refuses_unmarked_database(self):
        seed_demo.build_demo('Example-demo-Password-2026')
        with closing(sqlite3.connect(self.target)) as connection, connection:
            connection.execute("UPDATE employees SET name='DEMO Changed Name' WHERE id=1")
        seed_demo.build_demo('Another-demo-password',reset=True)
        backups=list(self.folder.glob('office_demo_before_reset_*.db'))
        self.assertEqual(1,len(backups))
        with closing(sqlite3.connect(backups[0])) as connection, connection:
            self.assertEqual('DEMO Changed Name',connection.execute('SELECT name FROM employees WHERE id=1').fetchone()[0])
        with closing(sqlite3.connect(self.target)) as connection, connection:
            connection.execute('DROP TABLE demo_metadata')
        before=hashlib.sha256(self.target.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):seed_demo.build_demo('Another-demo-password',reset=True)
        self.assertEqual(before,hashlib.sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(self.original_hash,hashlib.sha256(self.original.read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()
