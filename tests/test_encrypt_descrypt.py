from pathlib import Path
import pytest

from yaptide.admin.simulators import decrypt_file, encrypt_file

@pytest.fixture
def salt() -> str:
    '''Salt for encryption'''
    return 'salt'


@pytest.fixture
def password() -> str:
    '''Password for encryption'''
    return 'password'


def test_enrypt_descrypt(tmpdir, password, salt):
    '''Test encrypting and decrypting a file'''
    # create a file to encrypt in the temporary directory
    plain_file_path = Path(tmpdir) / 'plain.txt'
    encrypted_file_path = Path(tmpdir) / 'encrypted.txt'
    decrypted_file_path = Path(tmpdir) / 'decrypted.txt'
    plain_text_contents = "Hello World!"

    # write some text into the plain file
    plain_file_path.write_text(plain_text_contents, encoding='ascii')

    # check if plain file was created and is not empty
    assert plain_file_path.exists()
    assert plain_file_path.stat().st_size > 0

    # check if encrypted file doesn't exist yet
    assert not encrypted_file_path.exists()

    # encrypt the file
    encrypted_bytes = encrypt_file(file_path=plain_file_path, encryption_password=password, encryption_salt=salt)

    # check if original plain file is untouched
    assert plain_file_path.exists()
    assert plain_file_path.stat().st_size > 0
    assert plain_file_path.read_text(encoding='ascii') == plain_text_contents
    
    # save encrypted bytes to file
    encrypted_file_path.write_bytes(encrypted_bytes)

    # check if encrypted file was created and is not empty
    assert encrypted_file_path.exists()
    assert encrypted_file_path.stat().st_size > 0

    # check if encrypted file is different from plain file
    assert encrypted_file_path.read_bytes() != plain_file_path.read_bytes()

    # decrypt the file
    decrypted_bytes = decrypt_file(file_path=encrypted_file_path, encryption_password=password, encryption_salt=salt)

    # check if decrypted bytes are the same as original plain file
    assert decrypted_bytes == plain_file_path.read_bytes()
    
    # save decrypted bytes to file
    decrypted_file_path.write_bytes(decrypted_bytes)

    # check if decrypted file was created and is not empty
    assert decrypted_file_path.exists()
    assert decrypted_file_path.stat().st_size > 0

    # check if decrypted file is the same as original plain file
    assert decrypted_file_path.read_bytes() == plain_file_path.read_bytes()

