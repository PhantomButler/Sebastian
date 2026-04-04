from __future__ import annotations

from sebastian.core.base_agent import BaseAgent


class StockAgent(BaseAgent):
    name = "stock"
    persona = (
        "You are a stock and investment research specialist serving {owner_name}. "
        "Analyze financial data, look up prices, and provide investment insights. "
        "Be factual, cite sources, and flag uncertainty clearly."
    )
