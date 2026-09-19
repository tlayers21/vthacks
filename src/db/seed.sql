-- Fake organization for local development and testing.
--
-- Run via `python db/init_db.py` (executes schema.sql then this file), or let
-- `python db/seed.py` build the same org through the live Nessie API instead.
--
-- The nessie_id values here are deterministic 24-char hex strings shaped like real
-- Nessie ObjectIds, derived from sha1(name)[:24]. They are stable across machines, so
-- tests can hardcode them and every teammate's database is byte-identical.
--
-- The corporation and each department are their own customers, holding the accounts
-- money moves out of, rather than accounts hung off a finance employee. Money moves
-- corporate -> department -> employee. They carry the 'Finance' role because that is
-- functionally what they are, and they never log in. Every customer owns exactly one
-- account, so an account's purpose is always clear from its owner.
--
-- INSERT ORDER IS LOAD-BEARING. The foreign keys form a cycle:
--     customers.department_id -> departments.department_id
--     departments.account_id  -> accounts.nessie_id
--     accounts.customer_id    -> customers.nessie_id
-- We break it by inserting customers with a NULL department_id first, then accounts,
-- then departments, and finally attaching customers to departments in an UPDATE pass.
-- Do not reorder these blocks.

-- ---------------------------------------------------------------------------
-- 1. People (department_id attached in step 5)
--    1 Finance, 4 Managers (one per department), 8 Employees (two per department)
-- ---------------------------------------------------------------------------
INSERT INTO customers (nessie_id, name, role, department_id) VALUES
    ('698fec9d4a7cd9beaf936af0', 'Dana Whitfield',   'Finance',  NULL),
    ('956eed2ecefb9dcafff1c571', 'Marcus Lee',       'Manager',  NULL),
    ('6aee286af0ba7a046619ddf2', 'Priya Raman',      'Manager',  NULL),
    ('2c15cdac1210cee43aafc02a', 'Tomas Oliveira',   'Manager',  NULL),
    ('ab4e1e4d02b9dd22940571cd', 'Helen Osei',       'Manager',  NULL),
    ('6ca50b885e4037e80db44533', 'Alex Chen',        'Employee', NULL),
    ('091352ab41e9d1cf44cb8431', 'Ruth Delgado',     'Employee', NULL),
    ('77eae678aa54d96d23014d38', 'Sam Kowalski',     'Employee', NULL),
    ('25ee9a33b129edbe3a53de6e', 'Nia Brooks',       'Employee', NULL),
    ('418d13ad70fa7ea3d5e7ac44', 'Omar Haddad',      'Employee', NULL),
    ('34b149705a405d7a551ba57b', 'Leah Fitzgerald',  'Employee', NULL),
    ('88335974e504ae746e4739be', 'Victor Nguyen',    'Employee', NULL),
    ('ad3d81b993865c367d7a3276', 'Grace Abbott',     'Employee', NULL);

-- ---------------------------------------------------------------------------
-- 2. The organization itself: the corporation and each department, as their own
--    customers. Not people -- these never log in.
-- ---------------------------------------------------------------------------
INSERT INTO customers (nessie_id, name, role, department_id) VALUES
    ('e4be2cad196e442c0bdbadec', 'Acme Corporation',       'Finance', NULL),
    ('9c9ab00f8ff0d0bd0767295f', 'Engineering Department', 'Finance', NULL),
    ('450ab5782a5555e531875478', 'Marketing Department',   'Finance', NULL),
    ('a69bd436eec25cd2151368b7', 'Sales Department',       'Finance', NULL),
    ('4504875b8392bd29cd11a041', 'Operations Department',  'Finance', NULL);

-- ---------------------------------------------------------------------------
-- 3. Accounts -- exactly one per customer.
-- ---------------------------------------------------------------------------

