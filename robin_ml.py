
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

# ML-dependencies:
# python -m pip install --user numpy pandas keras tensorflow tensorflow-cpu
from random import randint
from numpy import array
from numpy import argmax
from pandas import concat
from pandas import DataFrame
from tensorflow import keras
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM
from tensorflow.keras.layers import Dense

# python -m pip install --user termplotlib
import termplotlib

def printable(obj):
  return json.dumps(obj, sort_keys=True, indent=2);

# generate a sequence of random numbers in [0, 99]
# def generate_sequence(length=25):
#     return [randint(0, 99) for _ in range(length)]

# From last week's 5-minute records, generate a random 2-hour sequence
def generate_sequence(length=25):
  global q
  begin_i = randint(0, len(q)-length)
  end_i = begin_i + length
  seq_q = q[begin_i:end_i]

  return [int(float(x['close_price'])*100.0) for x in seq_q]

MAX_VAL = int(200 * 100)

# one hot encode sequence
def one_hot_encode(sequence, n_unique=MAX_VAL):
    encoding = list()
    for value in sequence:
        vector = [0 for _ in range(n_unique)]
        vector[value] = 1
        encoding.append(vector)
    return array(encoding)

# decode a one hot encoded string
def one_hot_decode(encoded_seq):
    return [argmax(vector) for vector in encoded_seq]

# generate data for the lstm
def generate_data():
    # generate sequence
    sequence = generate_sequence()
    # one hot encode
    encoded = one_hot_encode(sequence)
    # create lag inputs
    df = DataFrame(encoded)
    df = concat([df.shift(4), df.shift(3), df.shift(2), df.shift(1), df], axis=1)
    # remove non-viable rows
    values = df.values
    values = values[5:,:]
    # convert to 3d for input
    x = values.reshape(len(values), 5, MAX_VAL)
    # drop last value from y
    y = encoded[4:-1,:]
    return x, y


q = []
def main(args=sys.argv):
  global active_buy_order_id
  global active_mv_sec
  global q

  # Ensure generate_device_token always gives
  # the same machine name.
  # https://github.com/jmfernandes/robin_stocks/blob/master/robin_stocks/robinhood/authentication.py
  random.seed(a="123", version=2)

  login = robinhood.login(
    'email@example.com',
    'some-pw-or-token',
  )

  random.seed(a=str(time.time()), version=2)

  crypto_securities = [
    #'LTC', 'ETC', 'ETH', 'BCH', 'BSV', 'BTC',
    'ETC'
  ]
  mv_sec = random.choice(crypto_securities)
  # https://robin-stocks.readthedocs.io/en/latest/robinhood.html#robin_stocks.robinhood.crypto.get_crypto_historicals
  q = robinhood.crypto.get_crypto_historicals(
    #mv_sec, interval='5minute', span='week'
    mv_sec, interval='hour', span='month'
  )
  current_n = 25
  nontrain_q = q[-current_n:]
  q = q[0:len(q)-current_n]
  print('Dataset len = {}'.format(len(q)))

  # define model
  model = Sequential()
  model.add(LSTM(50, batch_input_shape=(5, 5, MAX_VAL), stateful=True))
  model.add(Dense(MAX_VAL, activation='softmax'))
  model.compile(loss='categorical_crossentropy', optimizer='adam', metrics=['acc'])
  # fit model
  for i in range(3000):
      x, y = generate_data()
      model.fit(x, y, epochs=2, batch_size=5, verbose=2, shuffle=False)
      model.reset_states()
  
  # evaluate model on new data
  q = nontrain_q
  x, y = generate_data()
  yhat = model.predict(x, batch_size=5)
  print('mv_sec = {}'.format(mv_sec))
  print('Expected:  %s' % one_hot_decode(y))
  print('Predicted: %s' % one_hot_decode(yhat))

  y_arr = [int(i.strip()) for i in str(one_hot_decode(y))[1:-1].split(",")]
  yhat_arr = [int(i.strip()) for i in str(one_hot_decode(yhat))[1:-1].split(",")]
  x_arr = [x for x in range(0, len(y_arr))]

  fig = termplotlib.figure()
  fig.plot(x_arr, y_arr, width=80, height=30)
  fig.show()

  fig = termplotlib.figure()
  fig.plot(x_arr, yhat_arr, width=80, height=30)
  fig.show()

  return

  active_buy_order_id = ''
  active_mv_sec = 'NULL'

  p = robinhood.profiles.load_account_profile()
  cash = float(p['buying_power'])

  if 'ROBIN_SPEC_CASH' in os.environ:
    cash = float(os.environ['ROBIN_SPEC_CASH'])

  crypto_securities = [
    'LTC', 'ETC', 'ETH', 'BCH', 'BSV', 'BTC',
  ]

  while True:
    time.sleep(0.5)
    
    # Pick a security at random
    mv_sec = random.choice(crypto_securities)
    prediction_minutes = 4*60
    print('Predicting {} using last {}h of data'.format( mv_sec, round(prediction_minutes/60, 1) ))

    q = robinhood.crypto.get_crypto_historicals(mv_sec, interval='5minute', span='day')
    # Grab last prediction_minutes records
    n = int(prediction_minutes / 5)
    q = q[-n:]

    #print('q={}'.format(printable(q)))

    # Predict the next hour & wait to check if within some percent of truth
    # See https://towardsdatascience.com/getting-rich-quick-with-machine-learning-and-stock-market-predictions-696802da94fe
    # https://github.com/yacoubb/stock-trading-ml
    

if __name__ == '__main__':
  main()

