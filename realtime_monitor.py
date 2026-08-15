"""
Real-time Classroom Noise Monitor
----------------------------------
Connects to Arduino via Serial, displays live noise bar graph.
Requires: pip install pyserial matplotlib

Usage:
  python realtime_monitor.py          # auto-detect COM port
  python realtime_monitor.py COM3     # specify port
"""

import sys
import time
from collections import deque
from datetime import datetime
import threading

import serial
import serial.tools.list_ports
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import FancyBboxPatch

# Config
MAX_POINTS = 120  # show last 2 minutes
NOISE_MAX = 15
REFRESH_MS = 500

# Color thresholds
COLORS = {
    'quiet': '#2ecc71',    # 0-3
    'moderate': '#f1c40f', # 4-7
    'loud': '#e67e22',     # 8-11
    'very_loud': '#e74c3c' # 12-15
}

def get_color(noise):
    if noise <= 3: return COLORS['quiet']
    if noise <= 7: return COLORS['moderate']
    if noise <= 11: return COLORS['loud']
    return COLORS['very_loud']

def find_arduino():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").upper()
        if any(k in desc for k in ["ARDUINO", "CH340", "CH910", "USB-SERIAL", "FTDI"]):
            return p.device
    if ports:
        return ports[-1].device
    return None

class NoiseData:
    def __init__(self):
        self.times = deque(maxlen=MAX_POINTS)
        self.values = deque(maxlen=MAX_POINTS)
        self.current = 0
        self.lock = threading.Lock()

    def add(self, value):
        now = datetime.now()
        with self.lock:
            self.times.append(now)
            self.values.append(value)
            self.current = value

    def get(self):
        with self.lock:
            return list(self.times), list(self.values), self.current

data = NoiseData()

def serial_reader(port):
    while True:
        try:
            ser = serial.Serial(port, 9600, timeout=1)
            time.sleep(0.5)
            print(f"Connected to {port}. Monitoring noise...")
            while True:
                line = ser.readline().decode(errors='ignore').strip()
                if line.startswith("N:"):
                    try:
                        val = int(line[2:])
                        data.add(val)
                    except ValueError:
                        pass
        except serial.SerialException:
            time.sleep(1)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)

def animate(frame):
    times, values, current = data.get()

    ax.clear()

    if not values:
        ax.text(0.5, 0.5, "Waiting for Arduino data...", 
                transform=ax.transAxes, ha='center', va='center',
                fontsize=16, color='#888888')
        ax.set_facecolor('#1a1a2e')
        return

    times_display = [(t - times[0]).total_seconds() for t in times]
    colors = [get_color(v) for v in values]

    bars = ax.bar(times_display, values, width=0.8, color=colors, edgecolor='none', alpha=0.9)

    ax.set_xlim(max(0, times_display[-1] - 60), max(60, times_display[-1]))
    ax.set_ylim(0, NOISE_MAX + 1)
    ax.set_xlabel("Seconds ago", color='#aaaaaa', fontsize=10)
    ax.set_ylabel("Noise Level", color='#aaaaaa', fontsize=10)
    ax.set_facecolor('#1a1a2e')

    ax.tick_params(colors='#666666')
    ax.spines['bottom'].set_color('#333333')
    ax.spines['left'].set_color('#333333')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    ax.set_yticks([0, 3, 7, 11, 15])
    ax.set_yticklabels(['0', '3', '7', '11', '15'], fontsize=9)

    # Legend
    for label, color, rng in [
        ("Quiet (0-3)", COLORS['quiet'], "0-3"),
        ("Moderate (4-7)", COLORS['moderate'], "4-7"),
        ("Loud (8-11)", COLORS['loud'], "8-11"),
        ("Very Loud (12-15)", COLORS['very_loud'], "12-15"),
    ]:
        ax.bar([], [], color=color, label=label)
    ax.legend(loc='upper left', fontsize=8, framealpha=0.3, facecolor='#1a1a2e', edgecolor='#333333')

    # Title with current value
    color = get_color(current)
    fig.suptitle(f"Classroom Noise Monitor", fontsize=18, color='white', fontweight='bold', y=0.98)
    ax.set_title(f"Current: {current}/15", fontsize=14, color=color, fontweight='bold', pad=10)

    fig.tight_layout(rect=[0, 0, 1, 0.95])

# Parse port
port = sys.argv[1] if len(sys.argv) > 1 else find_arduino()
if not port:
    print("No COM port found. Plug in Arduino and try again.")
    sys.exit(1)

print(f"Port: {port}")
print("Starting monitor... (close window to stop)")

# Start serial reader thread
reader = threading.Thread(target=serial_reader, args=(port,), daemon=True)
reader.start()

# Setup plot
fig, ax = plt.subplots(figsize=(14, 5))
fig.patch.set_facecolor('#0f0f1a')
ax.set_facecolor('#1a1a2e')
plt.subplots_adjust(left=0.06, right=0.98, top=0.9, bottom=0.15)

ani = animation.FuncAnimation(fig, animate, interval=REFRESH_MS, cache_frame_data=False)
plt.show()
