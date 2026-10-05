-- Each query returns a count of invalid rows; the loader refuses to commit any failures.
SELECT 'order_totals' AS rule, COUNT(*) AS violations
FROM orders o LEFT JOIN (
    SELECT order_id, SUM(quantity * unit_price) AS amount FROM order_items GROUP BY order_id
) i USING (order_id)
WHERE i.amount IS NULL OR i.amount <> o.total_amount
UNION ALL
SELECT 'completed_order_payments', COUNT(*) FROM orders o
WHERE o.status = 'completed' AND NOT EXISTS (
    SELECT 1 FROM payments p WHERE p.order_id = o.order_id AND p.payment_status = 'completed'
)
UNION ALL
SELECT 'order_payment_consistency', COUNT(*) FROM payments p JOIN orders o USING (order_id)
WHERE p.payment_date < o.order_date OR p.amount <> o.total_amount
    OR (p.payment_status = 'completed' AND o.status <> 'completed')
UNION ALL
SELECT 'subscription_payment_consistency', COUNT(*)
FROM payments p JOIN subscriptions s USING (subscription_id)
WHERE p.payment_date < s.start_date OR p.payment_date >= s.end_date OR p.amount <> s.monthly_value
UNION ALL
SELECT 'refund_consistency', COUNT(*) FROM refunds r JOIN payments p USING (payment_id)
WHERE p.payment_status <> 'completed' OR p.order_id IS NULL
    OR r.amount > p.amount OR r.refund_date < p.payment_date
UNION ALL
SELECT 'customer_timeline', COUNT(*) FROM (
    SELECT customer_id, order_date AS event_date FROM orders
    UNION ALL SELECT customer_id, start_date FROM subscriptions
    UNION ALL SELECT customer_id, created_at FROM support_tickets
) e JOIN customers c USING (customer_id) WHERE e.event_date < c.signup_date
UNION ALL
SELECT 'observation_window', COUNT(*) FROM (
    SELECT signup_date AS event_date FROM customers
    UNION ALL SELECT order_date FROM orders
    UNION ALL SELECT payment_date FROM payments
    UNION ALL SELECT refund_date FROM refunds
    UNION ALL SELECT start_date FROM subscriptions
    UNION ALL SELECT end_date FROM subscriptions WHERE end_date IS NOT NULL
    UNION ALL SELECT created_at FROM support_tickets
) e CROSS JOIN dataset_metadata d
WHERE e.event_date < d.observation_start OR e.event_date >= d.observation_end;
