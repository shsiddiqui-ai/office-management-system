"""Editable authority reporting. Callers own the transaction and connection."""

DEFAULT_PARENTS = {
    'Plant Manager': 'Senior Director',
    'Deputy Plant Manager': 'Plant Manager',
    'Associate Director': 'Senior Director',
    'HLAO': 'Senior Director',
    'Principal Administrator': 'Senior Director',
}
CURRENT_DIVISIONS = {
    'Senior Director': ['Account', 'Admin', 'RM', 'CS&C', 'QC', 'SCS', 'GSD', 'ESD'],
    'Plant Manager': ['Technical', 'HP & OS', 'QA', 'Store'],
    'Deputy Plant Manager': ['Chemical', 'ICD', 'Electrical', 'Mechanical', 'Operation'],
}


def upgrade_reporting(connection):
    """Add schema once; never replace existing division or employee history."""
    columns = {row[1] for row in connection.execute('PRAGMA table_info(posts)')}
    if 'is_reporting_authority' not in columns:
        connection.execute('ALTER TABLE posts ADD COLUMN is_reporting_authority INTEGER NOT NULL DEFAULT 0 CHECK (is_reporting_authority IN (0,1))')
    connection.execute('''CREATE TABLE IF NOT EXISTS organization_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        root_post_id INTEGER NOT NULL REFERENCES posts(id)
    )''')
    connection.execute('''CREATE TABLE IF NOT EXISTS post_reporting_assignments (
        id INTEGER PRIMARY KEY,
        post_id INTEGER NOT NULL REFERENCES posts(id),
        parent_post_id INTEGER NOT NULL REFERENCES posts(id),
        start_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        end_date TEXT,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
        CHECK (post_id != parent_post_id)
    )''')
    connection.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_parent_per_post
        ON post_reporting_assignments(post_id) WHERE is_active = 1''')
    connection.execute("""CREATE TABLE IF NOT EXISTS organizational_unit_parent_history (
        id INTEGER PRIMARY KEY,
        organizational_unit_id INTEGER NOT NULL REFERENCES organizational_units(id),
        parent_id INTEGER REFERENCES organizational_units(id),
        start_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        end_date TEXT,
        is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1))
    )""")
    connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_one_current_parent_per_unit
        ON organizational_unit_parent_history(organizational_unit_id) WHERE is_current=1""")
    connection.execute("""INSERT INTO organizational_unit_parent_history(organizational_unit_id,parent_id)
        SELECT u.id,u.parent_id FROM organizational_units u WHERE NOT EXISTS (
            SELECT 1 FROM organizational_unit_parent_history h WHERE h.organizational_unit_id=u.id AND h.is_current=1
        )""")
    if connection.execute('SELECT 1 FROM organization_settings WHERE id=1').fetchone():
        return
    names = ['Senior Director', *DEFAULT_PARENTS]
    for name in names:
        connection.execute('INSERT OR IGNORE INTO posts (name, max_active_holders) VALUES (?,1)', (name,))
        connection.execute('UPDATE posts SET is_reporting_authority=1 WHERE name=?', (name,))
    ids = {row[0]: row[1] for row in connection.execute('SELECT name,id FROM posts')}
    connection.execute('INSERT INTO organization_settings (id,root_post_id) VALUES (1,?)', (ids['Senior Director'],))
    for name, parent in DEFAULT_PARENTS.items():
        connection.execute('''INSERT INTO post_reporting_assignments(post_id,parent_post_id)
            VALUES (?,?)''', (ids[name], ids[parent]))


def root_post_id(connection):
    row = connection.execute('SELECT root_post_id FROM organization_settings WHERE id=1').fetchone()
    if not row:
        raise ValueError('Run flask --app app upgrade-reporting first.')
    return row[0]


def authority_posts(connection):
    return connection.execute('''SELECT id,name FROM posts
        WHERE is_active=1 AND is_reporting_authority=1 ORDER BY name COLLATE NOCASE''').fetchall()


def validate_authority(connection, post_id):
    if not connection.execute('''SELECT 1 FROM posts WHERE id=?
        AND is_active=1 AND is_reporting_authority=1''', (post_id,)).fetchone():
        raise ValueError('Select an active reporting authority.')


def set_post_parent(connection, post_id, parent_id):
    root = root_post_id(connection)
    if post_id == root:
        raise ValueError('Senior Director remains the top authority.')
    validate_authority(connection, post_id)
    validate_authority(connection, parent_id)
    parents = dict(connection.execute('''SELECT post_id,parent_post_id FROM post_reporting_assignments
        WHERE is_active=1''').fetchall())
    seen = {post_id}
    current = parent_id
    while True:
        if current in seen:
            raise ValueError('This reporting change would create a cycle.')
        seen.add(current)
        if current == root:
            break
        validate_authority(connection, current)
        if current not in parents:
            raise ValueError('The selected authority must have a reporting path to Senior Director.')
        current = parents[current]
    if parents.get(post_id) == parent_id:
        return False
    connection.execute('''UPDATE post_reporting_assignments SET is_active=0,
        end_date=COALESCE(end_date,CURRENT_TIMESTAMP) WHERE post_id=? AND is_active=1''', (post_id,))
    connection.execute('INSERT INTO post_reporting_assignments(post_id,parent_post_id) VALUES (?,?)', (post_id,parent_id))
    return True


def set_division_authority(connection, division_id, authority_id):
    validate_authority(connection, authority_id)
    unit = connection.execute('SELECT unit_type,is_active FROM organizational_units WHERE id=?', (division_id,)).fetchone()
    if not unit or unit[0] != 'Division' or unit[1] != 1:
        raise ValueError('Select an active Division.')
    # Every selectable authority must actually connect to the fixed root.
    root = root_post_id(connection)
    parents = dict(connection.execute('SELECT post_id,parent_post_id FROM post_reporting_assignments WHERE is_active=1').fetchall())
    cursor, seen = authority_id, set()
    while cursor != root:
        if cursor in seen or cursor not in parents:
            raise ValueError('The selected authority has no valid reporting path to Senior Director.')
        seen.add(cursor)
        validate_authority(connection, cursor)
        cursor = parents[cursor]
    current = connection.execute('''SELECT authority_post_id FROM division_reporting_assignments
        WHERE division_id=? AND is_active=1''', (division_id,)).fetchone()
    if current and current[0] == authority_id:
        return False
    connection.execute('''UPDATE division_reporting_assignments SET is_active=0,
        end_date=COALESCE(end_date,CURRENT_DATE) WHERE division_id=? AND is_active=1''', (division_id,))
    connection.execute('''INSERT INTO division_reporting_assignments(division_id,authority_post_id)
        VALUES (?,?)''', (division_id,authority_id))
    return True


def normalized_division_name(name):
    value = ''.join(name.casefold().split())
    if value.endswith('division'):
        value = value[:-8]
    return value


def current_structure_plan(connection):
    """Match confirmed labels only; ambiguity/inactive matches abort the whole plan."""
    units = connection.execute("SELECT id,name,is_active FROM organizational_units WHERE unit_type='Division'").fetchall()
    result = []
    for authority, names in CURRENT_DIVISIONS.items():
        for label in names:
            matches = [u for u in units if normalized_division_name(u[1]) == normalized_division_name(label)]
            if len(matches) > 1:
                raise ValueError(f'Ambiguous Division name: {label}. Rename duplicate units before applying.')
            if matches and not matches[0][2]:
                raise ValueError(f'Division {matches[0][1]} is inactive. Reactivate it before applying.')
            result.append((label,authority,matches[0][0] if matches else None))
    return result


def record_unit_parent(connection, unit_id, parent_id):
    current = connection.execute("""SELECT parent_id FROM organizational_unit_parent_history
        WHERE organizational_unit_id=? AND is_current=1""", (unit_id,)).fetchone()
    if current is not None and current[0] == parent_id:
        return False
    connection.execute("""UPDATE organizational_unit_parent_history SET is_current=0,
        end_date=COALESCE(end_date,CURRENT_TIMESTAMP) WHERE organizational_unit_id=? AND is_current=1""", (unit_id,))
    connection.execute("""INSERT INTO organizational_unit_parent_history(organizational_unit_id,parent_id)
        VALUES (?,?)""", (unit_id,parent_id))
    return True
