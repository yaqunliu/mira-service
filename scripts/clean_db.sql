-- SQL script to truncate all tables and clear all data
-- Usage: psql -d <database_name> -f clean_db.sql

BEGIN;

-- Disable triggers temporarily if needed, but TRUNCATE CASCADE handles FKs.
-- Using TRUNCATE ... CASCADE is the most efficient way to clear data while keeping schema.

TRUNCATE TABLE
    shot_characters,
    shots,
    scenes,
    characters,
    creations,
    chapters,
    novels,
    points_records,
    temporary_points,
    points_accounts,
    subscription_points_history,
    creem_payments,
    wechat_payments,
    creem_subscriptions,
    wechat_subscriptions,
    orders,
    subscriptions,
    products,
    webhook_events,
    users
RESTART IDENTITY CASCADE;

COMMIT;
