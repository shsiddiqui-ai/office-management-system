# Office Management System — Final Project Rules

## 1. Project Overview

This is a Flask-based Office Management System for an offline office network.

The first major module is CD/DVD Management. Future modules may include HR,
ID Card Management and other office functions.

The system must preserve historical records and provide a professional UI.

---

## 2. Organizational Authority Hierarchy

The authority hierarchy is:

1. Senior Director (SD)
2. Plant Manager (PM)
3. Deputy Plant Manager (DPM)

Senior Director is the highest authority.

Plant Manager reports to Senior Director.

Deputy Plant Manager reports to Plant Manager.

Divisions are not permanently hardcoded under these authorities.

An administrator can change a Division's reporting authority to:

- Senior Director
- Plant Manager
- Deputy Plant Manager

Example:

A Division currently reporting to Plant Manager may later be moved directly
under Senior Director.

Every reporting change must preserve history with effective start and end dates.

A Division reports to an authority post, not to an Office unit or employee name.

---

## 3. Offices

The following are organizational units used for employee placement:

- Senior Director Office
- Plant Manager Office
- Deputy Plant Manager Office

These Offices are not controlling authorities.

They are units for employees such as:

- Correspondence staff
- Assistants
- Attendants
- Administrative staff

Divisions must not be placed underneath these Office units.

---

## 4. Divisions

Divisions must be dynamically manageable from the Admin Dashboard.

Admin can:

- Add a Division
- Rename a Division
- Change its reporting authority
- Deactivate or reactivate it
- View its history

Divisions must not be permanently deleted when they have historical data.

Division names must be unique without considering capitalization or extra spaces.

Example:

`IT Division`, `it division` and ` IT  Division ` are the same name.

When a Division is renamed, current screens show the new name.

Historical DVD requests must continue showing the Division name that existed
when the request was submitted.

When a Division is deactivated:

- Employees remain in the system.
- Their current Division becomes unassigned.
- Their current Section also becomes unassigned.
- They appear as "Without Division".
- Admin can later assign them to any active Division and optional Section.

---

## 5. Sections

A Section is a formal child unit of a Division.

Example:

Division:

- Cyber Security & Communication

Sections:

- Cyber Security & IT
- Communication

A Division may have:

- No Sections
- One Section
- Multiple Sections

It is not compulsory for every Division to have Sections or Heads.

Employees may report directly to the Division Manager without a Section.

Admin can:

- Add a Section
- Rename a Section
- Deactivate or reactivate a Section
- Transfer employees between Sections

A Section name must be unique inside its own Division without considering
capitalization or extra spaces.

The same Section name may exist in two different Divisions.

When a Section is deactivated:

- Its employees remain in the same Division.
- Their Section becomes unassigned.
- They report directly to their Division Manager.
- Admin can assign them to another Section of the same Division.
- Admin can also perform a full Division transfer.

---

## 6. Employee Location Rules

Every employee can have:

- Maximum one active Division or Office
- Maximum one active Section
- A Section is optional

If an employee has a Section, that Section must belong to the employee's
current Division.

An employee cannot simultaneously belong to two Divisions.

An employee cannot simultaneously have two home Sections.

When an employee changes Division:

- The previous Division assignment ends.
- The previous Section assignment ends.
- A new Division is assigned.
- A valid Section may optionally be assigned.

When an employee changes Section within the same Division:

- The Division remains unchanged.
- The previous Section assignment ends.
- The new Section assignment begins.

Assignment history must be preserved.

---

## 7. PIN Rules

Employee PIN:

- Must contain digits only
- Has no fixed length
- May start with zero
- Must be stored as TEXT
- Must always be unique

PIN can be edited.

A PIN cannot be changed to another employee's existing PIN.

---

## 8. Designations

Designations are employee job titles.

Examples:

- Chief Engineer
- Deputy Chief Engineer
- Senior Engineer
- Scientific Assistant
- Account Officer
- Admin Officer
- Principal Account Officer
- Senior Account Officer
- Principal Admin Officer
- Senior Admin Officer

Designations are not organizational posts.

Designation names must be unique without considering capitalization or
extra spaces.

An employee has only one current active designation.

Designation changes should preserve history wherever required.

Designations in use should be deactivated instead of permanently deleted.

---

## 9. Organizational Posts

Valid posts are:

- Senior Director
- Plant Manager
- Deputy Plant Manager
- Manager
- Acting Manager
- Head
- HLAO
- Principal Administrator

Account Officer and Admin Officer are designations, not posts.

Globally single-holder posts are:

- Senior Director
- Plant Manager
- Deputy Plant Manager
- HLAO
- Principal Administrator

Manager, Acting Manager and Head may have different holders in different
Divisions or Sections.

