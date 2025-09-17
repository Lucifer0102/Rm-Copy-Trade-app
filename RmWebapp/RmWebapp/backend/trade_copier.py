import logging
import time
from datetime import datetime
import json

logger = logging.getLogger(__name__)

class TradeCopier:
    def __init__(self, database, mt5_manager, socketio):
        self.db = database
        self.mt5 = mt5_manager
        self.socketio = socketio
        self.copied_trades = {}  # {provider_ticket: [receiver_tickets]}
        self.settings = self.db.get_settings()
        
    def update_settings(self, new_settings):
        """Update copier settings"""
        self.settings = new_settings
        logger.info(f"Settings updated: {new_settings}")
    
    def map_symbol(self, symbol, provider_broker, receiver_broker):
        """Map symbol from provider to receiver broker"""
        # Check for specific mapping
        mappings = self.db.get_symbol_mappings()
        
        for mapping in mappings:
            if mapping['provider_symbol'] == symbol:
                if mapping['broker_name'] == receiver_broker or not mapping['broker_name']:
                    return mapping['receiver_symbol']
        
        # Default mapping (add suffix/prefix if needed)
        symbol_suffix = self.settings.get('symbol_suffix', '')
        symbol_prefix = self.settings.get('symbol_prefix', '')
        
        return f"{symbol_prefix}{symbol}{symbol_suffix}"
    
    def calculate_lot_size(self, provider_volume, provider_balance, receiver_balance):
        """Calculate lot size based on settings"""
        lot_mode = self.settings.get('lot_mode', 'multiplier')
        
        if lot_mode == 'same':
            volume = provider_volume
        elif lot_mode == 'fixed':
            volume = self.settings.get('fixed_lot', 0.01)
        elif lot_mode == 'multiplier':
            multiplier = self.settings.get('lot_multiplier', 1.0)
            volume = provider_volume * multiplier
        elif lot_mode == 'ratio':
            # Calculate based on balance ratio
            if provider_balance > 0:
                ratio = receiver_balance / provider_balance
                volume = provider_volume * ratio
            else:
                volume = provider_volume
        elif lot_mode == 'risk':
            # Risk-based calculation
            risk_percent = self.settings.get('risk_percent', 1.0) / 100
            volume = (receiver_balance * risk_percent) / 1000  # Simplified risk calculation
        else:
            volume = provider_volume
        
        # Apply min/max limits
        min_lot = self.settings.get('min_lot', 0.01)
        max_lot = self.settings.get('max_lot', 100.0)
        
        if volume < min_lot:
            volume = min_lot
        elif volume > max_lot:
            volume = max_lot
        
        return volume
    
    def should_copy_trade(self, trade_type, symbol):
        """Check if trade should be copied based on filters"""
        # Check trade type filter
        if trade_type in ['BUY', 'BUY_LIMIT', 'BUY_STOP']:
            if not self.settings.get('copy_buy', True):
                return False
        elif trade_type in ['SELL', 'SELL_LIMIT', 'SELL_STOP']:
            if not self.settings.get('copy_sell', True):
                return False
        
        # Check symbol filter
        allowed_symbols = self.settings.get('allowed_symbols', '')
        if allowed_symbols:
            symbols_list = [s.strip() for s in allowed_symbols.split(',')]
            if symbol not in symbols_list:
                return False
        
        blocked_symbols = self.settings.get('blocked_symbols', '')
        if blocked_symbols:
            symbols_list = [s.strip() for s in blocked_symbols.split(',')]
            if symbol in symbols_list:
                return False
        
        return True
    
    def get_opposite_trade_type(self, trade_type):
        """Get opposite trade type for reverse trading"""
        opposite_map = {
            'BUY': 'SELL',
            'SELL': 'BUY',
            'BUY_LIMIT': 'SELL_LIMIT',
            'SELL_LIMIT': 'BUY_LIMIT',
            'BUY_STOP': 'SELL_STOP',
            'SELL_STOP': 'BUY_STOP'
        }
        return opposite_map.get(trade_type, trade_type)
    
    def copy_trades(self, provider_id, receiver_id, provider_trades):
        """Copy trades from provider to receiver"""
        try:
            # Get account info
            provider_account = self.db.get_account(provider_id)
            receiver_account = self.db.get_account(receiver_id)
            
            if not provider_account or not receiver_account:
                logger.error(f"Account not found: Provider {provider_id} or Receiver {receiver_id}")
                return
            
            # Get receiver's existing positions
            receiver_positions = self.mt5.get_positions(receiver_id)
            receiver_orders = self.mt5.get_orders(receiver_id)
            
            # Create lookup for existing trades
            receiver_trades_map = {}
            for pos in receiver_positions:
                comment = pos.get('comment', '')
                if 'TKT=' in comment:
                    # Extract provider ticket from comment
                    start = comment.find('TKT=') + 4
                    end = comment.find(']', start)
                    if end > start:
                        provider_ticket = int(comment[start:end])
                        receiver_trades_map[provider_ticket] = pos
            
            for order in receiver_orders:
                comment = order.get('comment', '')
                if 'TKT=' in comment:
                    start = comment.find('TKT=') + 4
                    end = comment.find(']', start)
                    if end > start:
                        provider_ticket = int(comment[start:end])
                        receiver_trades_map[provider_ticket] = order
            
            # Process provider trades
            for trade in provider_trades:
                provider_ticket = trade['ticket']
                
                # Check if trade already copied
                if provider_ticket in receiver_trades_map:
                    # Update SL/TP if changed
                    existing_trade = receiver_trades_map[provider_ticket]
                    if existing_trade['sl'] != trade['sl'] or existing_trade['tp'] != trade['tp']:
                        self.mt5.modify_position(
                            receiver_id,
                            existing_trade['ticket'],
                            trade['sl'],
                            trade['tp']
                        )
                        logger.info(f"Modified trade {existing_trade['ticket']} SL/TP")
                    continue
                
                # Check if should copy
                if not self.should_copy_trade(trade['type'], trade['symbol']):
                    logger.info(f"Trade {provider_ticket} filtered out")
                    continue
                
                # Map symbol
                mapped_symbol = self.map_symbol(
                    trade['symbol'],
                    provider_account.get('broker', ''),
                    receiver_account.get('broker', '')
                )
                
                # Calculate lot size
                volume = self.calculate_lot_size(
                    trade['volume'],
                    provider_account['balance'],
                    receiver_account['balance']
                )
                
                # Determine trade type (handle opposite trading)
                trade_type = trade['type']
                if self.settings.get('opposite_trades', False):
                    trade_type = self.get_opposite_trade_type(trade_type)
                
                # Create comment with provider ticket reference
                comment = f"[TKT={provider_ticket}]"
                if self.settings.get('opposite_trades', False):
                    comment += "[OPPOSITE]"
                
                # Set magic number
                magic = self.settings.get('magic_number', provider_id)
                
                # Place the trade
                if trade_type in ['BUY', 'SELL']:
                    # Market order
                    result = self.mt5.place_trade(
                        receiver_id,
                        trade_type,
                        mapped_symbol,
                        volume,
                        trade['sl'],
                        trade['tp'],
                        comment,
                        magic
                    )
                else:
                    # Pending order
                    result = self.mt5.place_pending_order(
                        receiver_id,
                        trade_type,
                        mapped_symbol,
                        volume,
                        trade.get('price_open', 0),
                        trade['sl'],
                        trade['tp'],
                        comment,
                        magic
                    )
                
                if result:
                    # Log successful copy
                    self.db.log_copied_trade({
                        'provider_id': provider_id,
                        'receiver_id': receiver_id,
                        'provider_ticket': provider_ticket,
                        'receiver_ticket': result,
                        'symbol': mapped_symbol,
                        'type': trade_type,
                        'volume': volume,
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    # Emit event
                    self.socketio.emit('trade_copied', {
                        'provider': provider_account['name'],
                        'receiver': receiver_account['name'],
                        'symbol': mapped_symbol,
                        'type': trade_type,
                        'volume': volume,
                        'ticket': result
                    })
                    
                    logger.info(f"Copied trade {provider_ticket} to {receiver_account['name']} as {result}")
                else:
                    logger.error(f"Failed to copy trade {provider_ticket} to {receiver_account['name']}")
            
            # Close trades that no longer exist on provider
            if self.settings.get('close_on_provider_close', True):
                self.close_missing_trades(
                    provider_trades,
                    receiver_trades_map,
                    receiver_id
                )
            
        except Exception as e:
            logger.error(f"Error copying trades: {e}")
            self.socketio.emit('error', {
                'message': f"Copy error: {str(e)}",
                'provider': provider_id,
                'receiver': receiver_id
            })
    
    def close_missing_trades(self, provider_trades, receiver_trades_map, receiver_id):
        """Close receiver trades that no longer exist on provider"""
        try:
            # Get current provider tickets
            provider_tickets = {trade['ticket'] for trade in provider_trades}
            
            # Find receiver trades to close
            for provider_ticket, receiver_trade in receiver_trades_map.items():
                if provider_ticket not in provider_tickets:
                    # Close the trade
                    if 'price_open' in receiver_trade and receiver_trade.get('price_current'):
                        # It's a position
                        if self.mt5.close_position(receiver_id, receiver_trade['ticket']):
                            logger.info(f"Closed position {receiver_trade['ticket']} (provider trade {provider_ticket} closed)")
                            
                            self.socketio.emit('trade_closed', {
                                'receiver_ticket': receiver_trade['ticket'],
                                'provider_ticket': provider_ticket,
                                'reason': 'Provider closed'
                            })
                    else:
                        # It's a pending order
                        if self.mt5.delete_order(receiver_id, receiver_trade['ticket']):
                            logger.info(f"Deleted order {receiver_trade['ticket']} (provider order {provider_ticket} deleted)")
                            
                            self.socketio.emit('order_deleted', {
                                'receiver_ticket': receiver_trade['ticket'],
                                'provider_ticket': provider_ticket,
                                'reason': 'Provider deleted'
                            })
            
        except Exception as e:
            logger.error(f"Error closing missing trades: {e}")
    
    def sync_all_accounts(self):
        """Sync all provider-receiver pairs"""
        try:
            providers = self.db.get_provider_accounts()
            receivers = self.db.get_receiver_accounts()
            
            for provider in providers:
                if not provider['enabled']:
                    continue
                
                # Get provider trades
                provider_trades = self.mt5.get_positions(provider['id'])
                provider_orders = self.mt5.get_orders(provider['id'])
                
                # Copy pending orders if enabled
                if self.settings.get('copy_pending', True):
                    provider_trades.extend(provider_orders)
                
                # Copy to each receiver
                for receiver in receivers:
                    if receiver['enabled']:
                        self.copy_trades(
                            provider['id'],
                            receiver['id'],
                            provider_trades
                        )
            
            return True
            
        except Exception as e:
            logger.error(f"Error syncing accounts: {e}")
            return False
    
    def get_copy_statistics(self):
        """Get copying statistics"""
        try:
            stats = {
                'total_copied': self.db.get_total_copied_trades(),
                'active_copies': len(self.copied_trades),
                'success_rate': self.db.get_copy_success_rate(),
                'total_volume': self.db.get_total_copied_volume(),
                'profit_loss': self.db.get_total_profit_loss()
            }
            return stats
            
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {}