"""Behavior checks against a fresh complete fictional organization."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from database import seed_demo


class DemoWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        folder=Path(self.temp.name)
        self.db=folder/'office_demo.db'
        with patch.object(seed_demo,'TARGET',self.db),patch.object(seed_demo,'ROSTER',folder/'staff.csv'):
            seed_demo.build_demo('Test-demo-Password-2026')
        self.connection=sqlite3.connect(self.db)
        self.connection.row_factory=sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.execute('UPDATE user_accounts SET must_change_password=0')
        self.connection.commit()
        app.config.update(TESTING=True,DATABASE=str(self.db),SECRET_KEY='test-workflows')
        self.client=app.test_client()
        self.login_as('DEMO Super Admin')

    def tearDown(self):
        self.connection.close();self.temp.cleanup()

    def employee(self,name):
        return self.connection.execute('SELECT * FROM employees WHERE name=?',(name,)).fetchone()

    def unit(self,name):
        return self.connection.execute('SELECT * FROM organizational_units WHERE name=?',(name,)).fetchone()

    def post(self,name):
        return self.connection.execute('SELECT * FROM posts WHERE name=?',(name,)).fetchone()

    def login_as(self,name):
        employee=self.employee(name)
        account=self.connection.execute('SELECT id FROM user_accounts WHERE employee_id=?',(employee['id'],)).fetchone()
        with self.client.session_transaction() as session:
            session.clear();session['user_account_id']=account[0]

    def edit_employee(self,employee,unit,section='',designation=None):
        return self.client.post(f"/admin/employees/edit/{employee['id']}",data={
            'pin':employee['pin'],'name':employee['name'],'designation_id':designation or employee['designation_id'],
            'organizational_unit_id':unit,'section_id':section,'extension_number':employee['extension_number']})

    def assert_integrity(self):
        self.assertFalse(self.connection.execute('PRAGMA foreign_key_check').fetchall())
        for table,key,condition in [('employee_post_assignments','employee_id','is_active=1'),('employee_location_assignments','employee_id','is_active=1'),('division_management_assignments','division_id','is_active=1'),('section_head_assignments','section_id','is_active=1'),('division_reporting_assignments','division_id','is_active=1')]:
            self.assertFalse(self.connection.execute(f'SELECT {key} FROM {table} WHERE {condition} GROUP BY {key} HAVING COUNT(*)>1').fetchall(),table)

    def test_all_existing_management_get_screens_render(self):
        paths=['/','/admin','/admin/units','/admin/units/add','/admin/designations','/admin/designations/add','/admin/employees','/admin/employees/add','/admin/posts','/admin/posts/assign','/admin/reporting-posts','/admin/organization-hierarchy','/cd-dvd','/dvd-request/new','/change-password']
        division=self.unit('CS&C')['id'];section=self.unit('CS&IT')['id'];employee=self.employee('DEMO Super Admin')['id']
        paths += [f'/admin/units/edit/{section}',f'/admin/employees/edit/{employee}',f'/admin/divisions/{division}/management',f'/admin/divisions/{division}/reporting-authority',f'/admin/sections/{section}/head']
        for path in paths:
            with self.subTest(path=path):
                result=self.client.get(path)
                self.assertEqual(200,result.status_code,result.data[:500])
                self.assertIn(b'DEMO DATABASE',result.data)

    def test_existing_demo_upgrade_preserves_data_and_password_and_is_repeatable(self):
        # Simulate the demo version installed before parent history existed.
        self.connection.execute('DROP TABLE organizational_unit_parent_history')
        self.connection.execute("UPDATE user_accounts SET password_hash='changed-password-hash' WHERE id=1")
        self.connection.commit()
        tables=[row[0] for row in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        before={table:[tuple(row) for row in self.connection.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                for table in tables}
        for _ in range(2):
            result=app.test_cli_runner().invoke(args=['upgrade-reporting'])
            self.assertEqual(0,result.exit_code,result.output)
        for table in tables:
            self.assertEqual(before[table],[tuple(row) for row in self.connection.execute(
                f'SELECT * FROM {table} ORDER BY rowid')],table)
        self.assertEqual(38,self.connection.execute(
            'SELECT COUNT(*) FROM organizational_unit_parent_history').fetchone()[0])
        self.assertEqual(2,len(list(self.db.parent.glob('office_demo_before_reporting_*.db'))))
        self.assert_integrity()

    def test_employee_cannot_read_or_mutate_admin_records(self):
        self.login_as('DEMO QA Division Staff 1')
        for path in ['/admin/units','/admin/employees','/admin/posts','/admin/designations','/admin/reporting-posts']:
            with self.subTest(path=path):self.assertEqual(403,self.client.get(path).status_code)
        before=self.connection.execute('SELECT COUNT(*) FROM organizational_units').fetchone()[0]
        result=self.client.post('/admin/units/add',data={'name':'Unauthorized','unit_type':'Division'})
        self.assertEqual(403,result.status_code)
        self.assertEqual(before,self.connection.execute('SELECT COUNT(*) FROM organizational_units').fetchone()[0])

    def test_cyber_security_can_view_but_not_change_organization(self):
        self.login_as('DEMO CS&IT Head')
        self.assertEqual(200,self.client.get('/admin/units').status_code)
        self.assertEqual(403,self.client.post('/admin/units/add',data={'name':'Unauthorized','unit_type':'Division'}).status_code)

    def test_transfer_history_and_invalid_section_are_atomic(self):
        employee=self.employee('DEMO QA Division Staff 1')
        division=self.unit('Technical')['id'];wrong=self.unit('CS&IT')['id']
        before=self.connection.execute('SELECT COUNT(*) FROM employee_location_assignments').fetchone()[0]
        self.assertEqual(400,self.edit_employee(employee,division,wrong).status_code)
        self.assertEqual(before,self.connection.execute('SELECT COUNT(*) FROM employee_location_assignments').fetchone()[0])
        self.assertEqual(302,self.edit_employee(employee,division).status_code)
        self.assertEqual(2,self.connection.execute('SELECT COUNT(*) FROM employee_location_assignments WHERE employee_id=?',(employee['id'],)).fetchone()[0])
        self.assertEqual(302,self.edit_employee(employee,division).status_code)
        self.assertEqual(2,self.connection.execute('SELECT COUNT(*) FROM employee_location_assignments WHERE employee_id=?',(employee['id'],)).fetchone()[0])
        self.assert_integrity()

    def test_head_transfer_closes_responsibility_and_keeps_post_history(self):
        employee=self.employee('DEMO CS&IT Head')
        post_assignment=self.connection.execute('SELECT id FROM employee_post_assignments WHERE employee_id=? AND is_active=1',(employee['id'],)).fetchone()[0]
        self.assertEqual(302,self.edit_employee(employee,self.unit('QA')['id']).status_code)
        self.assertEqual(0,self.connection.execute('SELECT COUNT(*) FROM section_head_assignments WHERE employee_id=? AND is_active=1',(employee['id'],)).fetchone()[0])
        self.assertEqual(0,self.connection.execute('SELECT COUNT(*) FROM post_assignment_units WHERE post_assignment_id=? AND is_active=1',(post_assignment,)).fetchone()[0])
        self.assertEqual(1,self.connection.execute('SELECT COUNT(*) FROM employee_post_assignments WHERE employee_id=? AND is_active=1',(employee['id'],)).fetchone()[0])
        self.assert_integrity()

    def test_section_move_blocked_until_dependencies_end_then_parent_history(self):
        section=self.unit('CS&IT');target=self.unit('QA')['id']
        payload={'name':section['name'],'parent_id':target}
        self.assertEqual(400,self.client.post(f"/admin/units/edit/{section['id']}",data=payload).status_code)
        employees=self.connection.execute('SELECT e.* FROM employees e JOIN employee_location_assignments l ON e.id=l.employee_id AND l.is_active=1 WHERE l.section_id=?',(section['id'],)).fetchall()
        for employee in employees:
            self.assertEqual(302,self.edit_employee(employee,target).status_code)
        self.assertEqual(302,self.client.post(f"/admin/units/edit/{section['id']}",data=payload).status_code)
        self.assertEqual(target,self.unit('CS&IT')['parent_id'])
        history=self.connection.execute('SELECT * FROM organizational_unit_parent_history WHERE organizational_unit_id=? ORDER BY id',(section['id'],)).fetchall()
        self.assertEqual(2,len(history))
        self.assertEqual(section['parent_id'],history[0]['parent_id'])
        self.assertTrue(history[0]['end_date'])
        self.assert_integrity()

    def test_section_deactivate_preserves_division_and_history(self):
        section=self.unit('CS&IT')
        affected=self.connection.execute('SELECT employee_id FROM employee_location_assignments WHERE section_id=? AND is_active=1',(section['id'],)).fetchall()
        self.assertEqual(302,self.client.post(f"/admin/units/deactivate/{section['id']}").status_code)
        for row in affected:
            current=self.connection.execute('SELECT * FROM employee_location_assignments WHERE employee_id=? AND is_active=1',(row[0],)).fetchone()
            self.assertEqual(section['parent_id'],current['organizational_unit_id']);self.assertIsNone(current['section_id'])
        self.assertEqual(0,self.connection.execute('SELECT COUNT(*) FROM section_head_assignments WHERE section_id=? AND is_active=1',(section['id'],)).fetchone()[0])
        self.assertEqual(302,self.client.post(f"/admin/units/reactivate/{section['id']}").status_code)
        self.assertEqual(0,self.connection.execute('SELECT COUNT(*) FROM section_head_assignments WHERE section_id=? AND is_active=1',(section['id'],)).fetchone()[0])
        self.assert_integrity()

    def test_division_deactivate_closes_children_reporting_and_responsibilities(self):
        division=self.unit('CS&C');section=self.unit('CS&IT')
        self.assertEqual(302,self.client.post(f"/admin/units/deactivate/{division['id']}").status_code)
        for table,column in [('division_reporting_assignments','division_id'),('division_management_assignments','division_id'),('employee_location_assignments','organizational_unit_id')]:
            self.assertEqual(0,self.connection.execute(f'SELECT COUNT(*) FROM {table} WHERE {column}=? AND is_active=1',(division['id'],)).fetchone()[0])
        self.assertEqual(0,self.unit('CS&IT')['is_active'])
        self.assertEqual(400,self.client.post(f"/admin/units/reactivate/{section['id']}").status_code)
        self.assertEqual(302,self.client.post(f"/admin/units/reactivate/{division['id']}").status_code)
        self.assertEqual(302,self.client.post(f"/admin/units/reactivate/{section['id']}").status_code)
        self.assert_integrity()

    def test_office_deactivation_preserves_employees_and_ends_placements(self):
        office=self.unit('PM Office')
        count=self.connection.execute('SELECT COUNT(*) FROM employees').fetchone()[0]
        self.assertEqual(302,self.client.post(f"/admin/units/deactivate/{office['id']}").status_code)
        self.assertEqual(0,self.connection.execute('SELECT COUNT(*) FROM employee_location_assignments WHERE organizational_unit_id=? AND is_active=1',(office['id'],)).fetchone()[0])
        self.assertEqual(count,self.connection.execute('SELECT COUNT(*) FROM employees').fetchone()[0])
        self.assert_integrity()

    def test_primary_manager_limit_and_multi_division_acting_charge(self):
        manager=self.employee('DEMO QA Manager');target=self.unit('Technical')['id']
        data={'employee_id':manager['id'],'responsibility_type':'Manager'}
        self.assertEqual(400,self.client.post(f'/admin/divisions/{target}/management',data=data).status_code)
        data['responsibility_type']='Acting Manager'
        self.assertEqual(302,self.client.post(f'/admin/divisions/{target}/management',data=data).status_code)
        self.assertEqual(2,self.connection.execute('SELECT COUNT(*) FROM division_management_assignments WHERE employee_id=? AND is_active=1',(manager['id'],)).fetchone()[0])
        before=self.connection.execute('SELECT COUNT(*) FROM division_management_assignments').fetchone()[0]
        self.assertEqual(302,self.client.post(f'/admin/divisions/{target}/management',data=data).status_code)
        self.assertEqual(before,self.connection.execute('SELECT COUNT(*) FROM division_management_assignments').fetchone()[0])
        assignment=self.connection.execute('SELECT id FROM employee_post_assignments WHERE employee_id=? AND is_active=1',(manager['id'],)).fetchone()[0]
        self.assertEqual(302,self.client.post(f'/admin/posts/end/{assignment}').status_code)
        self.assertEqual(0,self.connection.execute('SELECT COUNT(*) FROM division_management_assignments WHERE employee_id=? AND is_active=1',(manager['id'],)).fetchone()[0])
        self.assert_integrity()

    def test_head_eligibility_and_duplicate_assignment(self):
        section=self.unit('CS&IT')['id'];wrong=self.employee('DEMO QA Demo Section Head')['id'];head=self.employee('DEMO CS&IT Head')['id']
        self.assertEqual(400,self.client.post(f'/admin/sections/{section}/head',data={'employee_id':wrong}).status_code)
        before=self.connection.execute('SELECT COUNT(*) FROM section_head_assignments').fetchone()[0]
        self.assertEqual(302,self.client.post(f'/admin/sections/{section}/head',data={'employee_id':head}).status_code)
        self.assertEqual(before,self.connection.execute('SELECT COUNT(*) FROM section_head_assignments').fetchone()[0])
        self.assert_integrity()

    def test_single_post_single_holder_and_unit_type_validation(self):
        employee=self.employee('DEMO QA Division Staff 1');holder=self.employee('DEMO QA Manager')
        self.assertEqual(400,self.client.post('/admin/posts/assign',data={'employee_id':holder['id'],'post_id':self.post('Head')['id'],'organizational_unit_ids':self.unit('QA Demo Section')['id']}).status_code)
        self.assertEqual(400,self.client.post('/admin/posts/assign',data={'employee_id':employee['id'],'post_id':self.post('Senior Director')['id']}).status_code)
        self.assertEqual(400,self.client.post('/admin/posts/assign',data={'employee_id':employee['id'],'post_id':self.post('Head')['id'],'organizational_unit_ids':self.unit('PM Office')['id']}).status_code)
        self.assert_integrity()

    def test_duplicate_unit_names_and_rename_history(self):
        self.assertEqual(400,self.client.post('/admin/units/add',data={'name':' cs&c  ','unit_type':'Division'}).status_code)
        section=self.unit('CS&IT');target=self.unit('CS&C')['id']
        self.assertEqual(400,self.client.post('/admin/units/add',data={'name':' c (communication) ','unit_type':'Section','parent_id':target}).status_code)
        self.assertEqual(302,self.client.post(f"/admin/units/edit/{section['id']}",data={'name':'CS&IT Renamed','parent_id':target}).status_code)
        records=self.connection.execute('SELECT * FROM organizational_unit_name_history WHERE organizational_unit_id=?',(section['id'],)).fetchall()
        self.assertEqual(2,len(records));self.assertEqual(1,sum(r['is_current'] for r in records))

    def test_designation_in_use_cannot_be_deleted(self):
        employee=self.employee('DEMO QA Division Staff 1')
        self.assertEqual(400,self.client.post(f"/admin/designations/delete/{employee['designation_id']}").status_code)
        self.assert_integrity()

    def test_login_lockout_password_change_and_logout(self):
        client=app.test_client();admin=self.employee('DEMO Super Admin')
        for _ in range(5):self.assertEqual(200,client.post('/login',data={'pin':admin['pin'],'password':'incorrect'}).status_code)
        account=self.connection.execute('SELECT * FROM user_accounts WHERE employee_id=?',(admin['id'],)).fetchone()
        self.assertTrue(account['locked_until'])
        self.assertIn(b'temporarily locked',client.post('/login',data={'pin':admin['pin'],'password':'Test-demo-Password-2026'}).data)
        self.connection.execute("UPDATE user_accounts SET locked_until=datetime('now','-1 minute'),must_change_password=1 WHERE employee_id=?",(admin['id'],));self.connection.commit()
        self.assertEqual('/change-password',client.post('/login',data={'pin':admin['pin'],'password':'Test-demo-Password-2026'}).location)
        self.assertEqual('/change-password',client.get('/admin').location)
        self.assertIn(b'Current password is incorrect',client.post('/change-password',data={'current_password':'incorrect','new_password':'Changed-demo-password','confirm_password':'Changed-demo-password'}).data)
        self.assertEqual(302,client.post('/change-password',data={'current_password':'Test-demo-Password-2026','new_password':'Changed-demo-password','confirm_password':'Changed-demo-password'}).status_code)
        self.assertEqual(200,client.get('/admin').status_code)
        self.assertEqual('/login',client.post('/logout').location)
        self.assertEqual('/login',client.get('/admin').location)

    def test_inactive_account_or_employee_session_is_revoked(self):
        self.connection.execute('UPDATE employees SET is_active=0 WHERE id=1');self.connection.commit()
        self.assertEqual('/login',self.client.get('/admin').location)
        with self.client.session_transaction() as session:self.assertNotIn('user_account_id',session)

    def test_employee_cannot_impersonate_requester_or_read_others_request(self):
        admin=self.employee('DEMO Super Admin')
        self.connection.execute("INSERT INTO dvd_requests(requester_employee_id,dvd_category) VALUES (?,'Internal')",(admin['id'],));self.connection.commit()
        request_id=self.connection.execute('SELECT MAX(id) FROM dvd_requests').fetchone()[0]
        self.login_as('DEMO QA Division Staff 1')
        self.assertEqual(400,self.client.post('/dvd-request/new',data={'requester_employee_id':admin['id'],'dvd_category':'Internal'}).status_code)
        self.assertIn(self.client.get(f'/dvd-request/{request_id}').status_code,[403,404])

    def test_own_prototype_request_and_invalid_category(self):
        self.login_as('DEMO QA Division Staff 1');employee=self.employee('DEMO QA Division Staff 1')
        self.assertEqual(400,self.client.post('/dvd-request/new',data={'requester_employee_id':employee['id'],'dvd_category':'Invalid'}).status_code)
        self.assertEqual(302,self.client.post('/dvd-request/new',data={'requester_employee_id':employee['id'],'dvd_category':'Internal'}).status_code)
        request_id=self.connection.execute('SELECT MAX(id) FROM dvd_requests').fetchone()[0]
        self.assertEqual(200,self.client.get(f'/dvd-request/{request_id}').status_code)
        self.assert_integrity()


if __name__=='__main__':unittest.main()
