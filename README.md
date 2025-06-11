# TCP File Transmitter

A multithreaded TCP-based file transfer tool for sending large files over the network with:

* Chunked transfers for memory efficiency
* Multithreaded receiver (1 thread per client)
* SHA256-based integrity checking
* Retry with ACK/NACK logic
* Thread limiting to prevent resource exhaustion

---

## Features

* **Receiver** can handle multiple clients concurrently, each in a dedicated thread.
* **Sender** supports retries and waits for ACK/NACK before confirming success.
* **Checksum verification** ensures the file is received without corruption.
* **`.part` file resume support** allows recovery from mid-transfer crashes (on receiver side).
* **Thread limit control** via semaphore prevents too many open connections.

---

## Usage

### Start the Receiver

```bash
python3 transmitter.py recv 0.0.0.0 9000
```

* Listens on all interfaces (`0.0.0.0`) and port `9000`.
* Accepts multiple incoming file transfers in parallel.

---

### Send a File

```bash
python3 transmitter.py send file.zip 192.168.1.10 9000
```

* Sends `file.zip` to the receiver at `192.168.1.10` on port `9000`.

---

### Send Multiple Files in Parallel

From separate terminals or background jobs:

```bash
python3 transmitter.py send file1.bin 192.168.1.10 9000 &
python3 transmitter.py send file2.iso 192.168.1.10 9000 &
```

Or via a loop:

```bash
for file in *.bin; do
  python3 transmitter.py send "$file" 192.168.1.10 9000 &
done
wait
```

---

## Configurable Parameters

| Parameter                | Description                          | Default |
| ------------------------ | ------------------------------------ | ------- |
| `MAX_CONCURRENT_THREADS` | Max receiver threads allowed at once | `10`    |
| `CHUNK_SIZE`             | Size of each data chunk in bytes     | `4096`  |
| `MAX_RETRIES`            | Max sender retries on failure        | `3`     |
| `RETRY_DELAY`            | Delay between retries (seconds)      | `2`     |

---

## Future Enhancements

* `--resume` support on sender (offset-based resume)
* Compression or encryption options
* Logging to file or JSON
* Multi-file sending from one CLI command

---

## License

MIT License (you may use, modify, and distribute freely)

---

