import socket

def test_ip():
    hostname = 's3p.cloud.cyfronet.pl'
    ip = socket.gethostbyname(hostname)
    assert ip == '127.0.0.1'