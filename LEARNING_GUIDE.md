# How to understand this project

## 1. What problem does it solve?

Raw order exports contain duplicate IDs, missing product references, impossible dates, and invalid quantities. Reports can quietly double-count or contradict one another. The prototype applies one contract, isolates bad rows, and derives all reports from the same warehouse.

## 2. Follow one record

Find line `L0000003` in `data/orders.csv`. `validate` turns numeric strings into integers and checks its product/date/status. The load transaction writes it to `fact_order_line`. Each SQL view applies the same completed-revenue rule. The dashboard displays aggregated results, not raw records.

## 3. Know these choices

- **ETL:** extract a CSV, transform and validate its values, load structured tables.
- **Grain:** one order line. Calling this number orders or customers would be wrong.
- **Dimension:** descriptive context such as a product or calendar day.
- **Fact:** a measurable event such as quantity purchased and cents paid.
- **Idempotence:** rerunning the same snapshot preserves totals, rather than adding it twice.
- **Atomic transaction:** all warehouse changes commit together or roll back together.
- **Data mart:** a stable query/view tailored to a reporting use case.
- **Quarantine:** rejected records remain available for investigation.
- **Leakage:** using future information to make a prediction. The baselines only use training days.

## 4. Hands-on checks

1. Run the demo and tests. Open the dashboard.
2. Read `quality.json`. Find one rejected row for each fault category.
3. Load the same files again. Prove the revenue is unchanged.
4. Change an input status from completed to returned. Predict the revenue change, then rerun.
5. Change a price from cents to dollars accidentally. Explain why integer monetary units need documentation.
6. Add a test for a completely blank product name and another for a missing input column.
7. Use Python's `sqlite3` to query `mart_kpi`, `mart_daily`, and `mart_product`. Reconcile totals.
8. Explain why a full-refresh loader is dangerous if fed a partial incremental batch.

## 5. Honest interview framing

This was built with substantial AI assistance. Explain which pieces you personally inspected, modified, or tested rather than claiming you wrote every line unaided. There are no real users, real sales, cloud deployment, or proven business gains.

Before an interview, be able to explain `load` without reading it, write the completed-revenue SQL yourself, and implement a small requested change. Reading this guide is not a substitute for doing those exercises.

## 6. Sensible next work

Add schema-version migrations, atomic report publication, persisted failed-run audits, a real licensed data source, incremental updates with late-arriving corrections, and a Tableau dashboard. These are future ideas, not implemented features.
