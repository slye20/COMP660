"""One request per call, no application retries or unreported fallbacks.

Network time excludes query construction, client construction, and DNS parsing.
DoH setup uses pinned httpcore trace events; TCP and TLS include client overhead.
"""

from dataclasses import asdict, dataclass
import socket
import ssl
import time
import uuid

import certifi
import dns.exception
import dns.flags
import dns.message
import dns.query
import dns.rcode
import httpx


def now():
    return time.perf_counter_ns() / 1e6


@dataclass
class Result:
    status: str = "error"
    error: str = ""
    elapsed_ms: float = 0.0
    total_ms: float | None = None
    setup_ms: float | None = None
    tcp_ms: float | None = None
    tls_ms: float | None = None
    query_ms: float | None = None
    new_connection: bool = False
    reused: bool = False
    connection_id: str = ""
    tls_version: str = ""
    tls_resumed: bool | None = None
    http_version: str = ""
    rcode: str = ""
    answer_count: int = 0
    response_bytes: int = 0
    min_ttl: int | None = None

    def dict(self):
        return asdict(self)


def context(cafile=None):
    # Same trust store for DoT and DoH. Fresh context per session prevents sharing
    # TLS sessions between cold trials. Certificate and hostname checks stay on.
    return ssl.create_default_context(cafile=cafile or certifi.where())


def validate(query, response, result):
    result.response_bytes = len(response.to_wire())
    result.rcode = dns.rcode.to_text(response.rcode())
    result.answer_count = sum(len(rr) for rr in response.answer)
    result.min_ttl = min((rr.ttl for rr in response.answer), default=None)
    if not query.is_response(response):
        raise ValueError("DNS response ID/question does not match request")
    if response.flags & dns.flags.TC:
        raise ValueError("Truncated UDP response; TCP fallback deliberately disabled")
    if response.rcode() != dns.rcode.NOERROR:
        result.status = "dns_error"
        result.error = result.rcode
    elif not result.answer_count:
        result.status = "dns_error"
        result.error = "NOERROR with no answers"
    else:
        result.status = "ok"


class Session:
    def __init__(self, resolver, protocol, timeout=3.0, cafile=None):
        self.resolver = resolver
        self.protocol = protocol
        self.timeout = timeout
        self.sock = None
        self.client = None
        self.connection_id = ""
        self.ctx = context(cafile) if protocol != "do53" else None
        if protocol == "doh":
            self.client = httpx.Client(
                http2=True, verify=self.ctx, trust_env=False, timeout=timeout,
                follow_redirects=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=1,
                                   keepalive_expiry=None),
            )

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        if self.client is not None:
            self.client.close()

    def query(self, domain, qtype="A"):
        query = dns.message.make_query(domain, qtype, use_edns=0, payload=1232)
        if self.protocol == "doh":
            query.id = 0  # RFC 8484 recommends zero for HTTPS messages.
        wire = query.to_wire()
        result = Result()
        start = now()
        try:
            if self.protocol == "do53":
                result.setup_ms = result.tcp_ms = result.tls_ms = 0.0
                response = dns.query.udp(query, self.resolver["ip"],
                                         port=self.resolver.get("udp_port", 53),
                                         timeout=self.timeout, raise_on_truncation=True)
                result.total_ms = result.query_ms = now() - start
            elif self.protocol == "dot":
                if self.sock is None:
                    result.new_connection = True
                    self.connection_id = uuid.uuid4().hex
                    raw = socket.create_connection(
                        (self.resolver["ip"], self.resolver.get("dot_port", 853)), self.timeout)
                    tcp_end = now()
                    raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    try:
                        self.sock = self.ctx.wrap_socket(raw, server_hostname=self.resolver["dot_host"])
                    except BaseException:
                        raw.close()
                        raise
                    tls_end = now()
                    result.tcp_ms = tcp_end - start
                    result.tls_ms = tls_end - tcp_end
                    result.setup_ms = tls_end - start
                else:
                    result.reused = True
                    result.setup_ms = result.tcp_ms = result.tls_ms = 0.0
                result.connection_id = self.connection_id
                result.tls_version = self.sock.version()
                result.tls_resumed = self.sock.session_reused
                response = dns.query.tls(query, self.resolver["ip"], sock=self.sock,
                                         timeout=self.timeout)
                result.total_ms = now() - start
                result.query_ms = result.total_ms - result.setup_ms
            elif self.protocol == "doh":
                response = self._doh(query, wire, result, start)
            else:
                raise ValueError(f"Unknown protocol: {self.protocol}")
            validate(query, response, result)
        except (dns.exception.Timeout, httpx.TimeoutException, TimeoutError) as exc:
            result.status = "timeout"
            result.error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            result.status = "error"
            result.error = f"{type(exc).__name__}: {exc}"
        result.elapsed_ms = now() - start
        if result.status != "ok":
            # Failure duration is not a successful resolution latency. In
            # particular, don't silently include a timeout cutoff in quantiles.
            result.total_ms = result.query_ms = None
            if self.sock is not None:
                self.sock.close()
                self.sock = None
        return result

    def _doh(self, query, wire, result, start):
        timestamps = {}

        def trace(event, info):
            timestamps[event] = now()
            if event == "connection.connect_tcp.started":
                result.new_connection = True
                self.connection_id = uuid.uuid4().hex

        port = self.resolver.get("doh_port", 443)
        ip = self.resolver["ip"]
        ip = f"[{ip}]" if ":" in ip else ip
        url = f"https://{ip}:{port}{self.resolver['doh_path']}"
        host = self.resolver["doh_host"]
        with self.client.stream(
            "POST", url, content=wire,
            headers={"Host": host, "Accept": "application/dns-message",
                     "Content-Type": "application/dns-message", "Cache-Control": "no-cache"},
            extensions={"sni_hostname": host, "trace": trace},
        ) as response:
            body = response.read()
            result.total_ms = now() - start
            result.http_version = response.http_version
            stream = response.extensions.get("network_stream")
            tls = stream.get_extra_info("ssl_object") if stream else None
            if tls:
                result.tls_version = tls.version()
                result.tls_resumed = tls.session_reused
            if result.new_connection:
                # A successful new connection MUST produce all four events.
                # Fail visibly if a dependency change breaks instrumentation.
                tcp_start = timestamps["connection.connect_tcp.started"]
                tcp_end = timestamps["connection.connect_tcp.complete"]
                tls_start = timestamps["connection.start_tls.started"]
                tls_end = timestamps["connection.start_tls.complete"]
                result.tcp_ms = tcp_end - tcp_start
                result.tls_ms = tls_end - tls_start
                result.setup_ms = result.tcp_ms + result.tls_ms
            else:
                if not self.connection_id:
                    raise ValueError("Missing connection trace on first request")
                result.reused = True
                result.setup_ms = result.tcp_ms = result.tls_ms = 0.0
            result.connection_id = self.connection_id
            result.query_ms = result.total_ms - result.setup_ms
            response.raise_for_status()
            if response.headers.get("content-type", "").split(";")[0].strip() != "application/dns-message":
                raise ValueError("Unexpected DoH content type")
        return dns.message.from_wire(body)
