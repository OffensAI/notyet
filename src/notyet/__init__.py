"""
notyet - AWS IAM Eventual Consistency Persistence POC Tool

A security research tool that demonstrates AWS IAM eventual consistency 
vulnerabilities by exploiting the ~4 second propagation window.

Author: Eduard Agavriloae (saw_your_packet)

WARNING: This tool is for security research and educational purposes only.
Do not use in production environments.
"""

__version__ = "0.1.0"

from .event_logger import EventLogger

__all__ = ["EventLogger"]
