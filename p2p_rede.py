"""Descoberta P2P via multicast UDP (LAN)."""
from __future__ import annotations

import socket
import threading
import time
from typing import Callable, Optional


MULTICAST_GROUP = "239.255.66.66"
MULTICAST_PORT = 50077
PING_PREFIX = "BRN_NODE_PING:"
PONG_PREFIX = "BRN_NODE_PONG:"
SOCKET_TIMEOUT = 1.0
PEER_TTL = 15.0
MAX_PEERS = 256
BROADCAST_INTERVAL = 5.0


class AutoNodeDiscovery:
    def __init__(self,
                 p2p_port: int = 7777,
                 gui_callback: Optional[Callable[[str], None]] = None,
                 on_peer: Optional[Callable[[str, int], None]] = None,
                 on_message: Optional[Callable[[str, str], None]] = None):
        self.p2p_port = int(p2p_port)
        self.gui_callback = gui_callback
        self.on_peer = on_peer
        self.on_message = on_message

        self.discovered_peers: dict[str, float] = {}
        self._peers_lock = threading.Lock()
        self.running = False

        self._server_socket: Optional[socket.socket] = None
        self._broadcast_socket: Optional[socket.socket] = None
        self._server_thread: Optional[threading.Thread] = None
        self._broadcast_thread: Optional[threading.Thread] = None

        self.local_ip = self._get_local_ip()

    def _log(self, msg: str) -> None:
        if self.gui_callback:
            try:
                self.gui_callback(msg)
            except Exception:
                pass

    def _get_local_ip(self) -> str:
        try:
            for info in socket.getaddrinfo(
                socket.gethostname(), None, socket.AF_INET
            ):
                ip = info[4][0]
                if (ip.startswith(("10.", "172.", "192.168.",
                                   "169.254.", "127."))
                        and ip != "127.0.0.1"):
                    return ip
        except Exception:
            pass
        return "127.0.0.1"

    def _is_self(self, ip: str, port: int) -> bool:
        if ip == self.local_ip and port == self.p2p_port:
            return True
        if ip in ("127.0.0.1", "localhost") and port == self.p2p_port:
            return True
        return False

    def _prune(self) -> None:
        cutoff = time.monotonic() - PEER_TTL
        expired = [a for a, t in self.discovered_peers.items() if t < cutoff]
        for a in expired:
            self.discovered_peers.pop(a, None)

    def _add_peer(self, ip: str, port: int) -> bool:
        if not ip or self._is_self(ip, port):
            return False
        addr = f"{ip}:{port}"
        now = time.monotonic()
        with self._peers_lock:
            self._prune()
            if addr in self.discovered_peers:
                self.discovered_peers[addr] = now
                return False
            if len(self.discovered_peers) >= MAX_PEERS:
                return False
            self.discovered_peers[addr] = now
        self._log(f"peer descoberto: {addr}")
        if self.on_peer:
            try:
                self.on_peer(ip, int(port))
            except Exception as e:
                self._log(f"on_peer falhou: {e}")
        return True

    def get_peers(self) -> list[str]:
        with self._peers_lock:
            self._prune()
            return sorted(self.discovered_peers)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._server_thread = threading.Thread(
            target=self._run_server, name="brn-discovery-srv", daemon=True
        )
        self._broadcast_thread = threading.Thread(
            target=self._run_broadcast, name="brn-discovery-bcast",
            daemon=True
        )
        self._server_thread.start()
        self._broadcast_thread.start()
        self._log(f"descoberta ativa em {self.local_ip}:{MULTICAST_PORT}")

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        for s in (self._server_socket, self._broadcast_socket):
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
        for t in (self._server_thread, self._broadcast_thread):
            if (t is not None and t.is_alive()
                    and t is not threading.current_thread()):
                t.join(timeout=2.0)
        self._log("descoberta encerrada")

    def _run_server(self) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                              socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            s.bind(("", MULTICAST_PORT))
            mreq = (socket.inet_aton(MULTICAST_GROUP)
                    + socket.inet_aton("0.0.0.0"))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            s.settimeout(SOCKET_TIMEOUT)
            self._server_socket = s
        except Exception as e:
            self._log(f"erro ao abrir servidor multicast: {e}")
            self.running = False
            return

        while self.running:
            try:
                data, addr = s.recvfrom(64 * 1024)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                self._log(f"erro no recvfrom: {e}")
                continue

            remote_ip = addr[0]
            try:
                msg = data.decode("utf-8", errors="strict").strip()
            except UnicodeDecodeError:
                continue
            if not msg:
                continue

            if msg.startswith(PING_PREFIX):
                port_text = msg[len(PING_PREFIX):].strip()
                try:
                    remote_port = int(port_text)
                except ValueError:
                    continue
                if self._add_peer(remote_ip, remote_port):
                    try:
                        s.sendto(
                            f"{PONG_PREFIX}{self.p2p_port}".encode(),
                            addr,
                        )
                    except OSError:
                        pass
            elif msg.startswith(PONG_PREFIX):
                port_text = msg[len(PONG_PREFIX):].strip()
                try:
                    remote_port = int(port_text)
                except ValueError:
                    continue
                self._add_peer(remote_ip, remote_port)
            elif self.on_message is not None:
                try:
                    self.on_message(msg, remote_ip)
                except Exception as e:
                    self._log(f"on_message falhou: {e}")

        try:
            mreq = (socket.inet_aton(MULTICAST_GROUP)
                    + socket.inet_aton("0.0.0.0"))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass
        self._server_socket = None

    def _run_broadcast(self) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                              socket.IPPROTO_UDP)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            self._broadcast_socket = s
        except Exception as e:
            self._log(f"erro ao abrir socket de broadcast: {e}")
            return

        while self.running:
            try:
                s.sendto(
                    f"{PING_PREFIX}{self.p2p_port}".encode(),
                    (MULTICAST_GROUP, MULTICAST_PORT),
                )
            except OSError:
                if not self.running:
                    break
            except Exception as e:
                self._log(f"erro no broadcast: {e}")

            deadline = time.monotonic() + BROADCAST_INTERVAL
            while self.running and time.monotonic() < deadline:
                time.sleep(0.25)

        try:
            s.close()
        except Exception:
            pass
        self._broadcast_socket = None

    def send_multicast(self, payload: str) -> None:
        s = self._broadcast_socket
        if s is None:
            return
        try:
            s.sendto(payload.encode(),
                     (MULTICAST_GROUP, MULTICAST_PORT))
        except Exception as e:
            self._log(f"erro ao enviar multicast: {e}")


if __name__ == "__main__":
    print("Testando descoberta por 8 segundos...")
    d = AutoNodeDiscovery(p2p_port=7777,
                          gui_callback=lambda m: print("  ", m))
    d.start()
    time.sleep(8)
    print("Peers:", d.get_peers())
    d.stop()
    print("OK — p2p_rede.py funciona.")