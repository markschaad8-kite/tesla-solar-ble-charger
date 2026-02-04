#!/bin/bash
#
# Setup script for Tesla BLE Relay on Pi Zero 2 W
#
# Run this after copying the folder to the Pi Zero:
#   cd ~/pi-zero-ble-relay
#   chmod +x setup.sh
#   ./setup.sh
#

set -e

echo "========================================"
echo "Tesla BLE Relay - Setup Script"
echo "========================================"
echo ""

# Check we're on a Pi
if [ ! -f /proc/device-tree/model ]; then
    echo "Warning: This doesn't appear to be a Raspberry Pi"
fi

# Update package list
echo "[1/6] Updating package list..."
sudo apt update

# Install system dependencies
echo "[2/6] Installing system dependencies..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    bluez \
    bluetooth \
    git \
    golang

# Install Python dependencies
echo "[3/6] Installing Python dependencies..."
pip3 install --user -r requirements.txt

# Check if tesla-control already exists
if command -v tesla-control &> /dev/null; then
    echo "[4/6] tesla-control already installed, skipping build..."
else
    echo "[4/6] Building tesla-control from source..."
    echo "      (This will take 10-15 minutes on Pi Zero 2)"

    cd ~

    if [ ! -d "vehicle-command" ]; then
        git clone https://github.com/teslamotors/vehicle-command.git
    fi

    cd vehicle-command

    # Build tesla-control
    echo "      Building... please wait..."
    go build -o tesla-control ./cmd/tesla-control

    # Install to /usr/local/bin
    sudo mv tesla-control /usr/local/bin/
    sudo chmod +x /usr/local/bin/tesla-control

    cd ~/pi-zero-ble-relay

    echo "      tesla-control installed successfully!"
fi

# Verify tesla-control works
echo "[5/6] Verifying tesla-control installation..."
if tesla-control --help > /dev/null 2>&1; then
    echo "      tesla-control OK"
else
    echo "      ERROR: tesla-control not working!"
    exit 1
fi

# Setup systemd service
echo "[6/6] Setting up systemd service..."

# Copy service file
sudo cp ble-relay.service /etc/systemd/system/

# Add pi user to bluetooth group
sudo usermod -a -G bluetooth pi

# Allow pi user to run hciconfig without password (for service startup)
echo "pi ALL=(ALL) NOPASSWD: /usr/bin/hciconfig" | sudo tee /etc/sudoers.d/ble-relay > /dev/null

# Reload systemd
sudo systemctl daemon-reload

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Copy your private.pem from Pi 5:"
echo "   scp pi5:/path/to/private.pem ~/pi-zero-ble-relay/"
echo ""
echo "2. Edit config if needed:"
echo "   nano ~/pi-zero-ble-relay/config.env"
echo ""
echo "3. Start the service:"
echo "   sudo systemctl enable ble-relay"
echo "   sudo systemctl start ble-relay"
echo ""
echo "4. Check status:"
echo "   sudo systemctl status ble-relay"
echo "   journalctl -u ble-relay -f"
echo ""
echo "5. Test from Pi 5:"
echo "   curl http://$(hostname -I | awk '{print $1}'):5003/health"
echo ""
