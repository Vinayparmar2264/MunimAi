"""
llm.py — MerchAI v6 LLM Blueprint
Fixed problems from v5:
  1. Chatbot now connects to actual database — reads the current shop's products
  2. Response formatting is clean: paragraphs, bullets, proper spacing
  3. Shop data is fully isolated — chatbot only reads the correct shop's products
  4. Sensitive data (stock levels, cost, margins, internal metrics) is NEVER sent to LLM
  5. If customer asks for sensitive info, chatbot politely redirects
  6. Works for both shopkeeper mode (full context) and customer mode (public info only)

Routes:
  POST /llm/chat          — streaming chat with shop-aware context
  POST /llm/summary       — product summary for shopkeeper
  POST /llm/insight       — topic insight
  POST /llm/action-plan   — 7-day action plan
  POST /llm/compare       — compare what-if scenarios
  POST /llm/shop-chat     — customer-facing chatbot (public info only)
  GET  /llm/status        — API key status check
"""

import os
import json
from flask import (Blueprint, request, jsonify, Response,
                   session, stream_with_context)
from openrouter import OpenRouter

llm_bp = Blueprint("llm", __name__, url_prefix="/llm")

DEFAULT_MODEL = "inclusionai/ling-2.6-flash:free"

# ── Sensitive fields that must NEVER be sent to the customer chatbot ─────────
PRIVATE_FIELDS = {
    "stock", "cost_price", "current_margin_pct", "current_margin_value",
    "max_discount_pct", "min_acceptable_price", "safety_stock",
    "rop", "eoq", "order_qty", "order_action", "order_urgency",
    "at_risk_units", "at_risk_value", "stockout_prob", "health_score",
    "carrying_cost_monthly", "gmroi", "annual_value", "fill_rate",
    "confidence_pct", "turnover_ratio", "days_remaining",
}

# ── Keywords that signal a customer is asking for sensitive info ──────────────
SENSITIVE_KEYWORDS = [
    "stock", "how many units", "inventory", "cost", "margin", "profit",
    "markup", "supply", "reorder", "order quantity", "safety stock",
    "internal", "how much do you have", "how much stock", "shortage",
    "running out", "low stock", "out of stock",
]


def _api_key():
    return os.environ.get("OPENROUTER_API_KEY", "")


def _call(system: str, messages: list, max_tokens: int = 1200):
    """Call OpenRouter and return response content."""
    formatted = [{"role": "system", "content": system}] + messages
    with OpenRouter(api_key=_api_key()) as client:
        response = client.chat.send(
            model=DEFAULT_MODEL,
            messages=formatted,
            max_tokens=max_tokens
        )
    return response.choices[0].message.content


def _is_sensitive_question(text: str) -> bool:
    """Check if customer message is asking for private shop data."""
    t = text.lower()
    return any(kw in t for kw in SENSITIVE_KEYWORDS)


