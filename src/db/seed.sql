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
        'Solo meals are not reimbursable -- put the weekend hours on your timesheet instead.'),
    -- The planted receipt mismatch: the folio totals $318 and the claim says $1,318. It is
    -- over travel's $500 auto-approve limit anyway, so the policy engine would have queued it
    -- regardless -- the flag is the only thing here the engine could not have found.
    (9, '69b7b41defaa1749ce05d8bf', 3,  131800, 'travel', 'Hilton',
        'Conference hotel, 2 nights', 'needs_approval', 'needs_approval', NULL, NULL, NULL);

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
    receipt_path = 'c8fb99c070f0b6751ea1defc020d8418acdcbb9573b0258d069a61b0fcbd1d2c.svg',
    receipt_filename = 'figma-invoice.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = 'c8fb99c070f0b6751ea1defc020d8418acdcbb9573b0258d069a61b0fcbd1d2c'
WHERE expense_id = 1;

UPDATE expenses SET
    receipt_path = '40147d97866e70ce026738816d867f68c6793bda431483549de1eb7134cef2eb.svg',
    receipt_filename = 'olive-garden-dinner.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = '40147d97866e70ce026738816d867f68c6793bda431483549de1eb7134cef2eb'
WHERE expense_id = 2;

UPDATE expenses SET
    receipt_path = '2cac6c659e2b4cd2c0a1da83edb8265fa5e0877cde7ff640ea961ea3d06bfd5e.svg',
    receipt_filename = 'apple-workstation.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = '2cac6c659e2b4cd2c0a1da83edb8265fa5e0877cde7ff640ea961ea3d06bfd5e'
WHERE expense_id = 3;

UPDATE expenses SET
    receipt_path = '53fbe6272dedc675f845c7b6c0435dbf4418653eb72f6bc4a587fbe78394b802.svg',
    receipt_filename = 'meta-ads-invoice.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = '53fbe6272dedc675f845c7b6c0435dbf4418653eb72f6bc4a587fbe78394b802'
WHERE expense_id = 4;

UPDATE expenses SET
    receipt_path = '3229c0fdafddd3fb0acb86dc6e97e23d539e296a5f811a6bf50a59213e156c0e.svg',
    receipt_filename = 'google-ads-invoice.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = '3229c0fdafddd3fb0acb86dc6e97e23d539e296a5f811a6bf50a59213e156c0e'
WHERE expense_id = 5;

UPDATE expenses SET
    receipt_path = '55c2dff47f71448a1ead333882b646606ff094ce4c2e0edabcc528f4dd004f4c.svg',
    receipt_filename = 'linkedin-ads-invoice.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = '55c2dff47f71448a1ead333882b646606ff094ce4c2e0edabcc528f4dd004f4c'
WHERE expense_id = 6;

UPDATE expenses SET
    receipt_path = 'd2977ca162764a790e1968bc103daa443da5c26054f3c72a4f37051358c7e5c4.svg',
    receipt_filename = 'delta-itinerary.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = 'd2977ca162764a790e1968bc103daa443da5c26054f3c72a4f37051358c7e5c4'
WHERE expense_id = 7;

UPDATE expenses SET
    receipt_path = 'ca0b59413c00a04f68c7a3d102178833bdfc43ab80568313ea23a1b463e8e7c9.svg',
    receipt_filename = 'sweetgreen-lunch.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = 'ca0b59413c00a04f68c7a3d102178833bdfc43ab80568313ea23a1b463e8e7c9'
WHERE expense_id = 8;

UPDATE expenses SET
    receipt_path = 'f9a6ba50b64d71dd496ca6660abb59c363966f8fff037394e172763e07fab9b4.svg',
    receipt_filename = 'hilton-folio.svg',
    receipt_mime = 'image/svg+xml',
    receipt_hash = 'f9a6ba50b64d71dd496ca6660abb59c363966f8fff037394e172763e07fab9b4'
WHERE expense_id = 9;

-- Every other seeded expense agrees with its receipt, so their checks are seeded clean. Only
-- expense 9 disagrees, and it is the one the manager should be able to see without a network.
UPDATE expenses SET receipt_check = 'clean' WHERE expense_id BETWEEN 1 AND 8;
UPDATE expenses SET receipt_check = 'flagged' WHERE expense_id = 9;

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
        '$16,000.00 is over the $2,500.00 auto-approve limit for marketing'),
    (8, 8, 'approval_threshold', 'warn',
        '$95.00 is over the $75.00 auto-approve limit for food'),
    (9, 9, 'approval_threshold', 'warn',
        '$1,318.00 is over the $500.00 auto-approve limit for travel');

