
# python -m pip install --user robin_stocks
# https://robin-stocks.readthedocs.io/en/latest/robinhood.html
from robin_stocks import robinhood


import os
import sys
import random
import time
import pickle
import json
import signal
import subprocess
import locale

# Create a persistable cache for music analysis data
from functools import wraps
def cached(cache_file):
  initial_cache = {}
  try:
    with open(cache_file, 'rb') as fd:
      initial_cache = pickle.load(fd)
  except Exception as e:
    #print(e)
    pass

  def inner_cached(func):
      func.cache = initial_cache
      @wraps(func)
      def wrapper(*args):
          try:
              return func.cache[args]
          except KeyError:
              result = func(*args)
              func.cache[args] = result
              with open(cache_file, 'wb') as fd:
                pickle.dump(func.cache, fd)
              #print('Saved {} to {}'.format(args, cache_file))
              return result
      return wrapper
  return inner_cached

robin_logged_in = False

def check_robin_login():
  global robin_logged_in
  if not robin_logged_in:
    # Ensure generate_device_token always gives
    # the same machine name.
    # https://github.com/jmfernandes/robin_stocks/blob/master/robin_stocks/robinhood/authentication.py
    random.seed(a="123", version=2)
    login = robinhood.login(
      'email@example.com',
      'some-pw-or-token',
    )
    random.seed(a=str(time.time()), version=2)
    robin_logged_in = True

# returns [oldest price (1 week ago), newest price (now)]
# in 5-minute increments
@cached('/tmp/.get_crypto_history_cached.cache.bin')
def get_crypto_history_cached(sec, timestamp):
  return get_crypto_history(sec)

def get_crypto_history(sec):
  while True:
    try:
      check_robin_login()
      # https://robin-stocks.readthedocs.io/en/latest/robinhood.html#robin_stocks.robinhood.crypto.get_crypto_historicals
      history_json = robinhood.crypto.get_crypto_historicals(
        sec, interval='5minute', span='week'
        #sec, interval='hour', span='month'
      )
      #print('history_json[0] = {}'.format(history_json[0]))
      #print('history_json[-1] = {}'.format(history_json[-1]))
      return [float(x['close_price']) for x in history_json]
    except Exception as e:
      print(e)
      time.sleep(1)


def avg(list):
  return sum([x / len(list) for x in list])

# 10 slots = 50 minute moving avg
def moving_avg(history, slots=10):
  averages = []
  moving_avg = []
  for i in range(0, slots):
    moving_avg.append(history[i])

  for i in range(len(moving_avg), len(history)):
    moving_avg.pop(0)
    moving_avg.append(history[i])
    averages.append(avg(moving_avg))

  return averages

def moving_avg_1hr(history):
  return moving_avg(history, slots=12)

def moving_avg_3hr(history):
  return moving_avg(history, slots=12*3)

def moving_avg_6hr(history):
  return moving_avg(history, slots=12*6)

def moving_avg_12hr(history):
  return moving_avg(history, slots=12*12)

def sim_strat(sec, history, history_avg_long, history_avg_short):

  def purchase_decision(history, history_avg_short, history_avg_long, i=-1):
    if history[i] < history_avg_short[i]:
      return 'buy b/c now:{} < short avg:{}'.format(history[i], history_avg_short[i])

    if history[i] > history_avg_long[i]:
      return 'sell b/c now:{} > long avg:{}'.format(history[i], history_avg_long[i])

    return 'hold'


  cash = BEGIN_CASH
  shares = 0.0
  price_per_share = None
  last_buy_price = 0.0
  for i in range(-SIMULATION_TICKS, -1,1):
    print('')
    print('i={} cash={} shares={}'.format(i, cash, shares))
    decision = purchase_decision(history, history_avg_short, history_avg_long, i)
    print('purchase_decision({}) = {}'.format(i, purchase_decision(history, history_avg_short, history_avg_long, i)))
    price_per_share = history[i]
    if 'buy' in decision:
      if cash > 1.00:
        new_shares = cash / price_per_share
        print('BUY {} shares for {}'.format(new_shares, cash))
        shares += new_shares
        cash = 0.0
        last_buy_price = price_per_share
      else:
        print('CANNOT BUY; no cash')
    
    elif 'sell' in decision:
      if shares > 0.0:
        if price_per_share > last_buy_price:
          new_cash = shares * price_per_share
          print('SELL {} shares for {}'.format(shares, new_cash))
          cash += new_cash
          shares = 0.0
        else:
          print('REFUSED SELL; current price {} is < last_buy_price {}'.format(price_per_share, last_buy_price))
      else:
        print('CANNOT SELL; no shares')

    else:
      print('HOLDING')

  # sell all at end if we hold shares
  if shares > 0.0:
    cash = shares * price_per_share
    shares = 0.0
  sim_hours = SIMULATION_TICKS / 12

  print('')
  print('{}-hr trade sim of {} with cash={} ({}% gain)'.format(round(sim_hours, 1), sec, round(cash, 4), round(((cash-BEGIN_CASH)/BEGIN_CASH)*100.0,2)  ))
  print('END SIMPLEST')


