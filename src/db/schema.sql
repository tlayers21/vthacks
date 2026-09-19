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

CREATE TABLE budget_requests (
    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Pending', 'Approved', 'Rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(nessie_id)
);
