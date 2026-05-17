CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE DATABASE test;

\connect test
CREATE EXTENSION IF NOT EXISTS pgcrypto;
\i /docker-entrypoint-initdb.d/2.schema.sql
\i /docker-entrypoint-initdb.d/test-seed