def get_free_shares(sec):
  positions = robinhood.crypto.get_crypto_positions();
  for position in positions:
    if sec in position['currency']['code']:
      return float(position['quantity']) - float(position['quantity_held_for_sell'])

  return 0.0



def printable(obj):
  return json.dumps(obj, sort_keys=True, indent=2);

def on_exit(sig, frame):
  global active_buy_order_id
  
  print('CANCELLING BUY ORDER (ctrl+c)')
  order_state = 'unk'
  while active_buy_order_id and order_state != 'canceled':
    print('.', end='', flush=True)
    order_status = robinhood.orders.cancel_crypto_order(active_buy_order_id)
    if 'state' in order_status:
      order_state = order_status['state'].lower().strip()
    elif 'Order cannot be canceled at this time' in printable(order_status):
      break;
    else:
      print('order_status={}'.format(printable(order_status)))

  sys.exit(0)

SIMULATION_TICKS = 12*120
BEGIN_CASH = 50.0
active_buy_order_id = None

def main(args=sys.argv):
  global active_buy_order_id
  locale.setlocale(locale.LC_ALL, '')
  crypto_securities = [
    #'LTC', 'ETC', 'ETH', 'BCH', 'BSV', 'BTC',
    'LTC', 'ETC', 'ETH', 'BCH', 'BSV', 'BTC',
    #'ETC'
  ]
  #sec = random.choice(crypto_securities)
  sec = str(os.environ['USE_SECURITY']) if 'USE_SECURITY' in os.environ else random.choice(crypto_securities)
  history = get_crypto_history(sec)

  history_avg_long = moving_avg_6hr(history)
  #history_avg_long = moving_avg_12hr(history)
  history_avg_short = moving_avg_1hr(history)

  if 'sim' in args:
    sim_strat(sec, history, history_avg_long, history_avg_short)
    return

  # Actually begin buying using sim_simplest strategy
  check_robin_login()
  signal.signal(signal.SIGINT, on_exit)

  def purchase_decision(history, history_avg_short, history_avg_long, i=-1):
    if history[i] < history_avg_short[i]:
      return 'buy b/c now:{} < short avg:{}'.format( history[i], round(history_avg_short[i], 4) )

    if history[i] > history_avg_long[i]:
      return 'sell b/c now:{} > long avg:{}'.format( history[i], round(history_avg_long[i], 4) )

    return 'hold'

  def do_buy(cash, buy_sec, buy_price, buy_quantity, timeout_seconds=800):
    global active_buy_order_id
    # returns shares, cash
    active_order_id = None
    while not active_order_id:
      order = robinhood.orders.order_buy_crypto_limit(
        buy_sec, buy_quantity, buy_price,
        timeInForce='gtc',
      )
      if 'Order quantity has invalid increment' in printable(order) or 'Ensure that there are no more than' in printable(order):
        buy_quantity = float(str(buy_quantity)[:-1])
        print('WARN: reduced buy_quantity={}'.format(buy_quantity))
        time.sleep(0.5)
        continue

      if not ('id' in order):
        print('order={}'.format(printable(order)))

      # Contains an "id", "ref_id", 

      active_order_id = order['id']

    # Wait for order to be filled
    active_buy_order_id = active_order_id
    print('Waiting for {} buy order {} to be filled'.format(buy_sec, active_order_id), end='', flush=True)
    order_state = 'confirmed'
    order_status = None
    polled_seconds = 0
    cancel_buy = False
    poll_seconds = 15
    while order_state != 'filled' and order_state != 'canceled':
      print('.', end='', flush=True)
      if polled_seconds >= timeout_seconds:
        cancel_buy = True
        break

      time.sleep(poll_seconds)
      polled_seconds += poll_seconds

      order_status = robinhood.orders.get_crypto_order_info(active_order_id)
      # print('order_status={}'.format(printable(order_status)))
      order_state = order_status['state'].lower().strip()
    print('')

    if cancel_buy:
      print('CANCELLING BUY ORDER (timout after {} seconds)'.format(polled_seconds))
      order_state = 'unk'
      while order_state != 'canceled':
        print('.', end='', flush=True)
        order_status = robinhood.orders.cancel_crypto_order(active_order_id)
        if 'state' in order_status:
          order_state = order_status['state'].lower().strip()
        elif 'Order cannot be canceled at this time' in printable(order_status):
          break;
        else:
          print('order_status={}'.format(printable(order_status)))

      # Buy timed out, return NO shares and beginning cash
      return 0.0, cash
    else:

      # Buy executed, return ALL shares and NO cash
      return buy_quantity, 0.0


  def do_sell(cash, sell_sec, sell_price, sell_quantity):
    # returns shares, cash
    active_order_id = None
    while not active_order_id:
      order = robinhood.orders.order_sell_crypto_limit(
        sell_sec, sell_quantity, sell_price,
        timeInForce='gtc',
      )
      if 'Insufficient holdings.' in printable(order):
        print('!', end='', flush=True)
        time.sleep(5)
        continue

      if not 'id' in order:

        if 'Order quantity has invalid increment' in printable(order) or 'there are no more than' in printable(order):
          sell_quantity = float(str(sell_quantity)[:-1])
          print('WARN: reduced sell_quantity={}'.format(sell_quantity))
          time.sleep(0.5)

        else:
          print('WARN: order={}'.format(printable(order)))
          time.sleep(2)

        continue

      # Contains an "id", "ref_id", 

      active_order_id = order['id']

    # Wait for order to be filled
    print('Waiting for {} sell order {} to be filled'.format(sell_sec, active_order_id), end='', flush=True)
    order_state = 'confirmed'
    order_status = None
    polled_seconds = 0
    poll_seconds = 15
    while order_state != 'filled' and order_state != 'canceled':
      print('.', end='', flush=True)

      time.sleep(poll_seconds)
      polled_seconds += poll_seconds

      order_status = robinhood.orders.get_crypto_order_info(active_order_id)
      # print('order_status={}'.format(printable(order_status)))
      order_state = order_status['state'].lower().strip()
    print('')

    # Sell completed, return NO shares and ALL cash
    return 0.0, sell_quantity * sell_price

  begin_cash = float(os.environ['ROBIN_SPEC_CASH']) if 'ROBIN_SPEC_CASH' in os.environ else 50.0
  cash = begin_cash
  shares = 0.0
  print('sec={} cash={}'.format(sec, cash))

  while True:
    # Query new data
    history = get_crypto_history(sec)
    history_avg_long = moving_avg_6hr(history)
    history_avg_short = moving_avg_1hr(history)

    print('')
    print('cash={} shares={}'.format(cash, shares))
    decision = purchase_decision(history, history_avg_short, history_avg_long)
    print('decision = {}'.format(decision))
    price_per_share = round(history[-1], 2)
    if 'buy' in decision:
      if cash > 1.00:
        new_shares = cash / price_per_share
        print('BUY {} shares for {}'.format(new_shares, cash))
        shares, cash = do_buy(cash, sec, price_per_share, new_shares)
      else:
        print('CANNOT BUY; no cash')
    
    elif 'sell' in decision:
      shares = get_free_shares(sec)
      if shares > 0.0:
        new_cash = shares * price_per_share
        print('SELL {} shares for {}'.format(shares, new_cash))
        shares, cash = do_sell(cash, sec, price_per_share, shares)

        subprocess.run([
          '/j/bin/ding',
          '{} {} ({})'.format(
            sec,
            locale.currency(cash),
            locale.currency(cash - begin_cash)
          )
        ])

      else:
        print('CANNOT SELL; no shares')

    else:
      print('HOLDING')

    # Wait 5 mins
    time.sleep(300)




if __name__ == '__main__':
  main()