-- Personal accounts
INSERT INTO accounts (nessie_id, customer_id) VALUES
    ('4027109f5fb04b82c41e57dd', '698fec9d4a7cd9beaf936af0'),  -- Dana Whitfield
    ('a03f7850dcbef86101926901', '956eed2ecefb9dcafff1c571'),  -- Marcus Lee
    ('5c11cf855c160a73d5e052ba', '6aee286af0ba7a046619ddf2'),  -- Priya Raman
    ('3686a745ac84e7133f560365', '2c15cdac1210cee43aafc02a'),  -- Tomas Oliveira
    ('a0d42a323d5b0bbca5a73221', 'ab4e1e4d02b9dd22940571cd'),  -- Helen Osei
    ('038090567374c396c69c0193', '6ca50b885e4037e80db44533'),  -- Alex Chen
    ('526c6f4cff32d1c049b4aaac', '091352ab41e9d1cf44cb8431'),  -- Ruth Delgado
    ('e68adf57ca189113f6ff4a1b', '77eae678aa54d96d23014d38'),  -- Sam Kowalski
    ('ba3dae59eaea6e448b19a8bc', '25ee9a33b129edbe3a53de6e'),  -- Nia Brooks
    ('1bc579861a7a3bbbb21c2bfd', '418d13ad70fa7ea3d5e7ac44'),  -- Omar Haddad
    ('79831998370561564d88eb71', '34b149705a405d7a551ba57b'),  -- Leah Fitzgerald
    ('dd9a27972975211627f47d69', '88335974e504ae746e4739be'),  -- Victor Nguyen
    ('24610ab584948472fff60760', 'ad3d81b993865c367d7a3276');  -- Grace Abbott

-- Corporate and department accounts
INSERT INTO accounts (nessie_id, customer_id) VALUES
    ('f85d0dbca4483d8f8b6f7c55', 'e4be2cad196e442c0bdbadec'),  -- Acme Corporation
    ('c1c87dca14ac5d687df3579e', '9c9ab00f8ff0d0bd0767295f'),  -- Engineering Department
    ('0cda0468250c8ede7a03fa51', '450ab5782a5555e531875478'),  -- Marketing Department
    ('236aeb47ed0cfafb89448d04', 'a69bd436eec25cd2151368b7'),  -- Sales Department
    ('6b1dd319e41036d920bf747e', '4504875b8392bd29cd11a041');  -- Operations Department

-- ---------------------------------------------------------------------------
-- 4. Departments. Explicit department_id keeps the ids stable for tests and for the
--    UPDATE pass below. Budgets are monthly, in cents.
-- ---------------------------------------------------------------------------
INSERT INTO departments (department_id, name, monthly_budget_cents, account_id) VALUES
    (1, 'Engineering', 12000000, 'c1c87dca14ac5d687df3579e'),  -- $120,000
    (2, 'Marketing',    4500000, '0cda0468250c8ede7a03fa51'),  --  $45,000
    (3, 'Sales',        8000000, '236aeb47ed0cfafb89448d04'),  --  $80,000
    (4, 'Operations',   3500000, '6b1dd319e41036d920bf747e');  --  $35,000

-- ---------------------------------------------------------------------------
-- 5. Attach people to departments. Dana stays unassigned -- finance sees every
--    department, so belonging to one would be misleading. The corporation and the
--    department customers stay unassigned too: a department does not belong to itself.
-- ---------------------------------------------------------------------------
UPDATE customers SET department_id = 1 WHERE nessie_id IN (
    '956eed2ecefb9dcafff1c571',  -- Marcus Lee      (Manager)
    '6ca50b885e4037e80db44533',  -- Alex Chen       (Employee)
    '091352ab41e9d1cf44cb8431'   -- Ruth Delgado    (Employee)
);
UPDATE customers SET department_id = 2 WHERE nessie_id IN (
    '6aee286af0ba7a046619ddf2',  -- Priya Raman     (Manager)
    '77eae678aa54d96d23014d38',  -- Sam Kowalski    (Employee)
    '25ee9a33b129edbe3a53de6e'   -- Nia Brooks      (Employee)
);
UPDATE customers SET department_id = 3 WHERE nessie_id IN (
    '2c15cdac1210cee43aafc02a',  -- Tomas Oliveira  (Manager)
    '418d13ad70fa7ea3d5e7ac44',  -- Omar Haddad     (Employee)
    '34b149705a405d7a551ba57b'   -- Leah Fitzgerald (Employee)
);
UPDATE customers SET department_id = 4 WHERE nessie_id IN (
    'ab4e1e4d02b9dd22940571cd',  -- Helen Osei      (Manager)
    '88335974e504ae746e4739be',  -- Victor Nguyen   (Employee)
    'ad3d81b993865c367d7a3276'   -- Grace Abbott    (Employee)
);

