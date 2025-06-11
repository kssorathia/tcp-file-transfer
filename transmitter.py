#!/usr/bin/env python3

"""
TCP File Transmitter

This script allows sending and receiving files over TCP with support for:
- Chunked transfers
- Multithreaded receiving (1 thread per connection)
- File integrity validation via SHA256
- ACK/NACK-based error feedback and retry logic
- Enhancements -TBD: 
    Logging - DEBUG/INFO/WARN/ERROR  - JSON format, output to file or DB
    --resume option to resume partial tansfers

Usage:

Start receiver:
    python3 transmitter.py recv <bind_ip> <port>
Example:
    python3 transmitter.py recv 0.0.0.0 9000

Send a file:
    python3 transmitter.py send <filename> <receiver_ip> <port>
Example:
    python3 transmitter.py send bigfile.zip 192.168.1.10 9000

Parallel file transfers:
- You can launch multiple sender instances in parallel:
    python3 transmitter.py send file1 192.168.1.10 9000 &
    python3 transmitter.py send file2 192.168.1.10 9000 &
- The receiver handles each in its own thread.

Notes:
- Each sender runs in a separate process/thread and transfers a single file.
- Receiver can accept multiple connections in parallel.
- If the receiver crashes, the `.part` file is preserved.
- Resume logic is in place on receiver, but sender does not yet support offset negotiation.
"""

import argparse
import os
import socket
import struct
import threading
import hashlib
import time

# Constants
CHUNK_SIZE = 4096  # Chunk size for file transfer
HEADER_FORMAT = '!I256sQ32s'  # Network byte order: uint32, 256-byte string, uint64, 32-byte hash
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
ACK = b'\x06'  # Acknowledgment byte
NACK = b'\x15'  # Negative acknowledgment byte
MAX_RETRIES = 3  # Max retries on sender
RETRY_DELAY = 2  # Delay between retries in seconds

# Reason codes for NACK responses
REASON_CODES = {
    b'CHK': 'Checksum mismatch',
    b'DSK': 'Disk write failure',
    b'HDR': 'Header malformed or invalid',
    b'UNK': 'Unknown receiver error',
}

def sanitize_filename(filename):
    """Ensure only the base filename is used to prevent path traversal."""
    return os.path.basename(filename)

def calculate_sha256(filepath):
    """Compute the SHA256 checksum of a file in chunks."""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(CHUNK_SIZE):
            sha256.update(chunk)
    return sha256.digest()

