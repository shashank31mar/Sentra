#!/usr/bin/env python3
"""
Test connectivity from dashboard to security-controller using Cloud Map service discovery.
"""
import requests
import socket
import os
import sys
from datetime import datetime


def test_dns_resolution():
    """Test if security-controller.sentra.internal resolves to an IP."""
    hostname = "security-controller.sentra.internal"
    print(f"\n=== Testing DNS Resolution ===")
    print(f"Hostname: {hostname}")

    try:
        ip = socket.gethostbyname(hostname)
        print(f"✅ DNS Resolution: SUCCESS")
        print(f"   Resolved to: {ip}")
        return True, ip
    except socket.gaierror as e:
        print(f"❌ DNS Resolution: FAILED")
        print(f"   Error: {e}")
        return False, None


def test_tcp_connectivity(ip, port=8080):
    """Test if we can establish a TCP connection to the IP and port."""
    print(f"\n=== Testing TCP Connectivity ===")
    print(f"Target: {ip}:{port}")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((ip, port))
        sock.close()

        if result == 0:
            print(f"✅ TCP Connection: SUCCESS")
            print(f"   Port {port} is open")
            return True
        else:
            print(f"❌ TCP Connection: FAILED")
            print(f"   Port {port} is closed or unreachable")
            return False
    except Exception as e:
        print(f"❌ TCP Connection: ERROR")
        print(f"   Error: {e}")
        return False


def test_http_health_check(url="http://security-controller.sentra.internal:8080/v1/health"):
    """Test if we can make an HTTP request to the health endpoint."""
    print(f"\n=== Testing HTTP Health Check ===")
    print(f"URL: {url}")

    try:
        response = requests.get(url, timeout=5)
        print(f"✅ HTTP Request: SUCCESS")
        print(f"   Status Code: {response.status_code}")
        print(f"   Response: {response.text[:200]}")
        return True
    except requests.exceptions.Timeout:
        print(f"❌ HTTP Request: TIMEOUT")
        print(f"   Connection timed out after 5 seconds")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ HTTP Request: CONNECTION ERROR")
        print(f"   Error: {e}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ HTTP Request: ERROR")
        print(f"   Error: {e}")
        return False


def main():
    """Run all connectivity tests."""
    print("=" * 60)
    print("SENTRA DASHBOARD - CONNECTIVITY TEST")
    print(f"Timestamp: {datetime.utcnow().isoformat()}")
    print("=" * 60)

    # Print environment info
    print(f"\n=== Environment Info ===")
    print(f"AWS_REGION: {os.getenv('AWS_REGION', 'NOT SET')}")
    print(f"SECURITY_CONTROLLER_URL: {os.getenv('SECURITY_CONTROLLER_URL', 'NOT SET')}")

    # Run tests
    tests_passed = 0
    tests_total = 3

    # Test 1: DNS Resolution
    dns_ok, ip = test_dns_resolution()
    if dns_ok:
        tests_passed += 1

    # Test 2: TCP Connectivity
    if dns_ok and ip:
        tcp_ok = test_tcp_connectivity(ip, 8080)
        if tcp_ok:
            tests_passed += 1
    else:
        print(f"\n=== Skipping TCP test (DNS failed) ===")

    # Test 3: HTTP Health Check
    http_ok = test_http_health_check()
    if http_ok:
        tests_passed += 1

    # Summary
    print(f"\n{'=' * 60}")
    print(f"TEST SUMMARY: {tests_passed}/{tests_total} tests passed")
    print(f"{'=' * 60}")

    if tests_passed == tests_total:
        print("✅ All connectivity tests passed!")
        print("   Dashboard can successfully reach security-controller")
        sys.exit(0)
    else:
        print(f"❌ {tests_total - tests_passed} test(s) failed")
        print("   Dashboard cannot reach security-controller")
        sys.exit(1)


if __name__ == "__main__":
    main()
