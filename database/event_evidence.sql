-- Spoilers for the three embedded events. Read exercises.md first to investigate yourself.
WITH north AS (
    SELECT
        SUM(p.amount) FILTER (WHERE p.payment_date < DATE '2026-07-01') AS baseline,
        SUM(p.amount) FILTER (WHERE p.payment_date >= DATE '2026-07-01') AS observed
    FROM payments p
    JOIN customers c USING (customer_id)
    LEFT JOIN orders o ON o.order_id = p.order_id
    JOIN regions r ON r.region_id = COALESCE(o.region_id, c.region_id)
    WHERE p.payment_status = 'completed' AND r.region_name = 'North'
        AND p.payment_date >= DATE '2026-04-01' AND p.payment_date < DATE '2026-10-01'
), refund_rates AS (
    SELECT
        SUM(refund_amount) FILTER (WHERE month_start < DATE '2026-08-01')
            / NULLIF(SUM(revenue) FILTER (WHERE month_start < DATE '2026-08-01'), 0) AS baseline,
        SUM(refund_amount) FILTER (WHERE month_start >= DATE '2026-08-01')
            / NULLIF(SUM(revenue) FILTER (WHERE month_start >= DATE '2026-08-01'), 0) AS observed
    FROM analytics.monthly_refund_rate
    WHERE month_start >= DATE '2026-06-01' AND month_start < DATE '2026-10-01'
), enterprise_churn AS (
    SELECT m.month_start,
        (COUNT(s.subscription_id) FILTER (WHERE s.end_date < m.next_month))::numeric
            / NULLIF(COUNT(s.subscription_id), 0) AS rate
    FROM analytics.months m
    LEFT JOIN (subscriptions s JOIN customers c ON c.customer_id = s.customer_id)
        ON c.segment = 'enterprise' AND s.start_date < m.month_start
        AND (s.end_date IS NULL OR s.end_date >= m.month_start)
    WHERE m.month_start IN (DATE '2026-08-01', DATE '2026-09-01')
    GROUP BY m.month_start
), evidence AS (
    SELECT 'north_revenue' AS event, 'GBP' AS unit, baseline, observed FROM north
    UNION ALL
    SELECT 'refund_rate', 'fraction', baseline, observed FROM refund_rates
    UNION ALL
    SELECT 'enterprise_churn', 'fraction',
        MAX(rate) FILTER (WHERE month_start = DATE '2026-08-01'),
        MAX(rate) FILTER (WHERE month_start = DATE '2026-09-01') FROM enterprise_churn
)
SELECT event, unit, ROUND(baseline, 6) AS baseline, ROUND(observed, 6) AS observed,
    ROUND(100 * (observed / NULLIF(baseline, 0) - 1), 2) AS change_percent
FROM evidence ORDER BY event;
