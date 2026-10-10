"""Entry point for running as: python -m proxify"""
from dotenv import load_dotenv

load_dotenv()

import asyncio
import logging
from proxify.server import run_server

def main():
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logging.info("Exited.")

if __name__ == "__main__":
    main()
