import dns.exception
import dns.flags
import dns.message
import dns.rcode
import dns.rrset
import pytest

from dnsbench.transports import Result, Session, validate

RESOLVER = {"name": "test", "ip": "127.0.0.1", "dot_host": "localhost", "doh_host": "localhost", "doh_path": "/dns-query"}


def response(query):
    reply = dns.message.make_response(query)
    reply.answer.append(dns.rrset.from_text(query.question[0].name, 300, "IN", "A", "192.0.2.1"))
    return reply


def test_response_validation():
    query = dns.message.make_query("example.com", "A")
    result = Result()
    validate(query, response(query), result)
    assert result.status == "ok"
    assert result.answer_count == 1
    assert result.min_ttl == 300
    reply = response(query)
    reply.id += 1
    with pytest.raises(ValueError, match="does not match"):
        validate(query, reply, Result())


def test_truncated_response_is_not_silently_tcp():
    query = dns.message.make_query("example.com", "A")
    reply = response(query)
    reply.flags |= dns.flags.TC
    with pytest.raises(ValueError, match="fallback deliberately disabled"):
        validate(query, reply, Result())


def test_dns_error_is_distinct_from_success():
    query = dns.message.make_query("example.com", "A")
    reply = response(query)
    reply.set_rcode(dns.rcode.SERVFAIL)
    result = Result()
    validate(query, reply, result)
    assert result.status == "dns_error"
    assert result.rcode == "SERVFAIL"


def test_udp_timeout_keeps_failure_duration_not_latency(monkeypatch):
    def timeout(*args, **kwargs):
        raise dns.exception.Timeout
    monkeypatch.setattr("dns.query.udp", timeout)
    result = Session(RESOLVER, "do53").query("example.com")
    assert result.status == "timeout"
    assert result.total_ms is None
    assert result.query_ms is None
    assert result.elapsed_ms >= 0


def test_dot_new_connection_then_reuse_and_recovery(monkeypatch):
    class Socket:
        def setsockopt(self, *args):
            pass
        def setblocking(self, value):
            assert value is False
        def version(self):
            return "TLSv1.3"
        session_reused = False
        def close(self):
            pass

    session = Session(RESOLVER, "dot")
    monkeypatch.setattr("socket.create_connection", lambda *args: Socket())
    class Context:
        def wrap_socket(self, raw, **kwargs):
            return raw
    session.ctx = Context()
    monkeypatch.setattr("dns.query.tls", lambda query, *args, **kwargs: response(query))
    cold = session.query("example.com")
    warm = session.query("example.com")
    assert cold.status == warm.status == "ok"
    assert cold.new_connection and not cold.reused
    assert warm.reused and not warm.new_connection
    assert cold.connection_id == warm.connection_id
    assert warm.setup_ms == 0
    assert cold.total_ms == pytest.approx(cold.setup_ms + cold.query_ms)
    def eof(*args, **kwargs):
        raise EOFError
    monkeypatch.setattr("dns.query.tls", eof)
    assert session.query("example.com").status == "error"
    assert session.sock is None
    monkeypatch.setattr("dns.query.tls", lambda query, *args, **kwargs: response(query))
    recovered = session.query("example.com")
    assert recovered.new_connection and not recovered.reused
    assert recovered.connection_id != cold.connection_id
    session.close()


@pytest.mark.parametrize("behavior", ["normal", "missing_trace", "reconnect", "bad_content_type"])
def test_doh_trace_accounting_and_reuse(behavior):
    from contextlib import contextmanager

    class Reply:
        http_version = "HTTP/2"
        extensions = {}
        headers = {"content-type": "text/html" if behavior == "bad_content_type" else "application/dns-message"}
        def __init__(self, query):
            self.body = response(query).to_wire()
        def read(self):
            return self.body
        def raise_for_status(self):
            pass

    class Client:
        calls = 0
        @contextmanager
        def stream(self, method, url, content, headers, extensions):
            assert method == "POST"
            assert "127.0.0.1" in url  # No bootstrap DNS lookup.
            assert headers["Host"] == extensions["sni_hostname"] == "localhost"
            trace = extensions["trace"]
            if behavior != "missing_trace" and (not self.calls or behavior == "reconnect"):
                for event in ("connection.connect_tcp.started", "connection.connect_tcp.complete",
                              "connection.start_tls.started", "connection.start_tls.complete"):
                    trace(event, {})
            self.calls += 1
            query = dns.message.from_wire(content)
            assert query.id == 0
            yield Reply(query)
        def close(self):
            pass

    session = Session(RESOLVER, "doh")
    session.client.close()
    session.client = Client()
    cold = session.query("example.com")
    warm = session.query("example.com")
    if behavior in ("missing_trace", "bad_content_type"):
        assert cold.status == warm.status == "error"
        assert cold.total_ms is None
    else:
        assert cold.status == warm.status == "ok"
        assert cold.new_connection and not cold.reused
        assert cold.setup_ms == pytest.approx(cold.tcp_ms + cold.tls_ms)
        assert cold.total_ms == pytest.approx(cold.setup_ms + cold.query_ms)
        if behavior == "normal":
            assert warm.reused and warm.setup_ms == 0
            assert cold.connection_id == warm.connection_id
        else:
            assert warm.new_connection and not warm.reused
            assert cold.connection_id != warm.connection_id
    session.close()
