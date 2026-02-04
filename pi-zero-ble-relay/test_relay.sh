#!/bin/bash
#
# Test script to verify the BLE relay is working
# Run this from the Pi 5 after setting up the Pi Zero
#
# Usage: ./test_relay.sh [hostname]
#

RELAY_HOST=${1:-tesla-ble-relay.local}
RELAY_PORT=5003
RELAY_URL="http://${RELAY_HOST}:${RELAY_PORT}"

echo "========================================"
echo "Tesla BLE Relay - Test Script"
echo "========================================"
echo "Relay: ${RELAY_URL}"
echo ""

# Test 1: Health check
echo "[Test 1] Health check..."
HEALTH=$(curl -s "${RELAY_URL}/health" 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "  FAILED: Could not connect to relay"
    echo "  Check if Pi Zero is online and service is running"
    exit 1
fi

echo "  Response: ${HEALTH}"

BLUETOOTH=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('bluetooth', False))" 2>/dev/null)
TESLA_CTL=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tesla_control', False))" 2>/dev/null)

if [ "$BLUETOOTH" != "True" ]; then
    echo "  WARNING: Bluetooth not available on relay"
fi

if [ "$TESLA_CTL" != "True" ]; then
    echo "  ERROR: tesla-control not found on relay"
    exit 1
fi

echo "  OK"
echo ""

# Test 2: Status
echo "[Test 2] Status check..."
STATUS=$(curl -s "${RELAY_URL}/status" 2>/dev/null)
echo "  Response: ${STATUS}"
echo "  OK"
echo ""

# Test 3: BLE command (optional - requires car in range)
echo "[Test 3] BLE command test (optional)..."
echo "  This will attempt to send a BLE command to the car."
echo "  The car should be in BLE range of the Pi Zero."
echo ""
read -p "  Run BLE test? [y/N] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "  Sending charging-set-amps 16..."
    RESULT=$(curl -s -X POST "${RELAY_URL}/ble/command" \
        -H "Content-Type: application/json" \
        -d '{"command": "charging-set-amps", "args": ["16"]}' 2>/dev/null)

    echo "  Response: ${RESULT}"

    SUCCESS=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success', False))" 2>/dev/null)
    DURATION=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('duration', 0))" 2>/dev/null)

    if [ "$SUCCESS" == "True" ]; then
        echo "  SUCCESS! Command completed in ${DURATION}s"
    else
        ERROR=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error', 'unknown'))" 2>/dev/null)
        echo "  FAILED: ${ERROR}"
        echo ""
        echo "  If this is a range issue, try moving Pi Zero closer to car."
    fi
else
    echo "  Skipped"
fi

echo ""
echo "========================================"
echo "Tests complete!"
echo "========================================"
