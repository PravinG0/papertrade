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
from .report_agent import ReportAgent, report_agent
from .daily_report_agent import DailyReportAgent, daily_report_agent

__all__ = [
    "BullAgent",
    "BearAgent",
    "JudgeAgent",
    "ReportAgent",
    "report_agent",
    "DailyReportAgent",
    "daily_report_agent",
]
