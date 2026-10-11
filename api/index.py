"""Vercel serverless entry point for GitShare API
Based on: https://vercel-fastapi-gamma-smoky.vercel.app/
"""
from fastapi import FastAPI
import sys
from pathlib import Path

# Add project root to Python path for imports
root_path = Path(__file__).parent.parent
sys.path.insert(0, str(root_path))

# Import the main FastAPI application
from src.main import app

# Vercel will serve this app
app = app
