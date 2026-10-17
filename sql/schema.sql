-- Star schema for UK e-commerce transactions (SQLite; standard SQL that also
-- runs on PostgreSQL with minor type changes).
-- Grain of the fact table: one row per transaction line.

DROP TABLE IF EXISTS fact_order_line;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_country;

CREATE TABLE dim_country (
    country_id  INTEGER PRIMARY KEY,
    country     TEXT NOT NULL UNIQUE
);

CREATE TABLE dim_product (
    product_id    INTEGER PRIMARY KEY,
    product_no    TEXT NOT NULL UNIQUE,
    product_name  TEXT NOT NULL
);

CREATE TABLE dim_customer (
    customer_id  INTEGER PRIMARY KEY,
    customer_no  TEXT NOT NULL UNIQUE,
    is_guest     INTEGER NOT NULL CHECK (is_guest IN (0, 1))
);

CREATE TABLE dim_date (
    date_id      INTEGER PRIMARY KEY,          -- YYYYMMDD
    full_date    TEXT NOT NULL UNIQUE,         -- YYYY-MM-DD
    year         INTEGER NOT NULL,
    month        INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    quarter      INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    day_of_week  INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6)  -- 0 = Monday
);

CREATE TABLE fact_order_line (
    line_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_no  TEXT    NOT NULL,
    date_id         INTEGER NOT NULL REFERENCES dim_date(date_id),
    product_id      INTEGER NOT NULL REFERENCES dim_product(product_id),
    customer_id     INTEGER NOT NULL REFERENCES dim_customer(customer_id),
    country_id      INTEGER NOT NULL REFERENCES dim_country(country_id),
    quantity        INTEGER NOT NULL,
    unit_price      REAL    NOT NULL CHECK (unit_price > 0),
    sales           REAL    NOT NULL,          -- quantity * unit_price
    is_cancelled    INTEGER NOT NULL CHECK (is_cancelled IN (0, 1))
);

CREATE INDEX idx_fact_date        ON fact_order_line(date_id);
CREATE INDEX idx_fact_product     ON fact_order_line(product_id);
CREATE INDEX idx_fact_customer    ON fact_order_line(customer_id);
CREATE INDEX idx_fact_country     ON fact_order_line(country_id);
CREATE INDEX idx_fact_transaction ON fact_order_line(transaction_no);
