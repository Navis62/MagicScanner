"""Reconnaissance d'une carte à partir d'une image webcam."""
from .recognizer import Recognition, Recognizer
from .scoring import Candidate

__all__ = ["Candidate", "Recognition", "Recognizer"]
