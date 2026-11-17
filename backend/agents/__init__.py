"""
AI Debate Agents package for TradeLab.

Includes:
- BullAgent: Strictly bullish options strategist
- BearAgent: Strictly bearish options strategist
- JudgeAgent: Impartial institutional risk manager and options desk head
"""

from .bull_agent import BullAgent
from .bear_agent import BearAgent
from .judge_agent import JudgeAgent

__all__ = ["BullAgent", "BearAgent", "JudgeAgent"]