-- ---------------------------------------------------------------------------
-- 6. Budget requests -- all three statuses represented so the finance decision queue,
--    the filters, and the history views all have rows to show. Marketing's pending
--    request is the planted demo scenario (spec section 11).
-- ---------------------------------------------------------------------------
INSERT INTO budget_requests (request_id, customer_id, amount_cents, status) VALUES
    (1, '6aee286af0ba7a046619ddf2', 1800000, 'Pending'),   -- Marketing,   $18,000
    (2, '956eed2ecefb9dcafff1c571',  750000, 'Pending'),   -- Engineering,  $7,500
    (3, '2c15cdac1210cee43aafc02a', 1200000, 'Approved'),  -- Sales,       $12,000
    (4, 'ab4e1e4d02b9dd22940571cd',  500000, 'Rejected');  -- Operations,   $5,000

-- ---------------------------------------------------------------------------
-- 7. Expenses -- one per policy outcome, so every branch of the engine has a row to show.
--
-- submitted_at is deliberately omitted so it defaults to CURRENT_TIMESTAMP. The budget check
-- only counts the current month, so a hardcoded date would make Marketing's over-budget demo
-- quietly stop working on the first of next month.
--
-- Every row's amount must stay consistent with the rule that would have produced its
-- policy_decision (see policy/rules.py). tests/test_seed_consistency.py enforces that.
-- ---------------------------------------------------------------------------
INSERT INTO expenses (expense_id, customer_id, department_id, amount_cents, category,
                      merchant, description, status, policy_decision) VALUES
    -- Under Engineering's $1,000 software auto-approve limit: paid with no human involved
    (1, '6ca50b885e4037e80db44533', 1,    8900, 'software', 'Figma',
        'Design seat renewal', 'paid', 'auto_approved'),
    -- The planted team dinner (spec 11): over the $100 client-meals auto-approve limit,
    -- under the $500 cap
    (2, '418d13ad70fa7ea3d5e7ac44', 3,   18000, 'client meals', 'Olive Garden',
        'Team dinner after the Q3 close', 'needs_approval', 'needs_approval'),
    -- Over the $5,000 equipment cap, so the engine refused it outright
    (3, 'ad3d81b993865c367d7a3276', 4,  620000, 'equipment', 'Apple',
        'Workstation refresh', 'rejected', 'blocked'),
    -- Rows 4-6 put Marketing at $50,400 against a $45,000 budget: 112% (spec 11).
    -- Each sits under Marketing's $25,000 cap, so only the budget rule escalates the next one.
    (4, '77eae678aa54d96d23014d38', 2, 1800000, 'marketing', 'Meta Ads',
        'Q3 retargeting campaign', 'paid', 'needs_approval'),
    (5, '25ee9a33b129edbe3a53de6e', 2, 1640000, 'marketing', 'Google Ads',
        'Search campaign, product launch', 'approved', 'needs_approval'),
    (6, '77eae678aa54d96d23014d38', 2, 1600000, 'marketing', 'LinkedIn Ads',
        'Recruiting campaign', 'needs_approval', 'needs_approval'),
    -- Auto-approved but the transfer failed, so retry-payout has something to act on
    (7, '34b149705a405d7a551ba57b', 3,   42000, 'travel', 'Delta',
        'Client site visit, ATL-SFO', 'payout_failed', 'auto_approved');

-- Receipts. Every seeded expense is over the $25 threshold, so under spec 7.2 each one needs
-- a receipt or the engine would block it -- a row claiming 'auto_approved' or 'needs_approval'
-- with no receipt would be asserting a verdict the engine would never have given it.
-- Expense 3 still ends up blocked, but by the per-expense cap alone, which is the point of it.
--
-- Filenames are sha256(file) + extension, exactly how uploads are stored.
-- services.receipts.install_samples() copies data/sample_receipts/ into the receipts
-- directory; init_db.py and seed.py both call it, so the files exist before anything
-- renders them. Regenerate this block if a sample file changes -- the hash is the filename.

