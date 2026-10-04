"""Is the ~2 s per-call overhead the Windows localhost -> ::1 fallback? Time a trivial GET both ways."""
import socket
import time
import urllib.request

print("localhost resolves to:", [a[4][0] for a in socket.getaddrinfo("localhost", 11434, proto=socket.IPPROTO_TCP)])
for host in ["localhost", "127.0.0.1", "localhost", "127.0.0.1"]:
    t0 = time.perf_counter()
    urllib.request.urlopen(f"http://{host}:11434/api/version", timeout=10).read()
    print(f"{host:>10}: {time.perf_counter() - t0:.3f}s")

try:
    import httpx  # noqa: F401
    have_httpx = True
except ImportError:
    have_httpx = False
print("httpx available in this interpreter:", have_httpx)
