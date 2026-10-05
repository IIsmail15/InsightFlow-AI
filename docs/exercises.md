# Three SQL investigations

Use the default seed and fixed 2026 dates. Attempt these before reading `database/event_evidence.sql`. Work at the `psql` prompt from the README. You do not need to change or delete data.

## 1. Find the region responsible for declining revenue

Write a query comparing **April–June 2026** with **July–September 2026**, grouped by region.

Return `region_name`, `baseline_revenue`, `observed_revenue`, `absolute_change`, and `percentage_change`, sorted by the largest decline in GBP. Include both order and subscription payments, using only completed payments. Use the order's stored region for order payments and the customer's region for subscription payments.

Hints: join payments to customers, left-join orders, and resolve the region with `COALESCE`. Conditional aggregation with `FILTER` can put both periods in one row. Use exclusive upper date bounds and protect the percentage denominator with `NULLIF`.

Self-check: four region rows; North has a clear decline. Regional totals should reconcile to `analytics.monthly_revenue` for the same periods. Do not join order items for this metric.

## 2. Investigate the Analytics Export refund spike

Compare two **purchase cohorts**, June–July and August–September 2026, for completed orders that contain Analytics Export. Return `period`, `completed_orders`, `refunded_orders`, and `refunded_order_share`. Count refunds observed through 30 September, even if issued in a later month than the purchase.

Hints: use `EXISTS` to select orders containing the product; join completed order payments to refunds. Count distinct orders, or ensure the joins preserve one row per order. This exercise's order-count cohort rate differs deliberately from the official refund-amount cash-flow rate. Name it accordingly.

Self-check: two rows; the later cohort has a much higher refunded-order share. Explain why an order placed near 30 September has less time to receive a recorded refund. As an extension, compare the `reason` values and technical ticket counts, without claiming that customer-level ticket proximity proves causation.

## 3. Reconstruct historical enterprise churn

Calculate August and September 2026 churn **for every customer segment**, using subscriptions and customers rather than the aggregate churn view.

Return `month_start`, `segment`, `opening_customers`, `churned_customers`, and `churn_rate`. Use the official opening-cohort definition from the metric metadata. Include a cancellation on the month's first day and exclude a subscription beginning during that month.

Hints: cross-join the two months with the three segments, then left-join eligible subscriptions so zero-count cohorts remain visible. Derive membership from start/end dates, not today's status. Divide by `NULLIF(opening_customers, 0)` and cast to numeric before division.

Self-check: six rows; enterprise churn increases sharply in September. Summed segment counts should reconcile to `analytics.monthly_customer_churn`; rates themselves should not be summed or averaged without weighting.

After completing the queries, change one generator event probability, export it to a new directory with the same random seed, and predict how its SQL result should change before loading it into a disposable demo database. Keep the default seed data for the documented acceptance checks.