# ── SHOPKEEPER SYSTEM PROMPT ──────────────────────────────────────────────────
def _shopkeeper_system_prompt(analysis: dict, product_name: str = "") -> str:
    """
    Full context prompt for shopkeeper — includes all analysis data.
    Formatted clearly so the LLM produces structured, readable output.
    """
    if not analysis:
        return """You are MerchAI Assistant — a friendly retail advisor for shopkeepers.
Give specific, actionable advice in plain language. Use real numbers when available.

Format your responses clearly:
- Use short paragraphs (2-3 sentences each)
- Use bullet points for lists of items or steps
- Put the most important point first
- Keep language simple and direct
- Avoid jargon"""

    # Build a clean, structured context — no sensitive raw cost data
    ctx_parts = [
        f"Product: {product_name or analysis.get('category','Product')}",
        f"Category: {analysis.get('category','')}",
        f"Selling price: ₹{analysis.get('current_price',0)}",
        f"Competitor price status: {analysis.get('comp_status','Unknown')} — {analysis.get('comp_msg','')}",
        f"",
        f"DEMAND FORECAST:",
        f"  Next 7 days: {analysis.get('predicted_demand',0)} units",
        f"  Next 30 days: {analysis.get('forecast_d30',0)} units",
        f"  Trend: {analysis.get('trend','Stable')} ({analysis.get('intensity','Stable')})",
        f"  Daily velocity: {analysis.get('forecast_daily',0)} units/day",
        f"",
        f"INVENTORY STATUS:",
        f"  Stock zone: {analysis.get('zone_label','Unknown')}",
        f"  Days of stock remaining: {analysis.get('days_to_sell',0)} days",
        f"  Will sell before expiry: {'Yes' if analysis.get('will_sell_before_expiry') else 'No'}",
        f"  Expiry in: {analysis.get('expiry_days',0)} days",
        f"  Inventory health score: {analysis.get('health_score',0)}/100 ({analysis.get('health_grade','')})",
        f"",
        f"PRICING ADVICE:",
        f"  Discount recommendation: {analysis.get('discount_tier','NONE')}",
        f"  Recommended discount: {analysis.get('discount_pct',0)}%",
        f"  Reason: {analysis.get('discount_reason','')}",
        f"",
        f"ORDER ADVICE:",
        f"  Action needed: {analysis.get('order_action','KEEP_STOCK')}",
        f"  Recommendation: {analysis.get('order_msg','')}",
        f"  Units to order for next {analysis.get('reorder_window_days',7)} days: {analysis.get('window_reorder_qty',0)}",
        f"",
        f"PERFORMANCE:",
        f"  Customer satisfaction score: {analysis.get('csat_score',0)}/100 ({analysis.get('csat_level','')})",
        f"  Expected 30-day revenue: ₹{analysis.get('projected_revenue_30d',0):,}",
        f"  Expected 30-day profit: ₹{analysis.get('projected_profit_30d',0):,}",
        f"  Risk summary: {analysis.get('risk_msg','')}",
    ]
    context = "\n".join(ctx_parts)

    return f"""You are MerchAI Assistant — a friendly, expert retail advisor helping a shopkeeper manage their inventory and pricing.

You have full access to the AI analysis for this product. Use the data below to give specific, accurate, actionable advice.

{context}

RESPONSE FORMATTING RULES (follow these exactly):
1. Start with the most important point in 1-2 sentences
2. Use short paragraphs — 2 to 3 sentences each, with a blank line between paragraphs
3. Use bullet points (•) when listing multiple items, steps, or options
4. Use **bold** for key numbers, action words, and critical advice
5. Never dump all data at once — answer the specific question asked
6. End with one clear next action the shopkeeper should take
7. Keep total response under 300 words unless a detailed plan is requested
8. Do not use headers with # symbols — use plain text section labels if needed"""


# ── CUSTOMER SYSTEM PROMPT (public info only) ─────────────────────────────────
def _customer_system_prompt(shop_name: str, public_products: list) -> str:
    """
    Customer-facing chatbot prompt.
    Only includes public product info — NO stock, cost, or internal metrics.
    """
    if public_products:
        product_lines = []
        for p in public_products[:20]:  # limit to 20 products
            line = f"  • {p['product_name']}"
            if p.get("brand_name"):
                line += f" ({p['brand_name']})"
            line += f" — ₹{p['current_price']}"
            if p.get("competitor_price") and p["competitor_price"] > 0:
                line += f" (competitor: ₹{p['competitor_price']})"
            if p.get("discount_pct") and p["discount_pct"] > 0:
                line += f" — **{p['discount_pct']}% OFF** → ₹{p.get('discounted_price', p['current_price'])}"
            if p.get("expiry_days") and p["expiry_days"] <= 7:
                line += f" ⚠ Expires in {p['expiry_days']} days"
            elif p.get("expiry_days"):
                line += f" (fresh for {p['expiry_days']} more days)"
            if p.get("is_expired"):
                line += " [EXPIRED]"
            product_lines.append(line)
        product_context = "\n".join(product_lines)
    else:
        product_context = "  No products listed yet."

    return f"""You are the friendly customer assistant for {shop_name}.
You help customers find products, understand prices, check discounts, and make good purchase decisions.

AVAILABLE PRODUCTS AT {shop_name.upper()}:
{product_context}

STRICT RULES — follow these without exception:
1. NEVER mention stock levels, inventory counts, or how many units are available
2. NEVER mention cost price, purchase price, or the shop's profit margin
3. NEVER discuss internal shop operations, supplier details, or reorder info
4. NEVER reveal health scores, risk metrics, or any internal analytics
5. If a customer asks about stock availability or inventory, say: "Please ask the shopkeeper directly for the latest availability."
6. If asked about pricing strategy or how much the shop paid, politely redirect to product value

WHAT YOU CAN HELP WITH:
• Product prices and discounts currently available
• Comparing prices with competitors when info is available
• Suggesting products based on category or budget
• Expiry information (freshness) of perishable items
• General shopping advice

RESPONSE FORMAT:
• Keep responses friendly, short, and helpful
• Use bullet points for product lists or comparisons
• Use **bold** for prices and discount amounts
• Answer the question directly — don't give unnecessary background
• If you cannot help with something, suggest the customer speak to the shopkeeper"""


