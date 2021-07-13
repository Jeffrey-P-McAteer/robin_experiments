#!/usr/bin/env python

# ROBIN_BS_PERCENT=0.005 ROBIN_SPEC_CASH=25.0 robin idle

# Misc environment variables we read:
# 
# ROBIN_BS_PERCENT=0.01 # Purchase 1% below market price & sell 1% above
# ROBIN_SPEC_CASH=10.0 # Use no greater than $10 to buy securities
# USE_SECURITY=BTC # Only buy bitcoin, skip volatility measurements
# ROBIN_TIMEOUT_SEC=2700 # timeout after 45 mins

# python -m pip install --user robin_stocks
# https://robin-stocks.readthedocs.io/en/latest/robinhood.html
from robin_stocks import robinhood

import sys
import random
import json
import time
import locale
import os
import subprocess
import signal
import io
from datetime import datetime, timezone

locale.setlocale(locale.LC_ALL, '')

def printable(obj):
  return json.dumps(obj, sort_keys=True, indent=2);

def read_val(name, def_val=0.0):
  filename = '/tmp/.robin_{}'.format(name)
  if not os.path.exists(filename):
    return def_val

  with open(filename, 'r') as fd:
    return float(fd.read().strip())

def write_val(name, val):
  filename = '/tmp/.robin_{}'.format(name)
  with open(filename, 'w') as fd:
    fd.write('{}'.format(val))

def read_str(name, def_str=''):
  filename = '/tmp/.robin_{}'.format(name)
  if not os.path.exists(filename):
    return def_str

  with open(filename, 'r') as fd:
    return fd.read().strip()

def write_str(name, val):
  filename = '/tmp/.robin_{}'.format(name)
  with open(filename, 'w') as fd:
    fd.write('{}'.format(val))

def append_str(name, addtl_val):
  write_str(name, read_str(name) + addtl_val)

def de_append_str(name, val):
  write_str(name, read_str(name).replace(val, ''))

def get_max_price_usd(sec):
  q = robinhood.crypto.get_crypto_historicals(sec, interval='5minute', span='day')
  hours = 6
  n = int((hours*60) / 5)
  q = q[-n:]
  highest_price_usd = 0.0
  for x in q:
    p = float(x['high_price'])
    if p > highest_price_usd:
      highest_price_usd = p
  return highest_price_usd


def on_exit(sig, frame):
  global active_buy_order_id
  global active_mv_sec
  
  de_append_str('actively_trading', active_mv_sec)

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


