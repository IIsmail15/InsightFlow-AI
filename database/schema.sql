-- Applied once by the transactional seed runner. Dates use UTC calendar days.
CREATE SCHEMA analytics;

CREATE TABLE dataset_metadata (
    dataset_id integer PRIMARY KEY CHECK (dataset_id = 1),
    random_seed integer NOT NULL,
    observation_start date NOT NULL,
    observation_end date NOT NULL, -- exclusive
    currency char(3) NOT NULL CHECK (currency = 'GBP'),
    content_hash text NOT NULL,
    CHECK (observation_end > observation_start),
    CHECK (EXTRACT(DAY FROM observation_start) = 1 AND EXTRACT(DAY FROM observation_end) = 1)
);

CREATE TABLE regions (
    region_id integer PRIMARY KEY,
    region_name text NOT NULL UNIQUE,
    sales_manager text NOT NULL
);

CREATE TABLE sales_representatives (
    sales_rep_id integer PRIMARY KEY,
    rep_name text NOT NULL,
    region_id integer NOT NULL REFERENCES regions,
    UNIQUE (sales_rep_id, region_id)
);

CREATE TABLE customers (
    customer_id integer PRIMARY KEY,
    company_name text NOT NULL,
    segment text NOT NULL CHECK (segment IN ('startup', 'sme', 'enterprise')),
    region_id integer NOT NULL REFERENCES regions,
    sales_rep_id integer NOT NULL,
    signup_date date NOT NULL,
    acquisition_channel text NOT NULL CHECK (acquisition_channel IN ('organic', 'paid_search', 'partner', 'referral')),
    status text NOT NULL CHECK (status IN ('active', 'churned')),
    FOREIGN KEY (sales_rep_id, region_id) REFERENCES sales_representatives (sales_rep_id, region_id)
);

CREATE TABLE products (
    product_id integer PRIMARY KEY,
    product_name text NOT NULL UNIQUE,
    category text NOT NULL,
    price numeric(12,2) NOT NULL CHECK (price > 0)
);

CREATE TABLE orders (
    order_id integer PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES customers,
    order_date date NOT NULL,
    status text NOT NULL CHECK (status IN ('completed', 'cancelled', 'pending')),
    total_amount numeric(12,2) NOT NULL CHECK (total_amount > 0),
    region_id integer NOT NULL REFERENCES regions,
    UNIQUE (order_id, customer_id)
);

CREATE TABLE order_items (
    order_item_id integer PRIMARY KEY,
    order_id integer NOT NULL REFERENCES orders,
    product_id integer NOT NULL REFERENCES products,
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_price numeric(12,2) NOT NULL CHECK (unit_price > 0),
    UNIQUE (order_id, product_id)
);

CREATE TABLE subscriptions (
    subscription_id integer PRIMARY KEY,
    customer_id integer NOT NULL UNIQUE REFERENCES customers,
    plan text NOT NULL CHECK (plan IN ('starter', 'growth', 'enterprise')),
    monthly_value numeric(12,2) NOT NULL CHECK (monthly_value > 0),
    start_date date NOT NULL,
    end_date date, -- first inactive day; null means still active at observation end
    status text NOT NULL CHECK (status IN ('active', 'cancelled')),
    CHECK (end_date IS NULL OR end_date > start_date),
    CHECK ((status = 'active' AND end_date IS NULL) OR (status = 'cancelled' AND end_date IS NOT NULL)),
    UNIQUE (subscription_id, customer_id)
);

CREATE TABLE payments (
    payment_id integer PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES customers,
    order_id integer,
    subscription_id integer,
    payment_date date NOT NULL,
    amount numeric(12,2) NOT NULL CHECK (amount > 0),
    payment_status text NOT NULL CHECK (payment_status IN ('completed', 'failed')),
    CHECK (num_nonnulls(order_id, subscription_id) = 1),
    FOREIGN KEY (order_id, customer_id) REFERENCES orders (order_id, customer_id),
    FOREIGN KEY (subscription_id, customer_id) REFERENCES subscriptions (subscription_id, customer_id)
);

CREATE UNIQUE INDEX one_completed_order_payment ON payments (order_id)
    WHERE order_id IS NOT NULL AND payment_status = 'completed';
CREATE UNIQUE INDEX one_subscription_invoice_per_day ON payments (subscription_id, payment_date)
    WHERE subscription_id IS NOT NULL;

CREATE TABLE refunds (
    refund_id integer PRIMARY KEY,
    payment_id integer NOT NULL UNIQUE REFERENCES payments,
    refund_date date NOT NULL,
    amount numeric(12,2) NOT NULL CHECK (amount > 0),
    reason text NOT NULL CHECK (reason IN ('product_defect', 'not_needed', 'service_issue'))
);

CREATE TABLE support_tickets (
    ticket_id integer PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES customers,
    created_at date NOT NULL,
    category text NOT NULL CHECK (category IN ('billing', 'technical', 'cancellation', 'onboarding')),
    priority text NOT NULL CHECK (priority IN ('low', 'medium', 'high')),
    status text NOT NULL CHECK (status IN ('open', 'resolved')),
    resolution_time_hours numeric(8,2),
    CHECK ((status = 'open' AND resolution_time_hours IS NULL)
        OR (status = 'resolved' AND resolution_time_hours >= 0 AND resolution_time_hours IS NOT NULL))
);

CREATE INDEX customers_region_idx ON customers (region_id);
CREATE INDEX orders_customer_date_idx ON orders (customer_id, order_date);
CREATE INDEX orders_date_region_idx ON orders (order_date, region_id);
CREATE INDEX order_items_product_idx ON order_items (product_id);
CREATE INDEX payments_date_idx ON payments (payment_date);
CREATE INDEX payments_customer_idx ON payments (customer_id);
CREATE INDEX refunds_date_idx ON refunds (refund_date);
CREATE INDEX subscriptions_dates_idx ON subscriptions (start_date, end_date);
CREATE INDEX support_customer_date_idx ON support_tickets (customer_id, created_at);
