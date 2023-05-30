import boto3
import os
from cryptography.fernet import Fernet
import sys
import tempfile
from botocore.exceptions import NoCredentialsError, EndpointConnectionError, ClientError
from pathlib import Path


def encrypt_file(file_path: Path, key: str) -> Path:
    """Encrypts a file using Fernet"""
    with open(file_path, "rb") as file:
        original = file.read()
    fernet = Fernet(key)
    encrypted = fernet.encrypt(original)
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file.write(encrypted)
    return Path(temp_file.name)


def upload_file_to_s3(
    endpoint: str,
    access_key: str,
    secret_key: str,
    encryption_key: str,
    file_path: Path,
    bucket: str,
) -> None:
    """Uploads a file to S3 bucket"""
    # Create S3 client
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint,
    )
    # Check if connection to S3 is possible
    try:
        s3_client.list_buckets()
    except NoCredentialsError as e:
        raise Exception(
            "No credentials found. Check your access key and secret key."
        ) from e
    except EndpointConnectionError as e:
        raise Exception("Could not connect to the specified endpoint.") from e
    except ClientError as e:
        raise Exception(
            "An error occurred while connecting to S3:", e.response["Error"]["Message"]
        ) from e

    # Check if bucket exists and create if not
    if bucket not in [bucket["Name"] for bucket in s3_client.list_buckets()["Buckets"]]:
        print("Bucket does not exist. Creating bucket.")
        s3_client.create_bucket(Bucket=bucket)

    # Encrypt file
    encrypted_file_path = encrypt_file(file_path, encryption_key)
    try:
        # Upload encrypted file to S3 bucket
        print("Uploading file.")
        s3_client.upload_file(encrypted_file_path, bucket, os.path.basename(file_path))
        print("Upload successful.")
    except ClientError as e:
        raise Exception("Upload failed:", e.response["Error"]["Message"]) from e


def main():
    if "YAPTIDE_S3_CONFIG" not in os.environ:
        raise Exception("YAPTIDE_S3_CONFIG environment variable not set.")
    endpoint, access_key, secret_key, encryption_key = os.environ["YAPTIDE_S3_CONFIG"].split()
    if len(sys.argv) != 3:
        raise Exception("Wrong number of arguments <path> <bucket> needed.")
    path = Path(sys.argv[1])
    bucket = sys.argv[2]
    # Check if file exists
    if not os.path.exists(path):
        raise Exception("File does not exist.")
    upload_file_to_s3(endpoint, access_key, secret_key, encryption_key, path, bucket)


if __name__ == "__main__":
    main()
