# -*- coding: utf-8 -*-
"""Application configuration.
Most configuration is set via environment variables.
For local development, use a .env file to set
environment variables.
"""
from environs import Env
import os

file_dir = os.path.dirname(os.path.realpath(__file__))
env = Env()
env.read_env()

ENV = env.str("FLASK_ENV", default="production")
DEBUG = ENV == "development"
# below use '///' for local Windows and '////' for container -> consider autoconfiguring
SQLALCHEMY_DATABASE_URI = f'sqlite:///{file_dir}/data/main.db'
# SECRET_KEY = env.str("SECRET_KEY") skipcq: PY-W0069
# SEND_FILE_MAX_AGE_DEFAULT = env.int("SEND_FILE_MAX_AGE_DEFAULT") skipcq: PY-W0069
BCRYPT_LOG_ROUNDS = env.int("BCRYPT_LOG_ROUNDS", default=13)
DEBUG_TB_ENABLED = DEBUG
DEBUG_TB_INTERCEPT_REDIRECTS = False
CACHE_TYPE = "simple"  # Can be "memcached", "redis", etc.
SQLALCHEMY_TRACK_MODIFICATIONS = False
