CREATE TABLE IF NOT EXISTS lifecycle_events (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER,
    action VARCHAR(100) NOT NULL,
    message TEXT,
    created_at TIMESTAMP NOT NULL
);
