
# Automatic crypto speculation garbage

Don't use _any_ of this. The only neat thing is a moving average calculation done in `robin_movavg.py` where it buys
if a 6-hour moving average falls below a 72-hour moving average.


TODO copy comments from `*.py` here so people know to install deps using:

```bash
python -m pip install --user robin_stocks

# Then replace the following lines in all .py files:
login = robinhood.login(
  'email@example.com',
  'some-pw-or-token',
)

# TODO document some variables used at runtime
ROBIN_BS_PERCENT=0.01
ROBIN_SPEC_CASH=10.0
USE_SECURITY=BTC
ROBIN_TIMEOUT_SEC=2700

```


