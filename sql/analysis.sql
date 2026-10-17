-- Aggregation queries (CTEs + window functions). Each block starts with
-- "-- name: <table>" and is exported to data/processed/<table>.csv.
-- "Completed" = is_cancelled = 0.

-- name: kpi_summary
SELECT
    ROUND(SUM(f.sales), 2)                                            AS total_revenue,
    COUNT(DISTINCT f.transaction_no)                                  AS completed_transactions,
    ROUND(SUM(f.sales) * 1.0 / COUNT(DISTINCT f.transaction_no), 2)   AS avg_order_value,
    SUM(f.quantity)                                                   AS units_sold
FROM fact_order_line f
WHERE f.is_cancelled = 0;

-- name: monthly_revenue
WITH monthly AS (
    SELECT strftime('%Y-%m', d.full_date)  AS month,
           SUM(f.sales)                    AS revenue,
           COUNT(DISTINCT f.transaction_no) AS orders
    FROM fact_order_line f
    JOIN dim_date d ON d.date_id = f.date_id
    WHERE f.is_cancelled = 0
    GROUP BY strftime('%Y-%m', d.full_date)
)
SELECT month,
       ROUND(revenue, 2) AS revenue,
       orders,
       ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))
             / LAG(revenue) OVER (ORDER BY month), 1)              AS mom_growth_pct,
       ROUND(SUM(revenue) OVER (ORDER BY month
             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 2) AS running_revenue
FROM monthly
ORDER BY month;

-- name: product_pareto
WITH product_rev AS (
    SELECT p.product_no, p.product_name, SUM(f.sales) AS revenue
    FROM fact_order_line f
    JOIN dim_product p ON p.product_id = f.product_id
    WHERE f.is_cancelled = 0
    GROUP BY p.product_id, p.product_no, p.product_name
)
SELECT product_no,
       product_name,
       ROUND(revenue, 2)                                      AS revenue,
       RANK() OVER (ORDER BY revenue DESC)                    AS revenue_rank,
       ROUND(100.0 * revenue / SUM(revenue) OVER (), 2)       AS share_pct,
       ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue DESC, product_no
             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
             / SUM(revenue) OVER (), 2)                       AS cumulative_pct
FROM product_rev
ORDER BY revenue DESC, product_no;

-- name: customer_segments
WITH customer_rev AS (
    SELECT c.customer_no,
           SUM(f.sales)                     AS revenue,
           COUNT(DISTINCT f.transaction_no) AS orders
    FROM fact_order_line f
    JOIN dim_customer c ON c.customer_id = f.customer_id
    WHERE f.is_cancelled = 0
      AND c.is_guest = 0
    GROUP BY c.customer_id, c.customer_no
),
ranked AS (
    SELECT customer_no, revenue, orders,
           NTILE(4) OVER (ORDER BY revenue DESC) AS revenue_quartile
    FROM customer_rev
)
SELECT customer_no,
       ROUND(revenue, 2) AS revenue,
       orders,
       revenue_quartile,
       CASE revenue_quartile
            WHEN 1 THEN 'Top 25%'
            WHEN 2 THEN 'Upper-middle'
            WHEN 3 THEN 'Lower-middle'
            ELSE 'Bottom 25%'
       END AS segment
FROM ranked
ORDER BY revenue DESC;

-- name: country_summary
WITH country_rev AS (
    SELECT co.country,
           SUM(f.sales)                     AS revenue,
           COUNT(DISTINCT f.transaction_no) AS orders
    FROM fact_order_line f
    JOIN dim_country co ON co.country_id = f.country_id
    WHERE f.is_cancelled = 0
    GROUP BY co.country_id, co.country
)
SELECT country,
       ROUND(revenue, 2)                                   AS revenue,
       orders,
       ROUND(revenue * 1.0 / orders, 2)                    AS avg_order_value,
       ROUND(100.0 * revenue / SUM(revenue) OVER (), 2)    AS revenue_share_pct,
       RANK() OVER (ORDER BY revenue DESC)                 AS revenue_rank
FROM country_rev
ORDER BY revenue DESC;

-- name: cancellation_by_month
SELECT strftime('%Y-%m', d.full_date) AS month,
       COUNT(DISTINCT CASE WHEN f.is_cancelled = 0 THEN f.transaction_no END) AS completed_orders,
       COUNT(DISTINCT CASE WHEN f.is_cancelled = 1 THEN f.transaction_no END) AS cancelled_orders,
       ROUND(100.0 * COUNT(DISTINCT CASE WHEN f.is_cancelled = 1 THEN f.transaction_no END)
             / COUNT(DISTINCT f.transaction_no), 2)                            AS cancellation_rate_pct
FROM fact_order_line f
JOIN dim_date d ON d.date_id = f.date_id
GROUP BY strftime('%Y-%m', d.full_date)
ORDER BY month;
