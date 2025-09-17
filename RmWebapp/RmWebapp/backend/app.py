from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import json
import threading
import time
import logging
from datetime import datetime
from database import Database
from mt5_manager import MT5Manager
from trade_copier import TradeCopier
import os

# Initialize Flask app
app = Flask(__name__, static_folder='../frontend')
CORS(app, origins="*")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize components
db = Database()
mt5_manager = MT5Manager(db, socketio)
trade_copier = TradeCopier(db, mt5_manager, socketio)

# Global state
copying_active = False
monitoring_thread = None

# Serve HTML frontend
@app.route('/')
def index():
    """Serve the main HTML file"""
    try:
        return send_from_directory('../frontend', 'index.html')
    except Exception as e:
        logger.error(f"Error serving index.html: {e}")
        return "Please create frontend/index.html file", 404

@app.route('/<path:path>')
def serve_static(path):
    """Serve static files"""
    try:
        return send_from_directory('../frontend', path)
    except Exception as e:
        logger.error(f"Error serving static file {path}: {e}")
        return jsonify({'error': 'File not found'}), 404

# REST API Routes
@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    """Get all MT5 accounts"""
    try:
        accounts = db.get_all_accounts()
        return jsonify({'success': True, 'accounts': accounts})
    except Exception as e:
        logger.error(f"Error getting accounts: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/accounts', methods=['POST'])
def add_account():
    """Add new MT5 account"""
    try:
        data = request.json
        
        # Basic validation
        if not data.get('login') or not data.get('password') or not data.get('server'):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # For now, just save to database without MT5 connection
        # This allows testing without MT5
        account_data = {
            'login': int(data['login']),
            'password': data['password'],
            'server': data['server'],
            'name': data.get('name', f"Account {data['login']}"),
            'account_type': data.get('account_type', 'receiver'),
            'balance': 0,
            'equity': 0,
            'margin': 0,
            'free_margin': 0,
            'leverage': 100,
            'currency': 'USD',
            'enabled': True
        }
        
        account_id = db.add_account(account_data)
        
        if account_id:
            # Try to connect to MT5 (optional)
            try:
                mt5_manager.connect_account(
                    account_id,
                    int(data['login']),
                    data['password'],
                    data['server']
                )
            except Exception as mt5_error:
                logger.warning(f"Could not connect to MT5: {mt5_error}")
                # Continue anyway - account is saved
            
            socketio.emit('account_added', {'account_id': account_id})
            return jsonify({'success': True, 'account_id': account_id})
        else:
            return jsonify({'success': False, 'error': 'Account already exists'}), 400
            
    except Exception as e:
        logger.error(f"Error adding account: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
def remove_account(account_id):
    """Remove MT5 account"""
    try:
        mt5_manager.remove_account(account_id)
        socketio.emit('account_removed', {'account_id': account_id})
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error removing account: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/accounts/<int:account_id>/toggle', methods=['POST'])
def toggle_account(account_id):
    """Enable/disable account for copying"""
    try:
        data = request.json
        db.update_account_status(account_id, data['enabled'])
        socketio.emit('account_toggled', {'account_id': account_id, 'enabled': data['enabled']})
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error toggling account: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get copy trading settings"""
    try:
        settings = db.get_settings()
        return jsonify({'success': True, 'settings': settings})
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Update copy trading settings"""
    try:
        data = request.json
        db.update_settings(data)
        trade_copier.update_settings(data)
        socketio.emit('settings_updated', data)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/symbol-mapping', methods=['GET'])
def get_symbol_mapping():
    """Get symbol mapping rules"""
    try:
        mappings = db.get_symbol_mappings()
        return jsonify({'success': True, 'mappings': mappings})
    except Exception as e:
        logger.error(f"Error getting symbol mappings: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/symbol-mapping', methods=['POST'])
def add_symbol_mapping():
    """Add symbol mapping rule"""
    try:
        data = request.json
        mapping_id = db.add_symbol_mapping(
            data['provider_symbol'],
            data['receiver_symbol'],
            data.get('broker_name', '')
        )
        return jsonify({'success': True, 'mapping_id': mapping_id})
    except Exception as e:
        logger.error(f"Error adding symbol mapping: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/symbol-mapping/<int:mapping_id>', methods=['DELETE'])
def delete_symbol_mapping(mapping_id):
    """Delete symbol mapping rule"""
    try:
        db.delete_symbol_mapping(mapping_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error deleting symbol mapping: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/copy/start', methods=['POST'])
def start_copying():
    """Start copy trading"""
    global copying_active, monitoring_thread
    try:
        if copying_active:
            return jsonify({'success': False, 'error': 'Copying already active'}), 400
        
        copying_active = True
        monitoring_thread = threading.Thread(target=monitor_trades)
        monitoring_thread.daemon = True
        monitoring_thread.start()
        
        socketio.emit('copying_started')
        return jsonify({'success': True, 'message': 'Copy trading started'})
    except Exception as e:
        logger.error(f"Error starting copy trading: {e}")
        copying_active = False
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/copy/stop', methods=['POST'])
def stop_copying():
    """Stop copy trading"""
    global copying_active
    try:
        copying_active = False
        socketio.emit('copying_stopped')
        return jsonify({'success': True, 'message': 'Copy trading stopped'})
    except Exception as e:
        logger.error(f"Error stopping copy trading: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trades/active', methods=['GET'])
def get_active_trades():
    """Get all active trades"""
    try:
        trades = mt5_manager.get_all_active_trades()
        return jsonify({'success': True, 'trades': trades})
    except Exception as e:
        logger.error(f"Error getting active trades: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trades/history', methods=['GET'])
def get_trade_history():
    """Get trade history"""
    try:
        history = db.get_trade_history(limit=100)
        return jsonify({'success': True, 'history': history})
    except Exception as e:
        logger.error(f"Error getting trade history: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/performance', methods=['GET'])
def get_performance():
    """Get performance statistics"""
    try:
        stats = db.get_performance_stats()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        logger.error(f"Error getting performance stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get recent logs"""
    try:
        logs = db.get_recent_logs(limit=50)
        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# WebSocket Events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'status': 'Connected to MT5 Copy Trade Server'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {request.sid}")

@socketio.on('request_update')
def handle_update_request():
    """Send current status update"""
    emit('status_update', {
        'copying_active': copying_active,
        'accounts': db.get_all_accounts(),
        'active_trades': mt5_manager.get_all_active_trades() if copying_active else []
    })

# Background monitoring thread
def monitor_trades():
    """Monitor and copy trades in background"""
    global copying_active
    logger.info("Trade monitoring started")
    
    while copying_active:
        try:
            # Get provider accounts
            providers = db.get_provider_accounts()
            
            if providers:
                # Process each provider
                for provider in providers:
                    # Try to get positions (will fail if MT5 not connected)
                    try:
                        provider_trades = mt5_manager.get_positions(provider['id'])
                        
                        if provider_trades:
                            # Get receiver accounts
                            receivers = db.get_receiver_accounts()
                            
                            # Copy trades to receivers
                            for receiver in receivers:
                                if receiver['enabled']:
                                    trade_copier.copy_trades(
                                        provider['id'],
                                        receiver['id'],
                                        provider_trades
                                    )
                    except Exception as mt5_error:
                        logger.debug(f"Could not get positions for provider {provider['id']}: {mt5_error}")
                
                # Emit status update
                socketio.emit('trade_update', {
                    'timestamp': datetime.now().isoformat(),
                    'active_trades': []  # Will be populated when MT5 is connected
                })
            
            # Check interval (milliseconds to seconds)
            settings = db.get_settings()
            interval = settings.get('copy_interval', 500) / 1000.0
            time.sleep(interval)
            
        except Exception as e:
            logger.error(f"Error in monitoring thread: {e}")
            socketio.emit('error', {'message': str(e)})
            time.sleep(1)
    
    logger.info("Trade monitoring stopped")

# Initialize database on startup
def initialize():
    """Initialize application"""
    try:
        db.init_db()
        logger.info("Database initialized")
        
        # Load saved accounts (but don't fail if MT5 connection fails)
        accounts = db.get_all_accounts()
        for account in accounts:
            try:
                mt5_manager.connect_account(
                    account['id'],
                    account['login'],
                    account['password'],
                    account['server']
                )
                logger.info(f"Connected to account {account['login']}")
            except Exception as e:
                logger.warning(f"Could not connect account {account['login']}: {e}")
                # Continue without MT5 connection
        
        logger.info("MT5 Copy Trade Server initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize: {e}")
        # Continue anyway - allow web interface to work

if __name__ == '__main__':
    initialize()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)