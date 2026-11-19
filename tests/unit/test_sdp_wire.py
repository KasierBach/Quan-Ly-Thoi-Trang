from app.sockets import ChatSocketHandlers


def test_signaling_preserves_sdp_terminal_crlf(app):
    class Socket:
        pass

    handler = ChatSocketHandlers(Socket(), app)
    wire = 'v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\na=ssrc:1234 msid:- test-track\r\n'
    assert handler._description({'type': 'offer', 'sdp': wire}, 'offer')['sdp'] == wire
    handler.close()
