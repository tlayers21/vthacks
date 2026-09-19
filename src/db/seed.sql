-- Fake organization for local development and testing.
--
-- Run via `python db/init_db.py` (executes schema.sql then this file), or let
-- `python db/seed.py` build the same org through the live Nessie API instead.
--
-- The nessie_id values here are deterministic 24-char hex strings shaped like real
-- Nessie ObjectIds: sha1(name)[:24] for a customer, sha1('account:' + owner name)[:24]
-- for an account. They are stable across machines, so every teammate's database is
-- byte-identical and the ids can be regenerated from the names alone.
--
-- The cast is deliberately small -- one finance person, three managers, one employee each --
-- because the whole point of this org is that someone can hold it in their head while the
-- roles are switched in front of them.
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
--    1 Finance, 3 Managers (one per department), 3 Employees (one per manager)
-- ---------------------------------------------------------------------------
INSERT INTO customers (nessie_id, name, role, department_id) VALUES
    ('46dc699d55683c77fb2fdff9', 'Dana Whitfield',   'Finance',  NULL),
    ('5f421048bd4d8e3e90b9c5e0', 'Marcus Lee',       'Manager',  NULL),
    ('45e2abedb9e9ca8f43e3871b', 'Priya Raman',      'Manager',  NULL),
    ('7852de1729944ce87c3eb45c', 'Tomas Oliveira',   'Manager',  NULL),
    ('78d482edf6fb174320f74ace', 'Alex Chen',        'Employee', NULL),
    ('b53fcdaaca940b8401ce7e07', 'Sam Kowalski',     'Employee', NULL),
    ('69b7b41defaa1749ce05d8bf', 'Omar Haddad',      'Employee', NULL);

-- ---------------------------------------------------------------------------
-- 2. The organization itself: the corporation and each department, as their own
--    customers. Not people -- these never log in.
-- ---------------------------------------------------------------------------
INSERT INTO customers (nessie_id, name, role, department_id) VALUES
    ('22288ec84bcbb222845a5627', 'Nessence Corporation',   'Finance', NULL),
    ('12e0bcda330db3a05f397dbd', 'Engineering Department', 'Finance', NULL),
    ('99345ed6ec37b43539f62a95', 'Marketing Department',   'Finance', NULL),
    ('696a6805e67902eb87dc6966', 'Sales Department',       'Finance', NULL);

-- ---------------------------------------------------------------------------
-- 3. Accounts -- exactly one per customer.
-- ---------------------------------------------------------------------------

-- Personal accounts
INSERT INTO accounts (nessie_id, customer_id) VALUES
    ('e37b75ce4f86d8f21f1f67ae', '46dc699d55683c77fb2fdff9'),  -- Dana Whitfield
    ('a326388b37fa1ffde5b451be', '5f421048bd4d8e3e90b9c5e0'),  -- Marcus Lee
    ('503b369cdaf6997c29ef1f85', '45e2abedb9e9ca8f43e3871b'),  -- Priya Raman
    ('b1902b7859e2357efa1ca098', '7852de1729944ce87c3eb45c'),  -- Tomas Oliveira
    ('3bc3c624c896b7bfa83308cc', '78d482edf6fb174320f74ace'),  -- Alex Chen
    ('5f217905496d403ed2847e16', 'b53fcdaaca940b8401ce7e07'),  -- Sam Kowalski
    ('c5d78435f6b94c7ee8dce4b5', '69b7b41defaa1749ce05d8bf');  -- Omar Haddad

-- Corporate and department accounts
INSERT INTO accounts (nessie_id, customer_id) VALUES
    ('5f5729d5d8ba611d3de452ba', '22288ec84bcbb222845a5627'),  -- Nessence Corporation
    ('4b8c7b36165b25ee05b00115', '12e0bcda330db3a05f397dbd'),  -- Engineering Department
    ('777bb6be4c3aa0dfaa13cc85', '99345ed6ec37b43539f62a95'),  -- Marketing Department
    ('67ed89ac0858330ac417f07d', '696a6805e67902eb87dc6966');  -- Sales Department

-- ---------------------------------------------------------------------------
-- 4. Departments. Explicit department_id keeps the ids stable for tests and for the
--    UPDATE pass below. Budgets are monthly, in cents.
--
--    Ids 1 and 2 are load-bearing: policy/rules.py keys its only two overrides on
--    Engineering-software and Marketing-marketing.
-- ---------------------------------------------------------------------------
INSERT INTO departments (department_id, name, monthly_budget_cents, account_id) VALUES
    (1, 'Engineering', 12000000, '4b8c7b36165b25ee05b00115'),  -- $120,000
    (2, 'Marketing',    4500000, '777bb6be4c3aa0dfaa13cc85'),  --  $45,000
    (3, 'Sales',        8000000, '67ed89ac0858330ac417f07d');  --  $80,000

-- ---------------------------------------------------------------------------
-- 5. Attach people to departments. Dana stays unassigned -- finance sees every
--    department, so belonging to one would be misleading. The corporation and the
--    department customers stay unassigned too: a department does not belong to itself.
-- ---------------------------------------------------------------------------
UPDATE customers SET department_id = 1 WHERE nessie_id IN (
    '5f421048bd4d8e3e90b9c5e0',  -- Marcus Lee      (Manager)
    '78d482edf6fb174320f74ace'   -- Alex Chen       (Employee)
);
UPDATE customers SET department_id = 2 WHERE nessie_id IN (
    '45e2abedb9e9ca8f43e3871b',  -- Priya Raman     (Manager)
    'b53fcdaaca940b8401ce7e07'   -- Sam Kowalski    (Employee)
);
UPDATE customers SET department_id = 3 WHERE nessie_id IN (
    '7852de1729944ce87c3eb45c',  -- Tomas Oliveira  (Manager)
    '69b7b41defaa1749ce05d8bf'   -- Omar Haddad     (Employee)
);

