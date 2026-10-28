# Local verification

Default command: `python pipeline.py demo` (seed 42)

- Input rows including duplicates: 20,200
- Accepted rows: 19,756
- Quarantined rows: 444
- Rejected rate: 2.198%; triggers the configured 2% local quality alert
- Completed lines: 17,713
- Completed units: 35,557
- Net completed revenue: $467,373.50 in synthetic demonstration transactions
- Forecast training window: 76 days; holdout: 14 days
- Training-mean baseline MAE: $276.43
- Weekly-repeat baseline MAE: $454.21
- Local tests: 14 passing; hosted CI not yet verified

The mean baseline wins here. This is a synthetic fixture, not evidence of predictive accuracy on a real marketplace. All simulated monetary amounts are illustrative, not actual revenue.
