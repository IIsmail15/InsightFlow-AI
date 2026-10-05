-- A complete calendar keeps zero-activity months visible. Observation end is exclusive.
CREATE OR REPLACE VIEW analytics.months AS
SELECT d::date AS month_start, (d + interval '1 month')::date AS next_month
FROM dataset_metadata,
LATERAL generate_series(observation_start::timestamp,
    (observation_end - interval '1 month')::timestamp, interval '1 month') AS d;

CREATE OR REPLACE VIEW analytics.monthly_revenue AS
SELECT m.month_start, COALESCE(SUM(p.amount), 0)::numeric(16,2) AS revenue
FROM analytics.months m
LEFT JOIN payments p ON p.payment_date >= m.month_start AND p.payment_date < m.next_month
    AND p.payment_status = 'completed'
GROUP BY m.month_start;

CREATE OR REPLACE VIEW analytics.monthly_mrr AS
SELECT m.month_start, COALESCE(SUM(s.monthly_value), 0)::numeric(16,2) AS mrr
FROM analytics.months m
LEFT JOIN subscriptions s ON s.start_date < m.next_month
    AND (s.end_date IS NULL OR s.end_date >= m.next_month)
GROUP BY m.month_start;

CREATE OR REPLACE VIEW analytics.monthly_average_order_value AS
SELECT m.month_start, COUNT(o.order_id) AS completed_orders,
    COALESCE(SUM(o.total_amount), 0)::numeric(16,2) AS completed_order_value,
    ROUND(SUM(o.total_amount) / NULLIF(COUNT(o.order_id), 0), 2) AS average_order_value
FROM analytics.months m
LEFT JOIN orders o ON o.order_date >= m.month_start AND o.order_date < m.next_month
    AND o.status = 'completed'
GROUP BY m.month_start;

-- Aggregate refunds independently: joining raw payments to refunds/items can multiply revenue.
CREATE OR REPLACE VIEW analytics.monthly_refund_rate AS
WITH refunded AS (
    SELECT m.month_start, COALESCE(SUM(r.amount), 0)::numeric(16,2) AS refund_amount
    FROM analytics.months m
    LEFT JOIN refunds r ON r.refund_date >= m.month_start AND r.refund_date < m.next_month
    GROUP BY m.month_start
)
SELECT r.month_start, r.refund_amount, p.revenue,
    ROUND(r.refund_amount / NULLIF(p.revenue, 0), 6) AS refund_rate
FROM refunded r JOIN analytics.monthly_revenue p USING (month_start);

-- Opening cohort = subscribers active immediately BEFORE the month's first day.
-- A cancellation on the first day belongs to this month. Same-month entrants are excluded.
CREATE OR REPLACE VIEW analytics.monthly_customer_churn AS
SELECT m.month_start, COUNT(s.subscription_id) AS opening_customers,
    COUNT(s.subscription_id) FILTER (WHERE s.end_date < m.next_month) AS churned_customers,
    ROUND((COUNT(s.subscription_id) FILTER (WHERE s.end_date < m.next_month))::numeric
        / NULLIF(COUNT(s.subscription_id), 0), 6) AS churn_rate
FROM analytics.months m
LEFT JOIN subscriptions s ON s.start_date < m.month_start
    AND (s.end_date IS NULL OR s.end_date >= m.month_start)
GROUP BY m.month_start;