-- ---------------------------------------------------------------------------
-- 6. Funding requests. Nothing is seeded Approved on purpose: an approved request has
--    already raised its department's budget and moved corporate money, and replaying that
--    at startup is exactly the double-count services/startup.py works to avoid. Seeding
--    only Pending and Rejected keeps the arithmetic honest without a special case.
--
--    Marketing's pending request is the planted demo -- it is what unblocks the manager
--    whose department is over budget.
-- ---------------------------------------------------------------------------
INSERT INTO budget_requests (request_id, customer_id, department_id, amount_cents, reason,
                             status, decided_by, decided_at, decision_note) VALUES
    (1, '45e2abedb9e9ca8f43e3871b', 2, 2000000,
        'Q3 campaigns ran long and the recruiting push is still unpaid.',
        'Pending', NULL, NULL, NULL),
    (2, '5f421048bd4d8e3e90b9c5e0', 1,  750000,
        'Two more cloud environments for the launch.',
        'Pending', NULL, NULL, NULL),
    (3, '7852de1729944ce87c3eb45c', 3, 1200000,
        'Extra travel for the west coast accounts.',
        'Rejected', '46dc699d55683c77fb2fdff9', CURRENT_TIMESTAMP,
        'Sales is at 1% of budget this month -- come back when it is actually tight.');

-- ---------------------------------------------------------------------------
-- 7. Expenses -- one per policy outcome, so every branch of the engine has a row to show.
--
-- submitted_at is deliberately omitted so it defaults to CURRENT_TIMESTAMP. The budget check
-- only counts the current month, so a hardcoded date would make Marketing's over-budget demo
-- quietly stop working on the first of next month.
--
-- Every row's amount must stay consistent with the rule that would have produced its
-- policy_decision (see policy/rules.py). tests/test_seed_consistency.py enforces that.
--
-- Note row 3: the engine blocked it, but nothing is refused by the machine any more, so it
-- sits in the manager's queue wearing its block. Only row 8 is 'rejected', and a human did it.
-- ---------------------------------------------------------------------------
INSERT INTO expenses (expense_id, customer_id, department_id, amount_cents, category,
                      merchant, description, status, policy_decision,
                      decided_by, decided_at, decision_note) VALUES
    -- Under Engineering's $1,000 software auto-approve limit: paid with no human involved
    (1, '78d482edf6fb174320f74ace', 1,    8900, 'software', 'Figma',
        'Design seat renewal', 'paid', 'auto_approved', NULL, NULL, NULL),
    -- The planted team dinner: over the $100 client-meals auto-approve limit, under the $500 cap
    (2, '69b7b41defaa1749ce05d8bf', 3,   18000, 'client meals', 'Olive Garden',
        'Team dinner after the Q3 close', 'needs_approval', 'needs_approval', NULL, NULL, NULL),
    -- Over the $5,000 equipment cap: the engine says blocked, the manager still decides
    (3, '78d482edf6fb174320f74ace', 1,  620000, 'equipment', 'Apple',
        'Workstation refresh', 'needs_approval', 'blocked', NULL, NULL, NULL),
    -- Rows 4-6 put Marketing at $50,400 against a $45,000 budget: 112%.
    -- Each sits under Marketing's $25,000 cap, so only the budget rule escalates the next one.
    (4, 'b53fcdaaca940b8401ce7e07', 2, 1800000, 'marketing', 'Meta Ads',
        'Q3 retargeting campaign', 'paid', 'needs_approval', NULL, NULL, NULL),
    (5, 'b53fcdaaca940b8401ce7e07', 2, 1640000, 'marketing', 'Google Ads',
        'Search campaign, product launch', 'approved', 'needs_approval', NULL, NULL, NULL),
    (6, 'b53fcdaaca940b8401ce7e07', 2, 1600000, 'marketing', 'LinkedIn Ads',
        'Recruiting campaign', 'needs_approval', 'needs_approval', NULL, NULL, NULL),
    -- Auto-approved but the transfer failed, so retry-payout has something to act on
    (7, '69b7b41defaa1749ce05d8bf', 3,   42000, 'travel', 'Delta',
        'Client site visit, ATL-SFO', 'payout_failed', 'auto_approved', NULL, NULL, NULL),
    -- The one rejection in the seed, and a human made it -- with a reason the submitter can read
    (8, '69b7b41defaa1749ce05d8bf', 3,    9500, 'food', 'Sweetgreen',
        'Lunch while working the weekend', 'rejected', 'needs_approval',
        '7852de1729944ce87c3eb45c', CURRENT_TIMESTAMP,
        'Solo meals are not reimbursable -- put the weekend hours on your timesheet instead.');

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
        '$16,000.00 is over the $2,500.00 auto-approve limit for marketing'),
    (8, 8, 'approval_threshold', 'warn',
        '$95.00 is over the $75.00 auto-approve limit for food');
