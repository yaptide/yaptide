import os

def test_setting_secrets():
    """Check if secrets are set"""
    assert os.environ.get('S3_ENDPOINT') is not None
    assert os.environ.get('S3_ACCESS_KEY') is not None
    assert os.environ.get('S3_SECRET_KEY') is not None
    assert os.environ.get('S3_ENCRYPTION_KEY') is not None
