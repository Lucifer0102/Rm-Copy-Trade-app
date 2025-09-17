# config.py
import os

# Server Configuration
HOST = '0.0.0.0'
PORT = 5000
DEBUG = False

# Database Configuration
DB_PATH = 'mt5_copytrade.db'

# MT5 Configuration
MT5_TIMEOUT = 60000  # milliseconds
MT5_PATH = r"C:\Program Files\MetaTrader 5"  # Default MT5 installation path

# Logging Configuration
LOG_LEVEL = 'INFO'
LOG_FILE = 'mt5_copytrade.log'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# WebSocket Configuration
SOCKETIO_ASYNC_MODE = 'threading'
SOCKETIO_PING_TIMEOUT = 60
SOCKETIO_PING_INTERVAL = 25

# Copy Trading Defaults
DEFAULT_COPY_INTERVAL = 500  # milliseconds
DEFAULT_MAGIC_NUMBER = 123456
DEFAULT_LOT_MULTIPLIER = 1.0
DEFAULT_MIN_LOT = 0.01
DEFAULT_MAX_LOT = 100.0

# Security
SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key-here-change-in-production')
CORS_ORIGINS = '*'  # Change in production