UPDATE expenses SET
    receipt_path = '15627a9de8ac30984df88ff2f91062b9ff9d9dc21a8ecaab3e6ecaf7516a9ca0.svg',
    receipt_filename = 'figma-invoice.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = '15627a9de8ac30984df88ff2f91062b9ff9d9dc21a8ecaab3e6ecaf7516a9ca0'
WHERE expense_id = 1;

UPDATE expenses SET
    receipt_path = 'b893ad3dd5329c0c20f9ffb0ee00fc056a8a3c2246f7138e44a11c2ca96f4c04.svg',
    receipt_filename = 'olive-garden-dinner.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = 'b893ad3dd5329c0c20f9ffb0ee00fc056a8a3c2246f7138e44a11c2ca96f4c04'
WHERE expense_id = 2;

UPDATE expenses SET
    receipt_path = '6328d839d289120d284590f292959b4af1498b73ff39684c6ea647aae028dcbe.svg',
    receipt_filename = 'apple-workstation.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = '6328d839d289120d284590f292959b4af1498b73ff39684c6ea647aae028dcbe'
WHERE expense_id = 3;

UPDATE expenses SET
    receipt_path = 'ae158159379688b04bb6b6817fd561225f9b8c296037b1affd995b4af34fb829.svg',
    receipt_filename = 'meta-ads-invoice.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = 'ae158159379688b04bb6b6817fd561225f9b8c296037b1affd995b4af34fb829'
WHERE expense_id = 4;

UPDATE expenses SET
    receipt_path = '5bfbcb4c3ae327068b13125f6a0ff21364dbd902e15ff57d5cc6454d88d76e44.svg',
    receipt_filename = 'google-ads-invoice.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = '5bfbcb4c3ae327068b13125f6a0ff21364dbd902e15ff57d5cc6454d88d76e44'
WHERE expense_id = 5;

UPDATE expenses SET
    receipt_path = '637e32afda0507b708e145cb477343affd1a32de02abed532c6de3249e90026d.svg',
    receipt_filename = 'linkedin-ads-invoice.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = '637e32afda0507b708e145cb477343affd1a32de02abed532c6de3249e90026d'
WHERE expense_id = 6;

UPDATE expenses SET
    receipt_path = '8b5ce925236e37440176bfcb932115626eaff57e87408c705d6d3747dae6d3d7.svg',
    receipt_filename = 'delta-itinerary.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = '8b5ce925236e37440176bfcb932115626eaff57e87408c705d6d3747dae6d3d7'
WHERE expense_id = 7;

-- ---------------------------------------------------------------------------
-- 8. The violations those expenses recorded at submission time. Written out rather than
--    recomputed so the demo shows exactly what the engine said on the day.
-- ---------------------------------------------------------------------------
INSERT INTO expense_violations (violation_id, expense_id, rule, severity, message) VALUES
    (1, 2, 'approval_threshold', 'warn',
        '$180.00 is over the $100.00 auto-approve limit for client meals'),
    (2, 3, 'per_expense_cap', 'block',
        '$6,200.00 is over the $5,000.00 limit for equipment'),
    (3, 3, 'approval_threshold', 'warn',
        '$6,200.00 is over the $1,000.00 auto-approve limit for equipment'),
    (4, 4, 'approval_threshold', 'warn',
        '$18,000.00 is over the $2,500.00 auto-approve limit for marketing'),
    (5, 5, 'approval_threshold', 'warn',
        '$16,400.00 is over the $2,500.00 auto-approve limit for marketing'),
    (6, 6, 'department_budget', 'warn',
        '$16,000.00 exceeds the $10,600.00 left of this month''s $45,000.00 budget'),
    (7, 6, 'approval_threshold', 'warn',
        '$16,000.00 is over the $2,500.00 auto-approve limit for marketing');
