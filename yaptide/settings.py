# -*- coding: utf-8 -*-
"""Application configuration.
Most configuration is set via environment variables.
For local development, use a .env file to set
environment variables.
"""
from environs import Env
import os
from sys import platform

# file_dir = os.path.dirname(os.path.realpath(__file__))
env = Env()
env.read_env()

# ENV = env.str("FLASK_ENV", default="production")
# DEBUG = ENV == "development"
# SQLALCHEMY_DATABASE_URI = f'sqlite:////{file_dir}/data/main.db'
# if "win" in platform:
#     SQLALCHEMY_DATABASE_URI = f'sqlite:///{file_dir}/data/main.db'