Post and responsibility history must be preserved.

---

## 10. Manager and Acting Manager

Every Division can have one current managerial incharge:

- Manager
- Acting Manager
- Vacant temporarily

Manager and Acting Manager have the same authority for that Division.

A Manager has one primary Division.

The same Manager may receive Acting Manager responsibility for multiple
additional Divisions.

This must not create duplicate active employee posts.

The employee remains Manager of the primary Division, while responsibility
links record Acting Manager capacity for additional Divisions.

If a Head becomes Acting Manager:

- The active Head responsibility ends.
- Acting Manager responsibility begins.
- The change history is preserved.

When permanent authority is received, Acting Manager can be converted to
Manager while preserving history.

---

## 11. Heads

Head is an organizational post connected to a Section.

One Section can have only one current active Head.

One employee may be Head of multiple Sections only when all those Sections
belong to the employee's home Division.

An employee's home Section remains zero or one.

Additional Head responsibilities do not make the employee a normal member
of multiple Sections.

A Manager is above Heads.

A Head must never be made the controlling authority above a Manager.

A Division can exist without any Head or Section.

---

## 12. Historical Snapshots

Transactions such as DVD requests must store submission-time snapshots.

Required snapshots include, where applicable:

- Employee PIN
- Employee name
- Designation
- Division or Office name
- Section name
- Extension number
- Relevant post or responsibility

If a Division, Section, employee, designation or PIN is changed later,
previous DVD requests must continue showing the original submitted values.

---

## 13. Employee Screens

The Employee List should remain concise and show:

- PIN
- Employee Name
- Designation
- Division or Office
- Section
- Post
- Status

The Employee Profile should show the complete reporting chain.

Example:

Employee → Section → Division → DPM → PM → SD

If the Division reports directly to SD, the profile should show that actual
chain instead.

A separate Organization Hierarchy page should also be available.

---

## 14. Access and Permissions

Super Admin:

- Full system access
- Manages administrators and permissions
- At least one Super Admin must always remain active

Admin:

- Manages employees, designations, Divisions, Offices, Sections and hierarchy
- Can control which roles may view or manage different information

Manager or Acting Manager:

- Can access assigned Divisions and relevant approval work

Head:

- Can access assigned Sections and relevant approval work

Normal Employee:

- Can view their own profile
- Can view their reporting chain
- Can create and track their own requests

Cyber Security and Technical Incharge:

- Can access only the information required for their work and request workflow

---

## 15. CD/DVD Categories

The six categories are:

1. Internal
2. Internet
3. External
4. Vendor
5. Outward
6. Permanent

Permanent is a complete category, not merely an option inside another category.

---

## 16. CD/DVD Digital Workflow

Digital workflow:

1. Requesting employee submits request
2. Employee's Division Manager approves or rejects
3. Cyber Security approves or rejects
4. Technical Incharge processes and issues the DVD

Senior Director does not provide digital approval.

Senior Director signs the printed physical form only.

A requester cannot approve their own request.

Special self-approval routing will be finalized after the organizational
foundation is completed.

---

## 17. CD/DVD Physical Workflow

Physical signatures and processing:

1. Indentor / Requester
2. Division Manager
3. Cyber Security remarks and approval
4. Senior Director physical signature
5. Technical Incharge verifies and issues DVD

Technical Incharge records:

- DVD issue number
- Issued-by employee
- IT signature or stamp
- Operational status

---

## 18. DVD Lifecycle

Internal and Internet:

- Normal use → Shred → Close
- Faulty → Shred → Replacement with a new DVD number

External and Vendor:

- Normal → Close
- Faulty → Close
- No automatic replacement

Outward:

- Goes outside the organization
- Shredding is not applicable
- Close after completion

Permanent:

- Remains in requester or unit custody
- Is not normally shredded
- Faulty handling will be finalized later

---

## 19. Database and Deletion Policy

Important operational data must not be hard-deleted.

Use:

- Active and inactive status
- Start date
- End date
- Historical assignment tables
- Submission-time snapshots

The local SQLite database and backups must never be uploaded to public GitHub.

Ignored items include:

- `database/*.db`
- Database journal, WAL and SHM files
- Database backups
- `.env`
- `venv`
- `__pycache__`

---

## 20. Current Development Order

Development should proceed in this order:

1. Finalize organization database structure
2. Add Division, Office and Section support
3. Add dynamic authority reporting and history
4. Update employee location and transfer system
5. Implement Manager, Acting Manager and Head responsibilities
6. Add organization hierarchy page
7. Add authentication and permission system
8. Update DVD requests with historical snapshots
9. Implement approval workflow
10. Implement issue, faulty, shred, replacement and closure processes
11. Complete reports and professional UI