-- ---------------------------------------------------------------------------
-- 9. What the receipt reader found (spec 8.1). Written out rather than left for the first
--    page load, so the demo shows a read receipt with no API key and no network -- and so
--    `init_db.py` and `seed.py` produce the same database.
--
--    One row per distinct receipt file, because that is what the cache is keyed by.
--    Regenerate alongside section 7 if a sample file changes: the hash is the filename.
-- ---------------------------------------------------------------------------
INSERT INTO receipt_readings (receipt_hash, status, merchant, total_cents, receipt_date,
                              line_items, model) VALUES
    ('c8fb99c070f0b6751ea1defc020d8418acdcbb9573b0258d069a61b0fcbd1d2c', 'read',
        'FIGMA INC', 8900, '2026-09-03', '[]', 'seed'),
    ('40147d97866e70ce026738816d867f68c6793bda431483549de1eb7134cef2eb', 'read',
        'OLIVE GARDEN', 18000, '2026-09-12', '[]', 'seed'),
    ('2cac6c659e2b4cd2c0a1da83edb8265fa5e0877cde7ff640ea961ea3d06bfd5e', 'read',
        'APPLE STORE', 620000, '2026-09-14', '[]', 'seed'),
    ('53fbe6272dedc675f845c7b6c0435dbf4418653eb72f6bc4a587fbe78394b802', 'read',
        'META PLATFORMS', 1800000, '2026-09-01', '[]', 'seed'),
    ('3229c0fdafddd3fb0acb86dc6e97e23d539e296a5f811a6bf50a59213e156c0e', 'read',
        'GOOGLE ADS', 1640000, '2026-09-01', '[]', 'seed'),
    ('55c2dff47f71448a1ead333882b646606ff094ce4c2e0edabcc528f4dd004f4c', 'read',
        'LINKEDIN CORP', 1600000, '2026-09-02', '[]', 'seed'),
    ('d2977ca162764a790e1968bc103daa443da5c26054f3c72a4f37051358c7e5c4', 'read',
        'DELTA AIR LINES', 42000, '2026-09-09', '[]', 'seed'),
    ('ca0b59413c00a04f68c7a3d102178833bdfc43ab80568313ea23a1b463e8e7c9', 'read',
        'SWEETGREEN', 9500, '2026-09-13', '[]', 'seed'),
    ('f9a6ba50b64d71dd496ca6660abb59c363966f8fff037394e172763e07fab9b4', 'read',
        'HILTON ATLANTA', 31800, '2026-09-14', '[]', 'seed');

-- ---------------------------------------------------------------------------
-- 10. The flag that reading produced. tests/test_seed_consistency.py recomputes it with
--     services.expense_flags.compare, so this row cannot drift from the rule that made it.
-- ---------------------------------------------------------------------------
INSERT INTO expense_flags (flag_id, expense_id, flag, message) VALUES
    (1, 9, 'amount_mismatch', 'Receipt totals $318.00 but $1,318.00 was claimed.');

-- ---------------------------------------------------------------------------
-- 11. Spend rules. Generated from policy.DEFAULT_POLICY_RULES so a fresh database behaves
--     exactly as the old in-code constant did. Finance edits these from /policies at runtime.
--     department_id NULL is the org-wide default; a row with a department is an override.
-- ---------------------------------------------------------------------------
INSERT INTO policy_rules
    (department_id, category, per_expense_limit_cents, auto_approve_limit_cents) VALUES
    (NULL, 'travel'          ,   300000,    50000),
    (NULL, 'food'            ,    15000,     7500),
    (NULL, 'client meals'    ,    50000,    10000),
    (NULL, 'software'        ,   250000,    25000),
    (NULL, 'equipment'       ,   500000,   100000),
    (NULL, 'marketing'       ,  1000000,   100000),
    (NULL, 'training'        ,   250000,    50000),
    (NULL, 'office supplies' ,    50000,    10000),
    (NULL, 'shipping'        ,    50000,    10000),
    (NULL, 'other'           ,    25000,    10000),
    (   1, 'software'        ,  1000000,   100000),
    (   2, 'marketing'       ,  2500000,   250000);