def send_file(filename, ip, port):
    """Send a file to the specified IP and port, with retries and ACK/NACK verification."""
    if not os.path.exists(filename):
        print(f"[ERROR] File not found: {filename}")
        return

    basename = sanitize_filename(filename)
    filesize = os.path.getsize(filename)
    sha256 = calculate_sha256(filename)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with socket.create_connection((ip, port)) as sock:
                print(f"[INFO] Connected to receiver {ip}:{port} (Attempt {attempt})")

                # Prepare and send metadata header
                header = struct.pack(
                    HEADER_FORMAT,
                    len(basename.encode()),
                    basename.encode().ljust(256, b'\x00'),
                    filesize,
                    sha256
                )
                sock.sendall(header)

                # Send file in chunks
                with open(filename, 'rb') as f:
                    while chunk := f.read(CHUNK_SIZE):
                        sock.sendall(chunk)

                # Await receiver response
                response = sock.recv(4)
                if not response:
                    print(f"[ERROR] No response from receiver. Connection may have dropped.")
                elif response == ACK:
                    print(f"[INFO] File '{basename}' sent and acknowledged successfully.")
                    return
                elif response.startswith(NACK):
                    reason_code = response[1:4]
                    reason_msg = REASON_CODES.get(reason_code, 'Unspecified receiver error')
                    print(f"[WARN] Receiver rejected file '{basename}' ({reason_msg}) (Attempt {attempt})")
                else:
                    print(f"[ERROR] Unknown response from receiver: {response}")
        except Exception as e:
            print(f"[ERROR - Connection Failure] Attempt {attempt}: {type(e).__name__} - {e}")

        if attempt < MAX_RETRIES:
            print(f"[INFO] Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
        else:
            print(f"[ERROR] Failed to send file '{basename}' after {MAX_RETRIES} attempts.")

def handle_client(conn, addr):
    """Handle incoming connection and receive a file from the client."""
    try:
        print(f"[INFO] Connection from {addr}")
        header = conn.recv(HEADER_SIZE)
        if len(header) < HEADER_SIZE:
            conn.sendall(NACK + b'HDR')
            raise ValueError("Incomplete or malformed header received")

        filename_len, raw_filename, filesize, expected_sha256 = struct.unpack(HEADER_FORMAT, header)
        filename = raw_filename[:filename_len].decode().strip('\x00')
        filename = sanitize_filename(filename)

        partial_file = filename + ".part"
        offset = 0
        if os.path.exists(partial_file):
            offset = os.path.getsize(partial_file)

        mode = 'ab' if offset else 'wb'
        try:
            with open(partial_file, mode) as f:
                remaining = filesize - offset
                while remaining > 0:
                    chunk = conn.recv(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        conn.sendall(NACK + b'UNK')
                        raise IOError("Connection lost during file transfer")
                    f.write(chunk)
                    remaining -= len(chunk)
        except OSError:
            conn.sendall(NACK + b'DSK')
            raise

        # Validate file integrity
        actual_sha256 = calculate_sha256(partial_file)
        if actual_sha256 == expected_sha256:
            os.rename(partial_file, filename)
            print(f"[INFO] File '{filename}' received and verified successfully ({filesize} bytes) from {addr}")
            conn.sendall(ACK)
        else:
            print(f"[ERROR] Checksum mismatch for file '{filename}'")
            conn.sendall(NACK + b'CHK')
    except Exception as e:
        print(f"[ERROR] Error handling client {addr}: {e}")
        try:
            conn.sendall(NACK + b'UNK')
        except:
            pass
    finally:
        conn.close()

# Receiver concurrency control
MAX_CONCURRENT_THREADS = 10  # Limit concurrent client handlers
thread_limiter = threading.Semaphore(MAX_CONCURRENT_THREADS)


def handle_client_limited(conn, addr):
    with thread_limiter:
        handle_client(conn, addr)


def start_receiver(ip, port):
    """Start a receiver socket and listen for incoming file transfers."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((ip, port))
            s.listen()
            print(f"[INFO] Receiver listening on {ip}:{port}")

            while True:
                conn, addr = s.accept()
                threading.Thread(target=handle_client_limited, args=(conn, addr), daemon=True).start()
    except Exception as e:
        print(f"[ERROR] Receiver error: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="""\
TCP File Transmitter
Usage:
Start receiver:
  python3 transmitter.py recv 0.0.0.0 9000

Send a file:
  python3 transmitter.py send file.zip 192.168.1.10 9000

Multiple parallel sends:
  python3 transmitter.py send file1 192.168.1.10 9000 &
  python3 transmitter.py send file2 192.168.1.10 9000 &

Notes:
- Receiver handles each sender in a separate thread.
- SHA256-based integrity check is enforced.
- ACK/NACK responses allow retry on failure.
""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='mode', required=True)

    send_parser = subparsers.add_parser('send', help='Send file to receiver')
    send_parser.add_argument('filename', type=str, help='File to send')
    send_parser.add_argument('ip', type=str, help='Receiver IP address')
    send_parser.add_argument('port', type=int, help='Receiver port')

    recv_parser = subparsers.add_parser('recv', help='Receive files')
    recv_parser.add_argument('ip', type=str, help='Local bind IP')
    recv_parser.add_argument('port', type=int, help='Port to listen on')

    args = parser.parse_args()

    if args.mode == 'send':
        send_file(args.filename, args.ip, args.port)
    elif args.mode == 'recv':
        start_receiver(args.ip, args.port)


if __name__ == '__main__':
    main()
