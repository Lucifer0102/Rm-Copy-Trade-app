import sqlite3
import json
import logging
from datetime import datetime, timedelta
import threading

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path='mt5_copytrade.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.init_db()
    
    def init_db(self):
        """Initialize database tables"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Accounts table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    login INTEGER UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    server TEXT NOT NULL,
                    name TEXT,
                    account_type TEXT CHECK(account_type IN ('provider', 'receiver')),
                    broker TEXT,
                    balance REAL DEFAULT 0,
                    equity REAL DEFAULT 0,
                    margin REAL DEFAULT 0,
                    free_margin REAL DEFAULT 0,
                    leverage INTEGER DEFAULT 100,
                    currency TEXT DEFAULT 'USD',
                    enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_connected TIMESTAMP
                )
            ''')
            
            # Settings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            ''')
            
            # Symbol mappings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS symbol_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_symbol TEXT NOT NULL,
                    receiver_symbol TEXT NOT NULL,
                    broker_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Trade history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    ticket INTEGER,
                    type TEXT,
                    symbol TEXT,
                    volume REAL,
                    price REAL,
                    sl REAL,
                    tp REAL,
                    profit REAL,
                    comment TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES accounts(id)
                )
            ''')
            
            # Copied trades table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS copied_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id INTEGER,
                    receiver_id INTEGER,
                    provider_ticket INTEGER,
                    receiver_ticket INTEGER,
                    symbol TEXT,
                    type TEXT,
                    volume REAL,
                    status TEXT DEFAULT 'active',
                    profit REAL DEFAULT 0,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP,
                    FOREIGN KEY (provider_id) REFERENCES accounts(id),
                    FOREIGN KEY (receiver_id) REFERENCES accounts(id)
                )
            ''')
            
            # Logs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT,
                    message TEXT,
                    details TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Insert default settings if not exist
            default_settings = {
                'lot_mode': 'multiplier',  # same, fixed, multiplier, ratio, risk
                'lot_multiplier': '1.0',
                'fixed_lot': '0.01',
                'risk_percent': '1.0',
                'min_lot': '0.01',
                'max_lot': '100.0',
                'copy_buy': 'true',
                'copy_sell': 'true',
                'copy_pending': 'true',
                'opposite_trades': 'false',
                'close_on_provider_close': 'true',
                'copy_interval': '500',  # milliseconds
                'magic_number': '123456',
                'symbol_suffix': '',
                'symbol_prefix': '',
                'allowed_symbols': '',
                'blocked_symbols': '',
                'max_slippage': '20',
                'max_spread': '50'
            }
            
            for key, value in default_settings.items():
                cursor.execute('''
                    INSERT OR IGNORE INTO settings (key, value)
                    VALUES (?, ?)
                ''', (key, value))
            
            conn.commit()
            conn.close()
            logger.info("Database initialized successfully")
    
    def add_account(self, account_data):
        """Add new account"""
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT INTO accounts (
                        login, password, server, name, account_type, broker,
                        balance, equity, margin, free_margin, leverage, currency, enabled
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    account_data['login'],
                    account_data['password'],
                    account_data['server'],
                    account_data.get('name', f"Account {account_data['login']}"),
                    account_data['account_type'],
                    account_data.get('broker', ''),
                    account_data.get('balance', 0),
                    account_data.get('equity', 0),
                    account_data.get('margin', 0),
                    account_data.get('free_margin', 0),
                    account_data.get('leverage', 100),
                    account_data.get('currency', 'USD'),
                    account_data.get('enabled', True)
                ))
                
                account_id = cursor.lastrowid
                conn.commit()
                conn.close()
                
                self.log('INFO', f"Account {account_data['login']} added successfully")
                return account_id
                
            except sqlite3.IntegrityError:
                logger.error(f"Account {account_data['login']} already exists")
                return None
            except Exception as e:
                logger.error(f"Error adding account: {e}")
                return None
    
    def get_account(self, account_id):
        """Get account by ID"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
            row = cursor.fetchone()
            conn.close()
            
            return dict(row) if row else None
    
    def get_all_accounts(self):
        """Get all accounts"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM accounts ORDER BY created_at DESC')
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
    
    def get_provider_accounts(self):
        """Get all provider accounts"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM accounts 
                WHERE account_type = 'provider' AND enabled = 1
                ORDER BY created_at DESC
            ''')
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
    
    def get_receiver_accounts(self):
        """Get all receiver accounts"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM accounts 
                WHERE account_type = 'receiver' AND enabled = 1
                ORDER BY created_at DESC
            ''')
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
    
    def update_account_info(self, account_id, info):
        """Update account information"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            updates = []
            values = []
            for key, value in info.items():
                updates.append(f"{key} = ?")
                values.append(value)
            
            values.append(account_id)
            
            cursor.execute(f'''
                UPDATE accounts 
                SET {', '.join(updates)}
                WHERE id = ?
            ''', values)
            
            conn.commit()
            conn.close()
    
    def update_account_status(self, account_id, enabled):
        """Enable/disable account"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE accounts 
                SET enabled = ?
                WHERE id = ?
            ''', (enabled, account_id))
            
            conn.commit()
            conn.close()
    
    def delete_account(self, account_id):
        """Delete account"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM accounts WHERE id = ?', (account_id,))
            
            conn.commit()
            conn.close()
    
    def get_settings(self):
        """Get all settings"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT key, value FROM settings')
            rows = cursor.fetchall()
            conn.close()
            
            settings = {}
            for key, value in rows:
                # Parse boolean and numeric values
                if value.lower() in ['true', 'false']:
                    settings[key] = value.lower() == 'true'
                elif value.replace('.', '').replace('-', '').isdigit():
                    settings[key] = float(value) if '.' in value else int(value)
                else:
                    settings[key] = value
            
            return settings
    
    def update_settings(self, settings):
        """Update settings"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            for key, value in settings.items():
                cursor.execute('''
                    INSERT OR REPLACE INTO settings (key, value)
                    VALUES (?, ?)
                ''', (key, str(value)))
            
            conn.commit()
            conn.close()
            
            self.log('INFO', f"Settings updated: {settings}")
    
    def add_symbol_mapping(self, provider_symbol, receiver_symbol, broker_name=''):
        """Add symbol mapping"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO symbol_mappings (provider_symbol, receiver_symbol, broker_name)
                VALUES (?, ?, ?)
            ''', (provider_symbol, receiver_symbol, broker_name))
            
            mapping_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            return mapping_id
    
    def get_symbol_mappings(self):
        """Get all symbol mappings"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM symbol_mappings ORDER BY created_at DESC')
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
    
    def delete_symbol_mapping(self, mapping_id):
        """Delete symbol mapping"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM symbol_mappings WHERE id = ?', (mapping_id,))
            
            conn.commit()
            conn.close()
    
    def log_trade(self, trade_data):
        """Log a trade"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO trade_history (
                    account_id, ticket, type, symbol, volume, 
                    price, sl, tp, profit, comment
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade_data.get('account_id'),
                trade_data.get('ticket'),
                trade_data.get('type'),
                trade_data.get('symbol'),
                trade_data.get('volume'),
                trade_data.get('price'),
                trade_data.get('sl'),
                trade_data.get('tp'),
                trade_data.get('profit', 0),
                trade_data.get('comment', '')
            ))
            
            conn.commit()
            conn.close()
    
    def log_copied_trade(self, copy_data):
        """Log a copied trade"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO copied_trades (
                    provider_id, receiver_id, provider_ticket, receiver_ticket,
                    symbol, type, volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                copy_data['provider_id'],
                copy_data['receiver_id'],
                copy_data['provider_ticket'],
                copy_data['receiver_ticket'],
                copy_data['symbol'],
                copy_data['type'],
                copy_data['volume']
            ))
            
            conn.commit()
            conn.close()
    
    def get_trade_history(self, limit=100):
        """Get trade history"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT th.*, a.name as account_name
                FROM trade_history th
                LEFT JOIN accounts a ON th.account_id = a.id
                ORDER BY th.timestamp DESC
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
    
    def get_total_copied_trades(self):
        """Get total number of copied trades"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM copied_trades')
            count = cursor.fetchone()[0]
            conn.close()
            
            return count
    
    def get_copy_success_rate(self):
        """Calculate copy success rate"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN profit >= 0 THEN 1 ELSE 0 END) as profitable
                FROM copied_trades
                WHERE status = 'closed'
            ''')
            
            row = cursor.fetchone()
            conn.close()
            
            if row and row[0] > 0:
                return (row[1] / row[0]) * 100
            return 0
    
    def get_total_copied_volume(self):
        """Get total copied volume"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT SUM(volume) FROM copied_trades')
            volume = cursor.fetchone()[0]
            conn.close()
            
            return volume or 0
    
    def get_total_profit_loss(self):
        """Get total profit/loss"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT SUM(profit) FROM copied_trades WHERE status = "closed"')
            profit = cursor.fetchone()[0]
            conn.close()
            
            return profit or 0
    
    def get_performance_stats(self):
        """Get performance statistics"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get various stats
            stats = {}
            
            # Total trades
            cursor.execute('SELECT COUNT(*) FROM copied_trades')
            stats['total_trades'] = cursor.fetchone()[0]
            
            # Active trades
            cursor.execute('SELECT COUNT(*) FROM copied_trades WHERE status = "active"')
            stats['active_trades'] = cursor.fetchone()[0]
            
            # Win rate
            cursor.execute('''
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as wins
                FROM copied_trades
                WHERE status = 'closed'
            ''')
            row = cursor.fetchone()
            stats['win_rate'] = (row[1] / row[0] * 100) if row[0] > 0 else 0
            
            # Total profit
            cursor.execute('SELECT SUM(profit) FROM copied_trades WHERE status = "closed"')
            stats['total_profit'] = cursor.fetchone()[0] or 0
            
            # Today's trades
            cursor.execute('''
                SELECT COUNT(*) FROM copied_trades 
                WHERE DATE(timestamp) = DATE('now')
            ''')
            stats['today_trades'] = cursor.fetchone()[0]
            
            # Today's profit
            cursor.execute('''
                SELECT SUM(profit) FROM copied_trades 
                WHERE DATE(timestamp) = DATE('now') AND status = "closed"
            ''')
            stats['today_profit'] = cursor.fetchone()[0] or 0
            
            conn.close()
            return stats
    
    def log(self, level, message, details=''):
        """Add log entry"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO logs (level, message, details)
                VALUES (?, ?, ?)
            ''', (level, message, details))
            
            conn.commit()
            conn.close()
    
    def get_recent_logs(self, limit=50):
        """Get recent log entries"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM logs 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]