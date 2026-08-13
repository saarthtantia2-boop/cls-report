"""
Auto Time Setter for Arduino Noise Detector
--------------------------------------------
Sends current PC time to Arduino over Serial as soon as it boots.
Requires: pip install pyserial

Usage:
  python auto_time.py          # auto-detect COM port
  python auto_time.py COM3     # specify port
"""

import sys
import time
from datetime import datetime
import serial
import serial.tools.list_ports

def find_arduino():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        if "Arduino" in (p.description or "") or "CH340" in (p.description or "") or "CH910" in (p.description or "") or "USB-SERIAL" in (p.description or "").upper():
            return p.device
    if ports:
        return ports[-1].device
    return None

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_arduino()
    if not port:
        print("No COM port found. Plug in Arduino and try again.")
        return

    print(f"Waiting for Arduino on {port}...")
    while True:
        try:
            ser = serial.Serial(port, 9600, timeout=0.1)
            time.sleep(0.5)
            now = datetime.now()
            time_str = now.strftime("%H:%M:%S")
            ser.write(f"{time_str}\n".encode())
            print(f"Sent time: {time_str}")
            time.sleep(1)
            response = ser.readline().decode(errors="ignore").strip()
            if response:
                print(f"Arduino: {response}")
            ser.close()
            return
        except serial.SerialException:
            time.sleep(0.5)

if __name__ == "__main__":
    main()