# ═══════════════════════════════════════════════════════════════
# HELPER: Load analysis context from session or DB
# ═══════════════════════════════════════════════════════════════

def _load_shopkeeper_context(product_id=None, shop_id=None):
    """
    Load analysis for shopkeeper context.
    Tries DB first (if product_id given), falls back to session.
    """
    if product_id:
        user_id = session.get("user_id")
        if user_id:
            from database import get_analysis, get_product
            analysis = get_analysis(int(product_id), user_id)
            prod     = get_product(int(product_id), user_id)
            if analysis and prod:
                return analysis, prod.get("product_name", "Product")
    # Fallback to session
    return session.get("analysis", {}), session.get("raw_input", {}).get("product_name", "Product")


def _load_customer_context(shop_id):
    """Load public product data for customer chatbot."""
    from database import get_shop, get_public_shop_products
    shop     = get_shop(int(shop_id)) if shop_id else None
    products = get_public_shop_products(int(shop_id)) if shop_id else []
    shop_name = shop["shop_name"] if shop else "this shop"
    return shop_name, products


# ── FORMAT RESPONSE TEXT ────────────────────────────────────────
def _format_streaming_token(token: str) -> str:
    """
    Escape token for SSE streaming.
    Preserves newlines so the frontend can render proper paragraphs.
    """
    return token.replace("\n", "\\n")


# ═══════════════════════════════════════════════════════════════
# SHOPKEEPER CHAT (streaming, full analysis context)
# ═══════════════════════════════════════════════════════════════

@llm_bp.route("/chat", methods=["POST"])
def chat():
    if not _api_key():
        return jsonify({"error": "OPENROUTER_API_KEY not configured"}), 401

    body     = request.get_json() or {}
    user_msg = body.get("message", "").strip()
    history  = body.get("history", [])
    pid      = body.get("product_id")
    sid      = body.get("shop_id") or session.get("current_shop_id")

    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    analysis, pname = _load_shopkeeper_context(pid, sid)
    system   = _shopkeeper_system_prompt(analysis, pname)
    messages = history[-10:] + [{"role": "user", "content": user_msg}]

    def generate():
        try:
            text = _call(system, messages)

            # Stream word by word with newline preservation
            # Split on spaces but keep newline sequences intact
            import re
            tokens = re.split(r"(\s+)", text)
            for token in tokens:
                if token:
                    escaped = _format_streaming_token(token)
                    yield f"data: {escaped}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: ⚠ Error: {str(e)}\n\n"
            yield "data: [DONE]\n\n"

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no",
                             "Cache-Control": "no-cache"})


# ═══════════════════════════════════════════════════════════════
# CUSTOMER SHOP CHAT (public info only, no sensitive data)
# ═══════════════════════════════════════════════════════════════

@llm_bp.route("/shop-chat", methods=["POST"])
def shop_chat():
    """
    Customer-facing chatbot. Reads only public product data for the shop.
    Refuses to answer questions about stock, cost, margins, or internal ops.
    """
    if not _api_key():
        return jsonify({"error": "OPENROUTER_API_KEY not configured"}), 401

    body     = request.get_json() or {}
    user_msg = body.get("message", "").strip()
    history  = body.get("history", [])
    shop_id  = body.get("shop_id") or session.get("viewing_shop_id")

    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    if not shop_id:
        return jsonify({"error": "No shop specified"}), 400

    # Hard guard: if the question is clearly about sensitive data,
    # return a polite redirect without even calling the LLM
    if _is_sensitive_question(user_msg):
        polite_response = (
            "I'm not able to share information about stock levels or inventory details. "
            "For the latest availability, please ask the shopkeeper directly.\n\n"
            "I can help you with **product prices**, **current discounts**, "
            "**freshness information**, and **product comparisons**. "
            "What would you like to know?"
        )
        return jsonify({"reply": polite_response})

    shop_name, products = _load_customer_context(shop_id)
    system   = _customer_system_prompt(shop_name, products)
    messages = history[-8:] + [{"role": "user", "content": user_msg}]

    def generate():
        try:
            text = _call(system, messages, max_tokens=600)
            import re
            tokens = re.split(r"(\s+)", text)
            for token in tokens:
                if token:
                    escaped = _format_streaming_token(token)
                    yield f"data: {escaped}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: ⚠ Error: {str(e)}\n\n"
            yield "data: [DONE]\n\n"

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no",
                             "Cache-Control": "no-cache"})


# ═══════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════

