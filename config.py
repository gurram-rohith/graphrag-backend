import os
from dotenv import load_dotenv

# This tells Python to look for a .env file locally and load it into memory.
# On Render (where .env doesn't exist), this line safely does nothing!
load_dotenv()

# Now Python grabs the keys from memory (either from .env locally, or Render's dashboard)
URI = os.getenv("NEO4J_URI", "neo4j+s://fallback-uri")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "fallback-password")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "fallback-key")
NVIDIA_CHAT_MODEL: str = os.getenv(
    "NVIDIA_CHAT_MODEL", 
    "nvidia/nemotron-3.5-lightning-30b-a3b"
)
NVIDIA_EMBEDDING_MODEL: str = os.getenv(
    "NVIDIA_EMBEDDING_MODEL", 
    "nvidia/nemotron-3-embed-1b"
)