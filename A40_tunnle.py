#!/usr/bin/env python3
"""SSH tunnel to A40 inference servers — local port forwarding.

Forwards:
  localhost:5007 → A40:5007  (navigation model, /predict)
  localhost:5009 → A40:5009  (VLM scene description, vLLM /describe)

Usage:
  python3 A40_tunnle.py                  # both ports
  python3 A40_tunnle.py -p 5007          # nav model only
  python3 A40_tunnle.py -p 5007 -p 5009  # explicit
  Ctrl+C to stop.
"""
import os
import select
import signal
import socket
import sys
import threading

import paramiko

A40_HOST = '39.105.30.146'
A40_PORT = 7014
A40_USER = 'zhangenyan'
A40_PASS = os.environ.get('A40_PASSWORD', 'Zey666vln')
LOCAL_HOST = '127.0.0.1'
REMOTE_HOST = '127.0.0.1'

DEFAULT_PORTS = [5007, 5009]  # navigation model, VLM (vLLM)


def forward(local_conn, transport, remote_host, remote_port):
    """Bidirectional pipe between local socket and SSH direct-tcpip channel."""
    chan = None
    try:
        chan = transport.open_channel(
            'direct-tcpip', (remote_host, remote_port), local_conn.getpeername())
        if chan is None:
            return

        while True:
            r, w, x = select.select([local_conn, chan], [], [], 30)
            if not r:
                break
            if local_conn in r:
                data = local_conn.recv(65536)
                if len(data) == 0:
                    break
                chan.send(data)
            if chan in r:
                data = chan.recv(65536)
                if len(data) == 0:
                    break
                local_conn.send(data)
    except Exception:
        pass
    finally:
        try:
            local_conn.close()
        except Exception:
            pass
        if chan:
            try:
                chan.close()
            except Exception:
                pass


def listen_port(transport, local_port, remote_port, running_flag):
    """Create a TCP server on local_port forwarding to remote_port."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((LOCAL_HOST, local_port))
    except OSError as e:
        print(f"  Port {local_port} in use: {e}", file=sys.stderr)
        return None
    server.listen(5)
    server.settimeout(2.0)

    print(f"  {LOCAL_HOST}:{local_port} -> A40:{remote_port}")

    def _serve():
        while running_flag[0]:
            try:
                conn, addr = server.accept()
                t = threading.Thread(
                    target=forward,
                    args=(conn, transport, REMOTE_HOST, remote_port),
                    daemon=True,
                )
                t.start()
            except socket.timeout:
                continue
            except Exception:
                if running_flag[0]:
                    break
        try:
            server.close()
        except Exception:
            pass

    return _serve


def main():
    import argparse
    parser = argparse.ArgumentParser(description='A40 SSH Tunnel')
    parser.add_argument('-p', '--port', type=int, action='append',
                        help='Ports to forward (default: 5007 5009)')
    args = parser.parse_args()

    ports = args.port if args.port else DEFAULT_PORTS

    # Connect SSH
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    # 首次连接未知主机时自动接受 host key, 否则 load_system_host_keys() 找不到
    # 该主机就会抛 SSHException "Server not found in known_hosts" 直接退出。
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(A40_HOST, port=A40_PORT, username=A40_USER,
                    password=A40_PASS, timeout=10)
    except paramiko.AuthenticationException:
        print("SSH auth failed", file=sys.stderr)
        sys.exit(1)

    transport = ssh.get_transport()
    running = [True]

    # Start listeners
    print(f"SSH tunnel (PID {os.getpid()}):")
    threads = []
    for port in ports:
        t_fn = listen_port(transport, port, port, running)
        if t_fn:
            t = threading.Thread(target=t_fn, daemon=True)
            t.start()
            threads.append(t)

    if not threads:
        print("No ports forwarded. Exiting.")
        ssh.close()
        sys.exit(1)

    print("Ready. Ctrl+C to stop.")
    sys.stdout.flush()

    def stop(sig, frame):
        running[0] = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    # Wait for signal
    while running[0]:
        signal.pause()

    print("\nTunnel closed.")
    ssh.close()


if __name__ == '__main__':
    main()