import socket

def test_ip():
    hostname = 's3p.cloud.cyfronet.pl'
    ip = socket.gethostbyname(hostname)
    assert ip == '149.156.237.14' or ip == '149.156.237.13'