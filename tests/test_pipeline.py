import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import generate, load, report, validate, baseline_evaluation, read_csv, write_csv


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.db = self.root / 'out' / 'warehouse.sqlite'
        generate(self.data, 1000)
        self.good = dict(line_id='L1', day='2026-01-01', product_id='P00',
                         quantity='2', unit_cents='500', discount_cents='100', status='completed')

    def tearDown(self):
        self.tmp.cleanup()

    def test_reproducible_generator(self):
        other = self.root / 'other'
        generate(other, 1000)
        self.assertEqual((self.data/'orders.csv').read_bytes(), (other/'orders.csv').read_bytes())

    def test_valid_contract(self):
        self.assertEqual(validate(self.good, {'P00'})['quantity'], 2)

    def test_fault_contracts(self):
        faults = [('quantity', '0'), ('quantity', '-1'), ('unit_cents', '-1'),
                  ('discount_cents', '1001'), ('discount_cents', '-1'), ('status', 'unknown'),
                  ('day', '2026-02-31'), ('product_id', 'bad'), ('line_id', ' ')]
        for key, value in faults:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate(dict(self.good, **{key:value}), {'P00'})

    def test_reconciliation(self):
        q = load(self.data, self.db)
        self.assertEqual(q['input_rows'], q['accepted_rows'] + q['rejected_rows'])
        reasons = [r['reason'] for r in json.loads((self.db.parent/'rejected.json').read_text())]
        self.assertIn('duplicate line_id', reasons)
        self.assertIn('unknown product_id', reasons)

    def test_rerun_no_double_count(self):
        load(self.data, self.db)
        with sqlite3.connect(self.db) as c:
            before = c.execute('SELECT * FROM mart_kpi').fetchone()
        load(self.data, self.db)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(before, c.execute('SELECT * FROM mart_kpi').fetchone())
            self.assertEqual(2, c.execute('SELECT COUNT(*) FROM load_audit').fetchone()[0])

    def test_integer_revenue_and_status_rules(self):
        a = self.good
        rows = [a, dict(a, line_id='L2', status='returned'), dict(a,line_id='L3',status='cancelled')]
        write_csv(self.data/'orders.csv', rows)
        load(self.data,self.db)
        with sqlite3.connect(self.db) as c:
            self.assertEqual((1,2,900), c.execute('SELECT * FROM mart_kpi').fetchone())

    def test_empty_batch_preserves_warehouse(self):
        load(self.data,self.db)
        write_csv(self.data/'orders.csv', [dict(self.good, quantity='-1')])
        with self.assertRaises(ValueError):
            load(self.data,self.db)
        with sqlite3.connect(self.db) as c:
            self.assertGreater(c.execute('SELECT COUNT(*) FROM fact_order_line').fetchone()[0], 0)

    def test_transaction_rolls_back_on_sql_failure(self):
        load(self.data,self.db)
        with sqlite3.connect(self.db) as c:
            before = c.execute('SELECT * FROM mart_kpi').fetchone()
        products = read_csv(self.data/'products.csv')
        products[0]['name'] = 'modified'
        write_csv(self.data/'products.csv',products)
        with sqlite3.connect(self.db) as c:
            c.execute("CREATE TRIGGER fail_load BEFORE INSERT ON fact_order_line BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            load(self.data,self.db)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(before,c.execute('SELECT * FROM mart_kpi').fetchone())
            self.assertNotEqual('modified',c.execute("SELECT name FROM dim_product WHERE product_id='P00'").fetchone()[0])

    def test_duplicate_product_keys_rejected(self):
        products=read_csv(self.data/'products.csv')
        write_csv(self.data/'products.csv',products+products[:1])
        with self.assertRaises(ValueError):
            load(self.data,self.db)

    def test_alert_threshold(self):
        self.assertTrue(load(self.data,self.db,alert_threshold=0)['alert'])
        self.assertFalse(load(self.data,self.db,alert_threshold=1)['alert'])

    def test_forecast_no_holdout_leakage(self):
        daily=[dict(net_cents=100,day=str(i)) for i in range(30)]
        result=baseline_evaluation(daily)
        self.assertEqual(0,result['mean_mae_usd'])
        daily[-1]['net_cents']=1500
        result=baseline_evaluation(daily)
        self.assertEqual(1,result['mean_mae_usd'])
        self.assertEqual(1,result['weekly_repeat_mae_usd'])

    def test_short_forecast_guard(self):
        self.assertFalse(baseline_evaluation([dict(net_cents=100)]*10)['available'])

    def test_report_and_csv(self):
        load(self.data,self.db)
        result=report(self.db,self.db.parent)
        self.assertTrue(result['synthetic'])
        self.assertEqual(90,len(read_csv(self.db.parent/'daily.csv')))
        page=(self.db.parent/'dashboard.html').read_text()
        self.assertIn('Synthetic demonstration data',page)
        self.assertIn('Filter product table',page)

    def test_sql_marts_reconcile(self):
        load(self.data,self.db)
        with sqlite3.connect(self.db) as c:
            kpi=c.execute('SELECT net_cents FROM mart_kpi').fetchone()[0]
            self.assertEqual(kpi,c.execute('SELECT SUM(net_cents) FROM mart_daily').fetchone()[0])
            self.assertEqual(kpi,c.execute('SELECT SUM(net_cents) FROM mart_product').fetchone()[0])
            self.assertEqual([],c.execute('PRAGMA foreign_key_check').fetchall())


if __name__ == '__main__':
    unittest.main()
