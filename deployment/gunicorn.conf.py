import os
bind = '0.0.0.0:' + os.environ.get('PORT', '8080')
workers = 1
threads = 1
timeout = 60
accesslog = None
errorlog = '-'
# One mounted volume, one service replica. Campaign locks survive requests.
