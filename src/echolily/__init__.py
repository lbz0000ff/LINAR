"""
EchoLily - A natural language processing framework
"""

__version__ = "1.0.0"
__author__ = "EchoLily Team"
__email__ = "contact@echolily.dev"
__license__ = "MIT"

from .core.engine import Engine
from .core.pipeline import Pipeline
from .core.processor import Processor
from .core.config import Config

__all__ = ["Engine", "Pipeline", "Processor", "Config"]
