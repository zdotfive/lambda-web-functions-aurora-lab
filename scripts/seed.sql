-- Seed: 1,000,000 customers and 5,000,000 orders spread over the last 365 days.
-- Run from the loadgen: psql "$DB_URL" -v ON_ERROR_STOP=1 -f scripts/seed.sql
\timing on

DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
  id         bigint PRIMARY KEY,
  name       text        NOT NULL,
  email      text        NOT NULL,
  country    char(2)     NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE TABLE orders (
  id          bigint PRIMARY KEY,
  customer_id bigint        NOT NULL REFERENCES customers (id),
  amount      numeric(10,2) NOT NULL,
  status      text          NOT NULL,
  created_at  timestamptz   NOT NULL
);

SELECT setseed(0.42);

INSERT INTO customers (id, name, email, country, created_at)
SELECT g,
       'Customer ' || g,
       'customer' || g || '@example.com',
       (ARRAY['IT','DE','FR','ES','NL','IE','PL','SE','US','GB'])[1 + (g % 10)],
       now() - (random() * interval '1095 days')
FROM generate_series(1, 1000000) AS g;

INSERT INTO orders (id, customer_id, amount, status, created_at)
SELECT g,
       1 + floor(random() * 1000000)::bigint,
       round((5 + random() * 495)::numeric, 2),
       (ARRAY['created','paid','shipped','delivered','cancelled'])[1 + floor(random() * 5)::int],
       now() - (random() * interval '365 days')
FROM generate_series(1, 5000000) AS g;

CREATE INDEX orders_customer_created_idx ON orders (customer_id, created_at DESC);

ANALYZE customers;
ANALYZE orders;

SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size;
SHOW max_connections;
