import sys
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import resolve_advertised_udp_host  # noqa: E402


class FakeSocket:
    def __init__(self, local_addr):
        self.local_addr = local_addr

    def getsockname(self):
        return self.local_addr


def _ctx(server_ip, host="0.0.0.0", client_ip="100.91.235.8"):
    return SimpleNamespace(
        server=SimpleNamespace(
            cfg=SimpleNamespace(
                network=SimpleNamespace(
                    server_ip=server_ip,
                    host=host,
                )
            )
        ),
        session=SimpleNamespace(address=(client_ip, 65211)),
    )


class UdpAdvertiseTests(unittest.TestCase):
    def test_auto_uses_accepted_socket_local_address(self):
        advertised = resolve_advertised_udp_host(
            FakeSocket(("100.64.10.20", 2627)),
            _ctx("auto"),
        )

        self.assertEqual(advertised, "100.64.10.20")

    def test_explicit_host_wins(self):
        advertised = resolve_advertised_udp_host(
            FakeSocket(("100.64.10.20", 2627)),
            _ctx("203.0.113.55"),
        )

        self.assertEqual(advertised, "203.0.113.55")


if __name__ == "__main__":
    unittest.main()
