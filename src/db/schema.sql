-- Nessie ids are 24-char hex ObjectIds (e.g. 57cf75cea73e494d8675ec49), so every
-- nessie_id column is TEXT. Money is stored as INTEGER cents, never DECIMAL/REAL --
-- SQLite gives DECIMAL a NUMERIC affinity that round-trips through a float.

CREATE TABLE customers (
    nessie_id TEXT NOT NULL UNIQUE PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('Finance', 'Manager', 'Employee')),
    department_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (department_id) REFERENCES departments(department_id)
);

CREATE TABLE accounts (
    nessie_id TEXT NOT NULL UNIQUE PRIMARY KEY,
    customer_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(nessie_id)
);

CREATE TABLE departments (
    department_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL UNIQUE,
    monthly_budget_cents INTEGER NOT NULL DEFAULT 0 CHECK (monthly_budget_cents >= 0),
    -- Finance can edit the budget directly, so the change carries an author for the same
    -- reason policy_rules does: a ceiling nobody can attribute is not a control
    budget_updated_by TEXT REFERENCES customers(nessie_id),
    budget_updated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    account_id TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(nessie_id)
);

-- A manager asking finance for more department money. department_id is stored rather than read
-- off the requester, for the same reason expenses denormalize it: the money was asked for by a
-- department, not by wherever that manager sits later.
CREATE TABLE budget_requests (
    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    department_id INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    reason TEXT,
    status TEXT NOT NULL CHECK (status IN ('Pending', 'Approved', 'Rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decided_by TEXT,
    decided_at TIMESTAMP,
    decision_note TEXT,
    -- Same idempotency guard as expenses: one approval can only ever fund one transfer
    nessie_transfer_id TEXT UNIQUE,
    FOREIGN KEY (customer_id) REFERENCES customers(nessie_id),
    FOREIGN KEY (department_id) REFERENCES departments(department_id),
    FOREIGN KEY (decided_by) REFERENCES customers(nessie_id)
);

-- status is the lifecycle a manager can still move; policy_decision is the immutable record
-- of what the engine said at submission. Without both you cannot tell a policy block from a
-- manager rejection.
CREATE TABLE expenses (
    expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    -- Denormalized from customers: spend is charged to the department that owned it at
    -- submission time, not to wherever the employee sits today
    department_id INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    category TEXT NOT NULL CHECK (category IN (
        'travel', 'food', 'client meals', 'software', 'equipment',
        'marketing', 'training', 'office supplies', 'shipping', 'other'
    )),
    merchant VARCHAR(100),
    description TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'needs_approval', 'approved', 'rejected', 'paid', 'payout_failed'
    )),
    policy_decision TEXT NOT NULL CHECK (policy_decision IN (
        'auto_approved', 'needs_approval', 'blocked'
    )),
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decided_by TEXT,
    decided_at TIMESTAMP,
    -- Required when a manager rejects: a refusal the submitter cannot read is not a decision
    decision_note TEXT,
    -- Receipt bytes live on disk under settings.receipts_dir; only metadata is stored here.
    -- receipt_path is derived server-side from the hash, never from the uploaded filename
    receipt_path TEXT,
    receipt_filename TEXT,
    receipt_mime TEXT,
    receipt_hash TEXT,
    -- Where the receipt check got to. Separate from policy_decision because the engine never
    -- looks at a receipt, and unlike a violation this is not reproducible from the row
    receipt_check TEXT CHECK (receipt_check IN (
        'pending', 'clean', 'flagged', 'skipped', 'failed'
    )),
    -- UNIQUE is the idempotency guard, enforced by the database rather than by remembering to
    -- check. SQLite allows many NULLs here, so unpaid rows are fine
    nessie_transfer_id TEXT UNIQUE,
    FOREIGN KEY (customer_id) REFERENCES customers(nessie_id),
    FOREIGN KEY (department_id) REFERENCES departments(department_id),
    FOREIGN KEY (decided_by) REFERENCES customers(nessie_id)
);

CREATE INDEX idx_expenses_dept_month ON expenses (department_id, submitted_at);

-- A table rather than a JSON column so the approval queue can filter on `rule` directly, and so
-- the rule and severity vocabularies stay CHECK-declared beside every other enum in this file.
CREATE TABLE expense_violations (
    violation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL,
    rule TEXT NOT NULL CHECK (rule IN (
        'per_expense_cap', 'department_budget', 'approval_threshold', 'missing_receipt'
    )),
    severity TEXT NOT NULL CHECK (severity IN ('block', 'warn')),
    message TEXT NOT NULL,
    FOREIGN KEY (expense_id) REFERENCES expenses(expense_id) ON DELETE CASCADE
);

<<<<<<< HEAD
-- What a model read off a receipt, cached by the file hash rather than by the expense:
-- services/receipts.py dedupes identical bytes to one file on disk, so they are one reading
-- too, and a resubmitted receipt costs nothing. spec 8.1.
CREATE TABLE receipt_readings (
    receipt_hash TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN (
        'read', 'unreadable', 'unsupported', 'failed'
    )),
    merchant VARCHAR(100),
    total_cents INTEGER,
    -- ISO 8601, and NULL whenever the receipt did not print a date we could parse
    receipt_date TEXT,
    -- JSON array of strings, shown to the approver and never parsed back into money
    line_items TEXT,
    model TEXT NOT NULL,
    read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- A violation is what the engine decided and can be recomputed from the row at any time; a
-- flag is what a model noticed and cannot. Separate tables so a query can never confuse the
-- two, and so nothing an LLM said ever lands in the policy engine's vocabulary.
CREATE TABLE expense_flags (
    flag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL,
    flag TEXT NOT NULL CHECK (flag IN (
        'amount_mismatch', 'merchant_mismatch', 'category_mismatch',
        'stale_receipt', 'unreadable_receipt'
    )),
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Makes a re-check replace a flag rather than stack a second copy of it
    UNIQUE (expense_id, flag),
    FOREIGN KEY (expense_id) REFERENCES expenses(expense_id) ON DELETE CASCADE
);
=======
-- Spend rules, previously a constant in policy/rules.py. They live here so finance can change a
-- limit from the dashboard instead of shipping a deploy. department_id NULL is the org-wide
-- default a department inherits when it has no override of its own.
CREATE TABLE policy_rules (
    policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER,
    category TEXT NOT NULL CHECK (category IN (
        'travel', 'food', 'client meals', 'software', 'equipment',
        'marketing', 'training', 'office supplies', 'shipping', 'other'
    )),
    per_expense_limit_cents INTEGER NOT NULL CHECK (per_expense_limit_cents > 0),
    auto_approve_limit_cents INTEGER NOT NULL CHECK (auto_approve_limit_cents >= 0),
    -- Moving rules out of git loses the review trail that justified keeping them in code, so
    -- every change records its author
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- An inverted pair would make the auto-approve band unreachable
    CHECK (auto_approve_limit_cents <= per_expense_limit_cents),
    FOREIGN KEY (department_id) REFERENCES departments(department_id),
    FOREIGN KEY (updated_by) REFERENCES customers(nessie_id)
);

-- Two partial indexes rather than one UNIQUE(department_id, category): SQLite treats NULLs as
-- distinct, so a plain constraint would allow any number of org-wide rules per category.
CREATE UNIQUE INDEX idx_policy_rules_dept ON policy_rules (department_id, category)
    WHERE department_id IS NOT NULL;
CREATE UNIQUE INDEX idx_policy_rules_org ON policy_rules (category)
    WHERE department_id IS NULL;
>>>>>>> 08d74469fe20bb43266181098afee88b8f061d86