def idle_speculation():
  global active_buy_order_id
  global active_mv_sec

  active_buy_order_id = ''
  active_mv_sec = 'NULL'

  p = robinhood.profiles.load_account_profile()
  cash = float(p['buying_power'])

  if 'ROBIN_SPEC_CASH' in os.environ:
    cash = float(os.environ['ROBIN_SPEC_CASH'])

  buy_sell_percent = 0.0051
  if 'ROBIN_BS_PERCENT' in os.environ:
    buy_sell_percent = abs(float(os.environ['ROBIN_BS_PERCENT']))

  poll_seconds = 10
  # if we wait this long + buy is not executed, cancel it + go back to beginning
  buy_order_timeout_seconds = 22 * 60
  if 'ROBIN_TIMEOUT_SEC' in os.environ:
    buy_order_timeout_seconds = abs(float(os.environ['ROBIN_TIMEOUT_SEC']))

  always_use_security = None
  if 'USE_SECURITY' in os.environ:
    always_use_security = os.environ['USE_SECURITY']

  volatility_history_minutes = 45

  # refuse to buy securities near their highest price over last 4 hours.
  # eg. do not buy a security above $98 if traded at 4h $100 earlier
  #max_bid_percent = 0.989
  max_bid_percent = 0.999

  crypto_securities = [
    'LTC', 'ETC', 'ETH', 'BCH', 'BSV', 'BTC',
    # 'DOGE', # Too small for 0.5% change to profit
    # 'BTC', 'ETH', 'BSV',
  ]

  if always_use_security and not always_use_security in crypto_securities:
    print('Exiting b/c {} not in {}'.format(always_use_security, crypto_securities))
    return

  print('Speculating {} with {}% change'.format(locale.currency(cash), buy_sell_percent * 100.0))

  total_profit_usd = read_val('total_profit_usd')
  active_order_id = None
  avoid_securities = []

  while True:
    
    now_bp = 0.0
    while True:
      p = robinhood.profiles.load_account_profile()
      now_bp = float(p['buying_power'])
      if now_bp >= cash:
        break;
      print('Waiting for buying power (want {} have {})'.format(
        locale.currency(cash), locale.currency(now_bp),
      ))
      time.sleep(10)
      

    if not always_use_security:

      # Reset avoid_securities every now and then
      if random.choice([True, True, False, False, False, False, False]):
        avoid_securities = []

      # Find most volatile security
      most_volatile = ('NULL', 0.0)
      for sec in crypto_securities:
        # Do not consider active securities
        if sec in read_str('actively_trading'):
          print('Not considering {} because it is in actively_trading'.format(sec))
          continue

        # Do not consider these
        if sec in avoid_securities:
          print('Not considering {} because it is in avoid_securities'.format(sec))
          continue

        q = robinhood.crypto.get_crypto_historicals(sec, interval='5minute', span='day')
        # print('q={}'.format(printable(q)))
        # Only use last half hour's data (last 6 items)
        n = int(volatility_history_minutes / 5)
        q = q[-n:]
        
        avg_range_usd = 0.0
        for x in q:
          avg_range_usd += float(x['high_price']) - float(x['low_price'])
        avg_range_usd /= float(n)

        last_price_usd = float(q[-1]['close_price'])
        avg_range_percent = (avg_range_usd / last_price_usd) * 100.0

        if avg_range_percent > most_volatile[1]:
          most_volatile = (sec, avg_range_percent)

    else:
      most_volatile = (always_use_security, 999.0)

    mv_sec, mv_percent_change = most_volatile
    if 'NULL' in mv_sec:
      # Re-try avoided securities
      if len(avoid_securities) > 0:
        avoid_securities = []
        continue

      print('Could not find a security to speculate on: mv_sec={}'.format(mv_sec))
      break
    active_order_id = None

    active_mv_sec = mv_sec
    append_str('actively_trading', mv_sec)

    print('Most volatile security is {} at {}% change '.format(mv_sec, round(mv_percent_change, 1)))
    time.sleep(1)

    q = robinhood.crypto.get_crypto_quote(mv_sec)
    # print('q={}'.format(printable(q)))
    current_bid_price_usd = float(q['bid_price'])
    current_ask_price_usd = float(q['ask_price'])

    # Bid 0.5% lower
    my_bid_price_usd = round(current_bid_price_usd * (1.0 - buy_sell_percent), 2)
    # Check historicals, exit if my bid price is within 4% of get_max_price_usd()
    max_sec_price = get_max_price_usd(mv_sec)
    max_bid = max_bid_percent * max_sec_price
    if my_bid_price_usd >= max_bid:
      # print('Lowering bid {} to {} b/c price is near max price: {}'.format(
      #   locale.currency(my_bid_price_usd),
      #   locale.currency(max_bid),
      #   locale.currency(max_sec_price)
      # ))
      print('Not bidding {} b/c price is near max: {}'.format(locale.currency(my_bid_price_usd), locale.currency(max_sec_price)))
      avoid_securities.append(mv_sec)
      de_append_str('actively_trading', mv_sec)
      time.sleep(random.randint(10, 30))
      continue # Main while loop
      #my_bid_price_usd = round(max_bid, 2)

    my_bid_security_shares = round(cash / my_bid_price_usd, 8)

    # Place order 
    print('LIMIT BUY: {} {} shares at {}/share'.format(mv_sec, round(my_bid_security_shares, 6), locale.currency(my_bid_price_usd)))
    while not active_order_id:
      order = robinhood.orders.order_buy_crypto_limit(
        mv_sec, my_bid_security_shares, my_bid_price_usd,
        timeInForce='gtc',
      )
      if 'Order quantity has invalid increment' in printable(order):
        my_bid_security_shares = float(str(my_bid_security_shares)[:-1])
        print('WARN: reduced my_bid_security_shares={}'.format(my_bid_security_shares))
        time.sleep(1)
        continue

      if not ('id' in order):
        print('order={}'.format(printable(order)))

      # Contains an "id", "ref_id", 

      active_order_id = order['id']

    # Wait for order to be filled
    active_buy_order_id = active_order_id
    print('Waiting for buy order {} to be filled'.format(active_order_id), end='', flush=True)
    order_state = 'confirmed'
    order_status = None
    polled_seconds = 0
    cancel_buy = False
    considered_increased_buy_because_close = False
    while order_state != 'filled' and order_state != 'canceled':
      print('.', end='', flush=True)
      if polled_seconds >= buy_order_timeout_seconds:
        # If (current_bid_price_usd-my_bid_price_usd)/current_bid_price_usd
        # is less than 0.5*buy_sell_percent, go back 180 seconds and continue
        if not considered_increased_buy_because_close:
          considered_increased_buy_because_close = True
          q = robinhood.crypto.get_crypto_quote(mv_sec)
          current_bid_price_usd = float(q['bid_price'])
          x = (current_bid_price_usd-my_bid_price_usd)/current_bid_price_usd
          if x < 0.5*buy_sell_percent:
            # is very close, go back 180 seconds
            polled_seconds -= 180
            print('!', end='', flush=True)
            continue

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

      de_append_str('actively_trading', mv_sec)
      time.sleep(random.randint(10, 20))
      continue # Main while loop

    print('BUY ORDER FILLED')
    time.sleep(15)

    # Place limit sell at executed purchase price +0.5%
    purchase_price_usd = float(order_status['price'])
    my_ask_price_usd = round( purchase_price_usd * (1.001 + buy_sell_percent), 2)
    my_bid_security_shares = float(order_status['quantity'])

    print('LIMIT SELL: {} {} shares at {}/share'.format(mv_sec, round(my_bid_security_shares, 6), locale.currency(my_ask_price_usd)))
    active_order_id = None

    while not active_order_id:
      order = robinhood.orders.order_sell_crypto_limit(
        mv_sec, my_bid_security_shares, my_ask_price_usd,
        timeInForce='gtc',
      )

      if 'Insufficient holdings.' in printable(order):
        print('!', end='', flush=True)
        time.sleep(5)
        continue

      if not 'id' in order:
        print('WARN: order={}'.format(printable(order)))
        time.sleep(2)

        if 'Order quantity has invalid increment' in printable(order):
          my_bid_security_shares = float(str(my_bid_security_shares)[:-1])
          print('WARN: reduced my_bid_security_shares={}'.format(my_bid_security_shares))

        continue

      active_order_id = order['id']

    print('Waiting for sell order {} to be filled'.format(active_order_id), end='', flush=True)
    order_state = 'confirmed'
    order_status = None
    while order_state != 'filled' and order_state != 'canceled':
      print('.', end='', flush=True)
      time.sleep(poll_seconds)

      order_status = robinhood.orders.get_crypto_order_info(active_order_id)
      #print('order_status={}'.format(printable(order_status)))
      order_state = order_status['state'].lower().strip()
    print('')

    print('SELL ORDER FILLED')
    de_append_str('actively_trading', mv_sec)
    avoid_securities.append(mv_sec)

    sell_price_usd = float(order_status['price'])

    # Report status
    profit_usd = (sell_price_usd - purchase_price_usd) * my_bid_security_shares
    total_profit_usd = read_val('total_profit_usd')
    total_profit_usd += profit_usd
    print('SALE PROFIT: {}'.format(locale.currency(profit_usd)))
    print('TOTAL RUN PROFIT: {}'.format(locale.currency(total_profit_usd)))
    
    # Other bookkeeping
    write_val('total_profit_usd', total_profit_usd)

    subprocess.run([
      '/j/bin/ding',
      '{} ({})'.format(
        locale.currency(profit_usd),
        locale.currency(total_profit_usd)
      )
    ])

    print('Sleeping...')
    time.sleep(random.randint(10, 20))


