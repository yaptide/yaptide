import socket

def test_ip():
    hostname = 's3p.cloud.cyfronet.pl'
    ip = socket.gethostbyname(hostname)
    assert ip in ('149.156.237.14', '149.156.237.13')