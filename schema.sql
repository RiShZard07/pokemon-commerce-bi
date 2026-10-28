CREATE TABLE IF NOT EXISTS dim_product (
 product_id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
 list_cents INTEGER NOT NULL CHECK(list_cents >= 0)
);
CREATE TABLE IF NOT EXISTS dim_date(day TEXT PRIMARY KEY, weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6));
CREATE TABLE IF NOT EXISTS fact_order_line (
 line_id TEXT PRIMARY KEY, day TEXT NOT NULL REFERENCES dim_date(day),
 product_id TEXT NOT NULL REFERENCES dim_product(product_id),
 quantity INTEGER NOT NULL CHECK(quantity > 0), unit_cents INTEGER NOT NULL CHECK(unit_cents >= 0),
 discount_cents INTEGER NOT NULL CHECK(discount_cents BETWEEN 0 AND quantity*unit_cents),
 status TEXT NOT NULL CHECK(status IN ('completed','returned','cancelled'))
);
CREATE INDEX IF NOT EXISTS idx_line_day ON fact_order_line(day);
CREATE INDEX IF NOT EXISTS idx_line_product ON fact_order_line(product_id);
CREATE TABLE IF NOT EXISTS load_audit(run_id INTEGER PRIMARY KEY, input_rows INTEGER,
 accepted_rows INTEGER,rejected_rows INTEGER,loaded_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE VIEW IF NOT EXISTS mart_daily AS
 SELECT day, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed_lines,
 SUM(CASE WHEN status='completed' THEN quantity*unit_cents-discount_cents ELSE 0 END) AS net_cents
 FROM fact_order_line GROUP BY day;
CREATE VIEW IF NOT EXISTS mart_product AS
 SELECT p.product_id,p.name,p.category,
 SUM(CASE WHEN f.status='completed' THEN f.quantity ELSE 0 END) AS completed_units,
 SUM(CASE WHEN f.status='completed' THEN f.quantity*f.unit_cents-f.discount_cents ELSE 0 END) AS net_cents
 FROM dim_product p LEFT JOIN fact_order_line f ON p.product_id=f.product_id GROUP BY p.product_id;
CREATE VIEW IF NOT EXISTS mart_kpi AS
 SELECT SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed_lines,
 SUM(CASE WHEN status='completed' THEN quantity ELSE 0 END) AS completed_units,
 SUM(CASE WHEN status='completed' THEN quantity*unit_cents-discount_cents ELSE 0 END) AS net_cents
 FROM fact_order_line;