def main(args=sys.argv):
  # Ensure generate_device_token always gives
  # the same machine name.
  # https://github.com/jmfernandes/robin_stocks/blob/master/robin_stocks/robinhood/authentication.py
  random.seed(a="123", version=2)

  login = robinhood.login(
    'email@example.com',
    'some-pw-or-token',
  )

  random.seed(a=str(time.time()), version=2)
  
  if 'debug' in args:
    profileData = robinhood.load_portfolio_profile()
    print('profileData={}'.format(printable(profileData)))

    #positions = robinhood.get_open_stock_positions()
    #print('positions={}'.format(printable(positions)))

    cryptoProfile = robinhood.crypto.load_crypto_profile()
    print('cryptoProfile={}'.format(printable(cryptoProfile)))

    cryptoPositions = robinhood.crypto.get_crypto_positions()
    print('cryptoPositions={}'.format(printable(cryptoPositions)))

    cryptoQuote = robinhood.crypto.get_crypto_quote('LTC')
    print('cryptoQuote={}'.format(printable(cryptoQuote)))

    cryptoHist = robinhood.crypto.get_crypto_historicals('LTC', interval='5minute', span='day')
    print('cryptoHist={}'.format(printable(cryptoHist[0:10])))
    print('len(cryptoHist)={}'.format(len(cryptoHist)))

  else:
    if 'idle' in args:
      print('Going into idle speculation mode...')
      time.sleep(0.5)
      signal.signal(signal.SIGINT, on_exit)
      idle_speculation()

    elif 'status' in args:

      profile = robinhood.profiles.load_account_profile()
      buying_power = float(profile['buying_power'])

      print('Buying Power: {}'.format(locale.currency(buying_power)))

      print('=== crypto orders in flight ===')

      # We manually changed the file $(python -m site --user-site)/robin_stocks/robin_stocks.py
      # to silence this. Also see: rg 'Found Additional pages.' $(python -m site --user-site)
      cryptoOrders = robinhood.orders.get_all_open_crypto_orders()
      
      for order in cryptoOrders:
        #print('order={}'.format(printable(order)))

        side = order['side']
        limit_price_usd = float(order['price'])
        quantity_sec = float(order['quantity'])
        order_cost = quantity_sec*limit_price_usd
        sec = robinhood.crypto.get_crypto_quote_from_id(order['currency_pair_id'], 'symbol')
        sec = sec.replace('USD', '')

        quote = robinhood.crypto.get_crypto_quote(sec)
        ask_price = float(quote['ask_price'])
        bid_price = float(quote['bid_price'])

        created_at = datetime.strptime(order['created_at'], '%Y-%m-%dT%H:%M:%S.%f%z')
        order_age = datetime.now(timezone.utc) - created_at
        order_hours = (order_age.days * 24) + (order_age.seconds / 3600)
        order_hours = round(order_hours, 1)

        print('{:<5} {:<4} {:>8} {:>3}h > {:<8} {:<8}'.format(
          side, sec, locale.currency(limit_price_usd), int(order_hours),
          locale.currency(ask_price), locale.currency(bid_price)
        ))

        if order_hours > 24.0:
          if not 'nocancel' in args:
            yn = input('Order is >1 day old, cancel? [yN] ')
            yn = yn.lower().strip()
            if len(yn) < 1:
              yn = 'n'

            if 'y' in yn:
              print('Cancelling order {}...'.format(order['id']))
              robinhood.orders.cancel_crypto_order(order['id'])

      print('=== crypto owned ===')
      
      cryptoPositions = robinhood.crypto.get_crypto_positions()
      
      for pos in cryptoPositions:
        #print('pos={}'.format(printable(pos)))

        sec = pos['currency']['code']
        quantity = float(pos['quantity'])
        if quantity <= 0.0:
          pass # TODO this is wierd
          # for cb in pos['cost_bases']:
          #   quantity += float(cb['intraday_quantity'])
        print('{:<4} {:}'.format(
          sec, quantity,
        ))
        



if __name__ == '__main__':
  main()

