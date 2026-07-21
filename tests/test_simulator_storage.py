from pathlib import Path
from unittest.mock import Mock, patch

from yaptide.admin.simulator_storage import _is_valid_archive, download_shieldhit_demo_version


def test_is_valid_archive_accepts_real_gzip(tmp_path):
    """A file starting with the gzip magic bytes and a .gz suffix is considered valid"""
    archive_path = tmp_path / "shieldhit.tar.gz"
    archive_path.write_bytes(b"\x1f\x8b" + b"rest of gzip content")
    assert _is_valid_archive(archive_path) is True


def test_is_valid_archive_accepts_real_zip(tmp_path):
    """A file starting with the zip magic bytes and a .zip suffix is considered valid"""
    archive_path = tmp_path / "shieldhit.zip"
    archive_path.write_bytes(b"PK\x03\x04" + b"rest of zip content")
    assert _is_valid_archive(archive_path) is True


def test_is_valid_archive_rejects_html_error_page(tmp_path):
    """An HTML page (e.g. served by a firewall/browser-check instead of the archive) is rejected"""
    archive_path = tmp_path / "shieldhit.tar.gz"
    archive_path.write_bytes(b"<!DOCTYPE html><html>blocked</html>")
    assert _is_valid_archive(archive_path) is False


def test_download_shieldhit_demo_version_fails_gracefully_on_non_archive_response(tmp_path):
    """If shieldhit.org returns something that isn't an archive (e.g. a WAF challenge page),
    the function should return False instead of raising an exception
    """
    fake_response = Mock()
    fake_response.content = b"<!DOCTYPE html><html>blocked by firewall</html>"
    fake_response.raise_for_status = Mock()

    with patch("yaptide.admin.simulator_storage.requests.get", return_value=fake_response):
        result = download_shieldhit_demo_version(destination_dir=Path(tmp_path))

    assert result is False
