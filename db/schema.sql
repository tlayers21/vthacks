CREATE TABLE customers (
    nessie_id INT NOT NULL UNIQUE PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('Finance', 'Manager', 'Employee')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE accounts (
    nessie_id INT NOT NULL UNIQUE PRIMARY KEY,
    customer_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(nessie_id)
);

CREATE TABLE budget_requests (
    request_id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Pending', 'Approved', 'Rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(nessie_id)
);
