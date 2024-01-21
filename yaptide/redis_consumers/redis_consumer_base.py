from abc import abstractmethod
import logging
from threading import Thread
import time
from flask import Flask
from yaptide.redis.redis import get_redis_client

class RedisConsumerBase(Thread):
    def __init__(self, app: Flask, consumer_name: str, queue_name: str, batch_size: int):
        Thread.__init__(self)
        self.consumer_name = consumer_name
        self.queue_name = queue_name
        self.app = app
        self.batch_size = batch_size

    @abstractmethod
    def handle_message(self, messages) -> None:
        pass
    def log_message_info(self, message: str) -> None:
        logging.info(f"Consumer {self.consumer_name}: {message}")
    def log_message_error(self, message: str) -> None:
        logging.error(f"Consumer {self.consumer_name}: {message}")
    def run(self) -> None:
        self.log_message_info("starts working...")
        redis_client = get_redis_client()
        while True:
            messages = redis_client.lpop(self.queue_name, count = self.batch_size)
            if(messages is not None and len(messages) > 0):
                self.execute_handler(messages)
            else:
                time.sleep(1)

    def execute_handler(self, messages): 
            self.log_message_info(f"Received {len(messages)} messages")
            self.handle_message(messages)
            self.log_message_info(f"Processed messages successfully")