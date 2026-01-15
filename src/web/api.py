"""
Flask web API for controlling the emulator.

Provides REST endpoints and WebSocket interface.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..emulator.evse import EVSEStateMachine, ErrorFlags
    from ..emulator.ev import EVSimulator


class WebAPI:
    """Flask web API for the emulator."""
    
    def __init__(self, evse: 'EVSEStateMachine', ev: 'EVSimulator', host: str = "0.0.0.0", port: int = 8080):
        """
        Initialize the web API.
        
        Args:
            evse: EVSE state machine instance
            ev: EV simulator instance
            host: Host to bind to
            port: Port to bind to
        """
        self.evse = evse
        self.ev = ev
        self.host = host
        self.port = port
        
        # Create Flask app
        self.app = Flask(__name__, 
                         static_folder=os.path.join(os.path.dirname(__file__), 'static'),
                         static_url_path='')
        CORS(self.app)
        
        # Create SocketIO instance
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode='eventlet')
        
        # Register routes
        self._register_routes()
        
        # Set up state change callback
        self.evse.set_state_change_callback(self._on_state_change)
    
    def _register_routes(self):
        """Register all API routes."""
        
        # Serve index.html
        @self.app.route('/')
        def index():
            return send_from_directory(self.app.static_folder, 'index.html')
        
        # EVSE endpoints
        @self.app.route('/api/evse/status', methods=['GET'])
        def get_evse_status():
            return jsonify(self.evse.get_status())
        
        @self.app.route('/api/evse/version', methods=['GET'])
        def get_version():
            return jsonify({
                'firmware': self.evse.firmware_version,
                'protocol': self.evse.protocol_version
            })
        
        @self.app.route('/api/evse/enable', methods=['POST'])
        def enable_evse():
            if self.evse.enable():
                self._broadcast_status()
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': 'Cannot enable (errors present)'}), 400
        
        @self.app.route('/api/evse/disable', methods=['POST'])
        def disable_evse():
            self.evse.disable()
            self._broadcast_status()
            return jsonify({'success': True})
        
        @self.app.route('/api/evse/reset', methods=['POST'])
        def reset_evse():
            self.evse.reset()
            self._broadcast_status()
            return jsonify({'success': True})
        
        @self.app.route('/api/evse/current', methods=['POST'])
        def set_current():
            data = request.get_json()
            if not data or 'amps' not in data:
                return jsonify({'error': 'Missing amps parameter'}), 400
            
            try:
                amps = int(data['amps'])
                if amps < 6 or amps > 80:
                    return jsonify({'error': 'Current must be between 6 and 80 amps'}), 400
                
                self.evse.current_capacity_amps = amps
                self._broadcast_status()
                return jsonify({'success': True})
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid amps value'}), 400
        
        @self.app.route('/api/evse/service_level', methods=['POST'])
        def set_service_level():
            data = request.get_json()
            if not data or 'level' not in data:
                return jsonify({'error': 'Missing level parameter'}), 400
            
            level = data['level']
            if level not in ['L1', 'L2', 'Auto']:
                return jsonify({'error': 'Level must be L1, L2, or Auto'}), 400
            
            self.evse.service_level = level
            self._broadcast_status()
            return jsonify({'success': True})
        
        # EV endpoints
        @self.app.route('/api/ev/status', methods=['GET'])
        def get_ev_status():
            return jsonify(self.ev.get_status())
        
        @self.app.route('/api/ev/connect', methods=['POST'])
        def connect_ev():
            self.ev.connected = True
            self._broadcast_status()
            return jsonify({'success': True})
        
        @self.app.route('/api/ev/disconnect', methods=['POST'])
        def disconnect_ev():
            self.ev.connected = False
            self._broadcast_status()
            return jsonify({'success': True})
        
        @self.app.route('/api/ev/request_charge', methods=['POST'])
        def request_charge():
            self.ev.requesting_charge = True
            self._broadcast_status()
            return jsonify({'success': True})
        
        @self.app.route('/api/ev/stop_charge', methods=['POST'])
        def stop_charge():
            self.ev.requesting_charge = False
            self._broadcast_status()
            return jsonify({'success': True})
        
        @self.app.route('/api/ev/soc', methods=['POST'])
        def set_soc():
            data = request.get_json()
            if not data or 'soc' not in data:
                return jsonify({'error': 'Missing soc parameter'}), 400
            
            try:
                soc = float(data['soc'])
                if soc < 0 or soc > 100:
                    return jsonify({'error': 'SoC must be between 0 and 100'}), 400
                
                self.ev.soc = soc
                self._broadcast_status()
                return jsonify({'success': True})
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid soc value'}), 400
        
        @self.app.route('/api/ev/max_rate', methods=['POST'])
        def set_max_rate():
            data = request.get_json()
            if not data or 'amps' not in data:
                return jsonify({'error': 'Missing amps parameter'}), 400
            
            try:
                amps = float(data['amps'])
                if amps < 0:
                    return jsonify({'error': 'Max rate must be positive'}), 400
                
                # Convert amps to kW (assuming voltage from EVSE)
                voltage = self.evse.get_status()['voltage'] / 1000.0
                kw = (amps * voltage) / 1000.0
                self.ev.max_charge_rate_kw = kw
                self._broadcast_status()
                return jsonify({'success': True})
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid amps value'}), 400
        
        # Error simulation endpoints
        @self.app.route('/api/errors/trigger', methods=['POST'])
        def trigger_error():
            data = request.get_json()
            if not data or 'error' not in data:
                return jsonify({'error': 'Missing error parameter'}), 400
            
            from ..emulator.evse import ErrorFlags
            
            error_map = {
                'gfci': ErrorFlags.GFCI_TRIP,
                'stuck_relay': ErrorFlags.STUCK_RELAY,
                'no_ground': ErrorFlags.NO_GROUND,
                'diode_check': ErrorFlags.DIODE_CHECK_FAILED,
                'over_temp': ErrorFlags.OVER_TEMPERATURE,
                'gfi_self_test': ErrorFlags.GFI_SELF_TEST_FAILED
            }
            
            error_flag = error_map.get(data['error'])
            if error_flag is None:
                return jsonify({'error': 'Unknown error type'}), 400
            
            self.evse.trigger_error(error_flag)
            self._broadcast_error(data['error'])
            self._broadcast_status()
            return jsonify({'success': True})
        
        @self.app.route('/api/errors/clear', methods=['POST'])
        def clear_errors():
            self.evse.clear_errors()
            self._broadcast_status()
            return jsonify({'success': True})
        
        @self.app.route('/api/errors/status', methods=['GET'])
        def get_error_status():
            status = self.evse.get_status()
            return jsonify({
                'error_flags': status['error_flags'],
                'error_counts': {
                    'gfci': status['gfci_count'],
                    'no_ground': status['no_ground_count'],
                    'stuck_relay': status['stuck_relay_count']
                }
            })
        
        # Combined status endpoint
        @self.app.route('/api/status', methods=['GET'])
        def get_combined_status():
            return jsonify({
                'evse': self.evse.get_status(),
                'ev': self.ev.get_status()
            })
    
    def _on_state_change(self, new_state):
        """Called when EVSE state changes."""
        self.socketio.emit('state_change', {
            'state': int(new_state),
            'state_name': new_state.name
        })
    
    def _broadcast_status(self):
        """Broadcast status update via WebSocket."""
        evse_status = self.evse.get_status()
        ev_status = self.ev.get_status()
        
        self.socketio.emit('status_update', {
            'evse': evse_status,
            'ev': ev_status
        })
    
    def _broadcast_error(self, error_type: str):
        """Broadcast error event via WebSocket."""
        self.socketio.emit('error', {
            'error': error_type,
            'message': f'{error_type} error triggered'
        })
    
    def run(self):
        """Run the web server."""
        print(f"Starting web server on http://{self.host}:{self.port}")
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False)
