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
    monthly_budget_cents INTEGER NOT NULL DEFAULT 0,
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
