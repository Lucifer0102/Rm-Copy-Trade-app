# Simplified MT5 Manager - Works without MT5 connection for testing
import logging
from datetime import datetime
import time
import random

logger = logging.getLogger(__name__)

class MT5Manager:
    def __init__(self, database, socketio):
        self.db = database
        self.socketio = socketio
        self.connections = {}
        logger.info("MT5Manager initialized (simplified version)")
        
    def add_account(self, login, password, server, account_type, name=""):
        """Add account without MT5 connection"""
        try:
            # Just save to database without MT5 connection
            account_data = {
                'login': int(login),
                'password': password,
                'server': server,
                'name': name or f"Account {login}",
                'account_type': account_type,
                'balance': 10000.00,  # Demo values
                'equity': 10000.00,
                'margin': 0,
                'free_margin': 10000.00,
                'leverage': 100,
                'currency': 'USD',
                'enabled': True
            }
            
            account_id = self.db.add_account(account_data)
            
            if account_id:
                logger.info(f"Account {login} added successfully (ID: {account_id})")
                self.socketio.emit('account_connected', {
                    'account_id': account_id,
                    'login': login,
                    'status': 'connected'
                })
                return account_id
            else:
                logger.error(f"Failed to add account {login} to database")
                return None
                
        except Exception as e:
            logger.error(f"Error in add_account: {str(e)}")
            return None
    
    def remove_account(self, account_id):
        """Remove account"""
        try:
            self.db.delete_account(account_id)
            if account_id in self.connections:
                del self.connections[account_id]
            logger.info(f"Account {account_id} removed")
        except Exception as e:
            logger.error(f"Error removing account: {e}")
    
    def connect_account(self, account_id, login, password, server):
        """Simulate connection (no actual MT5)"""
        try:
            self.connections[account_id] = {
                'login': login,
                'connected': True,
                'last_ping': datetime.now()
            }
            logger.info(f"Account {login} marked as connected (simulation)")
            return True
        except Exception as e:
            logger.error(f"Error in connect_account: {e}")
            return False
    
    def get_positions(self, account_id):
        """Get positions (returns empty for now)"""
        return []
    
    def get_orders(self, account_id):
        """Get orders (returns empty for now)"""
        return []
    
    def place_trade(self, account_id, trade_type, symbol, volume, sl=0, tp=0, comment="", magic=0):
        """Simulate placing trade"""
        logger.info(f"Would place {trade_type} trade: {symbol} {volume} lots")
        return random.randint(100000, 999999)  # Return fake ticket number
    
    def place_pending_order(self, account_id, order_type, symbol, volume, price, sl=0, tp=0, comment="", magic=0):
        """Simulate placing pending order"""
        logger.info(f"Would place {order_type} order: {symbol} {volume} lots at {price}")
        return random.randint(100000, 999999)
    
    def close_position(self, account_id, ticket):
        """Simulate closing position"""
        logger.info(f"Would close position {ticket}")
        return True
    
    def modify_position(self, account_id, ticket, sl, tp):
        """Simulate modifying position"""
        logger.info(f"Would modify position {ticket}: SL={sl}, TP={tp}")
        return True
    
    def delete_order(self, account_id, ticket):
        """Simulate deleting order"""
        logger.info(f"Would delete order {ticket}")
        return True
    
    def get_all_active_trades(self):
        """Get all active trades (returns empty for testing)"""
        return []
    
    def normalize_volume(self, symbol, volume):
        """Normalize volume"""
        return round(volume, 2)
    
    def check_connection(self, account_id):
        """Check connection status"""
        return account_id in self.connections