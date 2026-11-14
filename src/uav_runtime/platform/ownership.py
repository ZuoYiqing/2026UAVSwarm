"""Kernel-wide ownership lease, distinct from the MAVLink UDP receiver.

Reserving (not listening on) the same numeric TCP port provides a cross-store,
cross-process lock for cooperating Runtime deployments in one network namespace.
No additional MAVLink receiver is created. Unmanaged external receivers still
require Simulation's preflight/process ownership checks.
"""
import socket

from .contract import PlatformError


class TransportLease:
    def __init__(self, endpoint: str):
        self.socket = None
        if not endpoint.startswith("udpin:127.0.0.1:"):
            raise PlatformError("explicit_loopback_mavlink_required")
        port = int(endpoint.rsplit(":", 1)[1])
        lease = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            lease.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            lease.bind(("127.0.0.1", port))
        except OSError:
            lease.close()
            raise PlatformError("mavlink_transport_already_owned", 409) from None
        self.socket = lease

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
