-- Local development only: give Supabase Auth (GoTrue) a password for its
-- database role, the same way Supabase's own docker setup does. Runs once,
-- as supabase_admin, when the database volume is first created.
\set pgpass `echo "$POSTGRES_PASSWORD"`
ALTER USER supabase_auth_admin WITH PASSWORD :'pgpass';