@llm_bp.route("/summary", methods=["POST"])
def summary():
    if not _api_key():
        return jsonify({"error": "OPENROUTER_API_KEY not configured"}), 401

    body     = request.get_json() or {}
    pid      = body.get("product_id")
    analysis, pname = _load_shopkeeper_context(pid)

    prompt = (
        f"Give a clear 3-paragraph summary of the current situation for {pname}.\n"
        "Paragraph 1: What the sales forecast looks like and the demand trend.\n"
        "Paragraph 2: The inventory situation and whether action is needed.\n"
        "Paragraph 3: The single most important thing the shopkeeper should do right now.\n"
        "Use **bold** for key numbers and actions. Keep each paragraph to 2-3 sentences."
    )

    system = _shopkeeper_system_prompt(analysis, pname)
    text   = _call(system, [{"role": "user", "content": prompt}])
    return jsonify({"summary": text})


# ═══════════════════════════════════════════════════════════════
# INSIGHT
# ═══════════════════════════════════════════════════════════════

@llm_bp.route("/insight", methods=["POST"])
def insight():
    if not _api_key():
        return jsonify({"error": "OPENROUTER_API_KEY not configured"}), 401

    body     = request.get_json() or {}
    topic    = body.get("topic", "general")
    pid      = body.get("product_id")
    analysis, pname = _load_shopkeeper_context(pid)

    prompt = (
        f"Explain '{topic}' for this product in simple, practical terms.\n"
        "Give a 2-3 sentence explanation, then bullet-point 2-3 specific actions "
        "the shopkeeper can take right now based on the data.\n"
        "Use **bold** for the most important number or action."
    )

    system = _shopkeeper_system_prompt(analysis, pname)
    text   = _call(system, [{"role": "user", "content": prompt}])
    return jsonify({"insight": text})


# ═══════════════════════════════════════════════════════════════
# ACTION PLAN
# ═══════════════════════════════════════════════════════════════

@llm_bp.route("/action-plan", methods=["POST"])
def action_plan():
    if not _api_key():
        return jsonify({"error": "OPENROUTER_API_KEY not configured"}), 401

    body     = request.get_json() or {}
    pid      = body.get("product_id")
    analysis, pname = _load_shopkeeper_context(pid)

    prompt = (
        f"Create a clear 7-day action plan for {pname}.\n"
        "Format as:\n"
        "**Today:** [action]\n"
        "**Day 2-3:** [action]\n"
        "**Day 4-5:** [action]\n"
        "**Day 6-7:** [action]\n"
        "**End of week check:** [what to measure]\n\n"
        "Base every action on the actual data provided. "
        "Be specific with numbers. Keep each action to 1-2 sentences."
    )

    system = _shopkeeper_system_prompt(analysis, pname)
    text   = _call(system, [{"role": "user", "content": prompt}], max_tokens=500)
    return jsonify({"plan": text})


# ═══════════════════════════════════════════════════════════════
# COMPARE SCENARIOS
# ═══════════════════════════════════════════════════════════════

@llm_bp.route("/compare", methods=["POST"])
def compare():
    if not _api_key():
        return jsonify({"error": "OPENROUTER_API_KEY not configured"}), 401

    body      = request.get_json() or {}
    scenarios = body.get("scenarios", [])
    pid       = body.get("product_id")
    analysis, pname = _load_shopkeeper_context(pid)

    if not scenarios:
        return jsonify({"error": "No scenarios provided"}), 400

    sc_text = "\n".join([
        f"  Scenario '{s['label']}': "
        f"Price ₹{s.get('price',0)}, "
        f"Profit ₹{int(s.get('profit_30d',0)):,}, "
        f"Health {s.get('health_score',0)}/100, "
        f"Customer Score {s.get('csat_score',0)}/100"
        for s in scenarios
    ])

    prompt = (
        f"Compare these scenarios for {pname}:\n{sc_text}\n\n"
        "Write 3 short paragraphs:\n"
        "1. Which scenario gives the most profit and why\n"
        "2. Which scenario gives the best customer experience\n"
        "3. Your final recommendation — which scenario to choose and why\n\n"
        "Use **bold** for the winning scenario name and key numbers. "
        "Be specific and direct."
    )

    system = _shopkeeper_system_prompt(analysis, pname)
    text   = _call(system, [{"role": "user", "content": prompt}], max_tokens=400)
    return jsonify({"comparison": text})


# ═══════════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════════

@llm_bp.route("/status")
def status():
    key = _api_key()
    return jsonify({
        "configured": bool(key),
        "model": DEFAULT_MODEL,
        "version": "v6",
        "features": ["shopkeeper_chat", "customer_chat", "shop_isolation",
                     "sensitive_data_guard", "clean_formatting"]
    })