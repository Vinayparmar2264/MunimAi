"""
llm.py — MerchAI v6 LLM Blueprint (Groq API Integration)
Secured and Isolated Multi-Tenant Assistant
"""

import os
import json
import re
import requests
from flask import (Blueprint, request, jsonify, Response,
                   session, stream_with_context)

llm_bp = Blueprint("llm", __name__, url_prefix="/llm")

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
    return os.environ.get("GROQ_API_KEY") or ""


def _call(system: str, messages: list, max_tokens: int = 1200) -> str:
    """Call Groq API and return response content (non-streaming)."""
    api_key = _api_key()
    if not api_key:
        raise ValueError("Groq API key (GROQ_API_KEY) not configured in .env")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": False
    }
    
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )
    
    if response.status_code != 200:
        raise Exception(f"Groq API Error (Status {response.status_code}): {response.text}")
        
    res_json = response.json()
    return res_json["choices"][0]["message"]["content"]


def _call_stream(system: str, messages: list, max_tokens: int = 1200):
    """Call Groq API and stream delta content."""
    api_key = _api_key()
    if not api_key:
        raise ValueError("Groq API key (GROQ_API_KEY) not configured in .env")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": True
    }
    
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        stream=True,
        timeout=30
    )
    
    if response.status_code != 200:
        raise Exception(f"Groq API Error (Status {response.status_code}): {response.text}")
        
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8').strip()
            if decoded_line.startswith("data: "):
                data_str = decoded_line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data_json = json.loads(data_str)
                    delta = data_json["choices"][0]["delta"]
                    if "content" in delta:
                        yield delta["content"]
                except Exception:
                    pass


def _is_sensitive_question(text: str) -> bool:
    """Check if customer message is asking for private shop data."""
    t = text.lower()
    return any(kw in t for kw in SENSITIVE_KEYWORDS)


# ── SYSTEM PROMPTS ────────────────────────────────────────────────────────────

def _shopkeeper_system_prompt(analysis: dict, product_name: str = "") -> str:
    """Full context prompt for shopkeeper — includes all analysis data."""
    if not analysis:
        return """You are MunimAI Assistant — a friendly retail advisor for shopkeepers.
Give specific, actionable advice in plain language. Use real numbers when available.

Format your responses clearly:
- Use short paragraphs (2-3 sentences each)
- Use bullet points for lists of items or steps
- Put the most important point first
- Keep language simple and direct
- Avoid jargon"""

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

    return f"""You are MunimAI Assistant — a friendly, expert retail advisor helping a shopkeeper manage their inventory and pricing.

You have access to the AI analysis for this product. Use the data below to give specific, accurate, actionable advice.

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


def _customer_system_prompt(shop_name: str, public_products: list) -> str:
    """Customer-facing chatbot prompt (public info only)."""
    if public_products:
        product_lines = []
        for p in public_products[:20]:
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


# ── CONTEXT BUILDERS ──────────────────────────────────────────────────────────

def _load_shopkeeper_context(product_id=None, shop_id=None):
    """Fallback utility for compatibility - loads context for a single product."""
    if product_id:
        user_id = session.get("user_id")
        if user_id:
            from database import get_analysis, get_product
            analysis = get_analysis(int(product_id), user_id)
            prod     = get_product(int(product_id), user_id)
            if analysis and prod:
                return analysis, prod.get("product_name", "Product")
    return session.get("analysis", {}), session.get("raw_input", {}).get("product_name", "Product")


def _build_shopkeeper_prompt_context(user_id, product_id=None, shop_id=None):
    """Build a comprehensive context of the shopkeeper's data, strictly isolated."""
    from database import get_shops_by_owner, get_all_products, get_all_analyses
    
    shops = get_shops_by_owner(user_id)
    products = get_all_products(user_id)
    analyses = get_all_analyses(user_id)
    
    ctx = []
    ctx.append(f"Shopkeeper Name: {session.get('user_name', 'Shopkeeper')}")
    ctx.append("SHOPS OWNED BY THIS SHOPKEEPER:")
    for s in shops:
        ctx.append(f"  - Shop ID {s['id']}: '{s['shop_name']}' at location '{s['shop_location']}'")
        
    ctx.append("\nALL PRODUCTS AND ANALYSIS FOR THIS SHOPKEEPER:")
    for p in products:
        p_analysis = next((a for a in analyses if a["product_id"] == p["id"]), None)
        line = f"  - Product ID {p['id']} in Shop {p['shop_id']}: '{p['product_name']}'"
        if p.get("brand_name"):
            line += f" ({p['brand_name']})"
        line += f" | Category: {p['category']} | Price: ₹{p['current_price']} | Cost: ₹{p['cost_price']} | Stock: {p['stock']} units"
        
        if p_analysis:
            d = p_analysis["analysis"]
            line += f" | Health Score: {d.get('health_score','—')}/100 | Recommended Discount: {d.get('discount_pct', 0)}% | Reorder Action: {d.get('order_action', 'KEEP_STOCK')}"
        ctx.append(line)
        
    active_analysis = {}
    active_pname = "Product"
    if product_id:
        from database import get_product, get_analysis
        prod = get_product(int(product_id), user_id)
        if prod:
            active_pname = prod.get("product_name", "Product")
            analysis = get_analysis(int(product_id), user_id)
            if analysis:
                active_analysis = analysis
                ctx.append(f"\nACTIVE PRODUCT IN FOCUS: '{active_pname}'")
                ctx.append(f"  - Selling Price: ₹{analysis.get('current_price', 0)}")
                ctx.append(f"  - Cost Price: ₹{analysis.get('cost_price', 0)}")
                ctx.append(f"  - Stock Level: {analysis.get('stock', 0)} units")
                ctx.append(f"  - Expiry Days Remaining: {analysis.get('expiry_days', 0)} days")
                ctx.append(f"  - Inventory Health Score: {analysis.get('health_score', 0)}/100")
                ctx.append(f"  - Reorder Advice: {analysis.get('order_msg', '')}")
                ctx.append(f"  - Pricing recommendation: {analysis.get('discount_reason', '')}")
                ctx.append(f"  - 30d projected revenue: ₹{analysis.get('projected_revenue_30d', 0):,}")
                ctx.append(f"  - 30d projected profit: ₹{analysis.get('projected_profit_30d', 0):,}")
                
    return "\n".join(ctx), active_pname, active_analysis


def _build_visitor_prompt_context():
    """Build context for guest visitor using session data (no DB queries)."""
    analysis = session.get("analysis", {})
    raw_input = session.get("raw_input", {})
    pname = raw_input.get("product_name", "Product")
    
    ctx = []
    ctx.append("Guest Visitor (Not Logged In)")
    ctx.append("SESSION ANALYSIS DATA FOR CURRENT PRODUCT:")
    if analysis:
        ctx.append(f"  - Product Name: '{pname}'")
        ctx.append(f"  - Category: {analysis.get('category','')}")
        ctx.append(f"  - Selling Price: ₹{analysis.get('current_price', 0)}")
        ctx.append(f"  - Cost Price: ₹{analysis.get('cost_price', 0)}")
        ctx.append(f"  - Stock: {analysis.get('stock', 0)} units")
        ctx.append(f"  - Forecast (7d): {analysis.get('predicted_demand', 0)} units")
        ctx.append(f"  - Inventory Health Score: {analysis.get('health_score', 0)}/100")
        ctx.append(f"  - Recommended discount: {analysis.get('discount_pct', 0)}% ({analysis.get('discount_reason', '')})")
        ctx.append(f"  - Reorder action: {analysis.get('order_msg', '')}")
    else:
        ctx.append("  No active session analysis. Answer general queries only.")
        
    return "\n".join(ctx), pname, analysis


def _build_customer_prompt_context(user_id, shop_id):
    """Build public-only customer context including user location and shop catalog."""
    from database import get_user_by_id, get_shop, get_public_shop_products
    
    user = get_user_by_id(user_id)
    shop = get_shop(int(shop_id))
    products = get_public_shop_products(int(shop_id))
    
    shop_name = shop["shop_name"] if shop else "this shop"
    
    ctx = []
    ctx.append(f"Customer Name: {user['name']}")
    ctx.append(f"Customer Email: {user['email']}")
    ctx.append(f"Customer Location: {user.get('location_name', 'Unknown')}")
    if user.get("latitude") and user.get("longitude"):
        ctx.append(f"Customer Coordinates: Latitude {user['latitude']}, Longitude {user['longitude']}")
        if shop and shop.get("latitude") and shop.get("longitude"):
            from database import _haversine
            dist = _haversine(user["latitude"], user["longitude"], shop["latitude"], shop["longitude"])
            ctx.append(f"Distance to shop: {dist:.2f} km")
            
    ctx.append(f"\nSHOP CATALOG FOR {shop_name.upper()} (ONLY PUBLIC DATA IS ACCESSIBLE):")
    for p in products:
        line = f"  • {p['product_name']}"
        if p.get("brand_name"):
            line += f" ({p['brand_name']})"
        line += f" — price: ₹{p['current_price']}"
        if p.get("discount_pct") and p["discount_pct"] > 0:
            line += f" ({p['discount_pct']}% OFF → discounted price: ₹{p['discounted_price']})"
        if p.get("expiry_days"):
            if p["expiry_days"] <= 0:
                line += " [EXPIRED]"
            elif p["expiry_days"] <= 7:
                line += f" [Expires in {p['expiry_days']} days!]"
            else:
                line += f" [Fresh for {p['expiry_days']} days]"
        ctx.append(line)
        
    ctx.append("\nSECURITY RULES:")
    ctx.append("- NEVER disclose stock levels, cost prices, internal margins, reorder details, health scores, or carrying costs.")
    ctx.append("- If asked about inventory availability, redirect politely: 'Please ask the shopkeeper directly for the latest availability.'")
    ctx.append("- Never access or reveal other customer profiles or details.")
    
    return "\n".join(ctx), shop_name, products


def _format_streaming_token(token: str) -> str:
    """Escape token for SSE streaming. Preserves newlines."""
    return token.replace("\n", "\\n")


# ── SHOPKEEPER & GUEST CHAT (streaming) ───────────────────────────────────────

@llm_bp.route("/chat", methods=["POST"])
def chat():
    # Enforce basic key existence check
    if not _api_key():
        return jsonify({"error": "Groq API key (GROQ_API_KEY) not configured"}), 401

    body     = request.get_json() or {}
    user_msg = body.get("message", "").strip()
    history  = body.get("history", [])
    pid      = body.get("product_id")
    sid      = body.get("shop_id") or session.get("current_shop_id")

    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    user_id = session.get("user_id")
    if user_id:
        # Shopkeeper route - verify role & ownership
        role = session.get("user_role")
        if role not in ("shopkeeper", "admin"):
            return jsonify({"error": "Forbidden: Only shopkeepers can access this route"}), 403
            
        if pid:
            from database import get_product
            p = get_product(int(pid), user_id)
            if not p:
                return jsonify({"error": "Forbidden: Product not found or does not belong to you"}), 403
                
        if sid:
            from database import get_shop
            s = get_shop(int(sid), user_id)
            if not s:
                return jsonify({"error": "Forbidden: Shop not found or does not belong to you"}), 403

        context, pname, analysis = _build_shopkeeper_prompt_context(user_id, pid, sid)
    else:
        # Guest Visitor route - ignore any sent DB product_id/shop_id to avoid unauthorized lookups
        context, pname, analysis = _build_visitor_prompt_context()

    system   = _shopkeeper_system_prompt(analysis, pname)
    # Inject full isolated context into the system prompt prefix
    system = f"{context}\n\n{system}"
    messages = history[-10:] + [{"role": "user", "content": user_msg}]

    def generate():
        try:
            for content in _call_stream(system, messages):
                escaped = _format_streaming_token(content)
                yield f"data: {escaped}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: ⚠ Error: {str(e)}\n\n"
            yield "data: [DONE]\n\n"

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no",
                             "Cache-Control": "no-cache"})


# ── CUSTOMER SHOP CHAT (streaming, public-info only) ──────────────────────────

@llm_bp.route("/shop-chat", methods=["POST"])
def shop_chat():
    if not _api_key():
        return jsonify({"error": "Groq API key (GROQ_API_KEY) not configured"}), 401

    body     = request.get_json() or {}
    user_msg = body.get("message", "").strip()
    history  = body.get("history", [])
    shop_id  = body.get("shop_id") or session.get("viewing_shop_id")

    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    if not shop_id:
        return jsonify({"error": "No shop specified"}), 400

    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Unauthorized: Please log in to use the assistant"}), 401

    # Hard guard: redirect sensitive queries before they reach Groq
    if _is_sensitive_question(user_msg):
        polite_response = (
            "I'm not able to share information about stock levels or inventory details. "
            "For the latest availability, please ask the shopkeeper directly.\n\n"
            "I can help you with **product prices**, **current discounts**, "
            "**freshness information**, and **product comparisons**. "
            "What would you like to know?"
        )
        return jsonify({"reply": polite_response})

    # Load customer coordinates, locations, and public products
    context, shop_name, public_products = _build_customer_prompt_context(user_id, shop_id)
    system   = _customer_system_prompt(shop_name, public_products)
    system = f"{context}\n\n{system}"
    messages = history[-8:] + [{"role": "user", "content": user_msg}]

    def generate():
        try:
            for content in _call_stream(system, messages, max_tokens=600):
                escaped = _format_streaming_token(content)
                yield f"data: {escaped}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: ⚠ Error: {str(e)}\n\n"
            yield "data: [DONE]\n\n"

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no",
                             "Cache-Control": "no-cache"})


# ── SUMMARY ───────────────────────────────────────────────────────────────────

@llm_bp.route("/summary", methods=["POST"])
def summary():
    if not _api_key():
        return jsonify({"error": "Groq API key not configured"}), 401

    body = request.get_json() or {}
    pid  = body.get("product_id")
    sid  = body.get("shop_id")

    user_id = session.get("user_id")
    if user_id:
        role = session.get("user_role")
        if role not in ("shopkeeper", "admin"):
            return jsonify({"error": "Forbidden: Only shopkeepers can view summaries"}), 403
        if pid:
            from database import get_product
            p = get_product(int(pid), user_id)
            if not p:
                return jsonify({"error": "Forbidden: Product does not belong to you"}), 403
        analysis, pname = _load_shopkeeper_context(pid, sid)
    else:
        analysis = session.get("analysis", {})
        pname = session.get("raw_input", {}).get("product_name", "Product")

    if not analysis:
        return jsonify({"error": "No product analysis data available"}), 400

    prompt = (
        f"Give a clear 3-paragraph summary of the current situation for {pname}.\n"
        "Paragraph 1: What the sales forecast looks like and the demand trend.\n"
        "Paragraph 2: The inventory situation and whether action is needed.\n"
        "Paragraph 3: The single most important thing the shopkeeper should do right now.\n"
        "Use **bold** for key numbers and actions. Keep each paragraph to 2-3 sentences."
    )

    system = _shopkeeper_system_prompt(analysis, pname)
    try:
        text   = _call(system, [{"role": "user", "content": prompt}])
        return jsonify({"summary": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── INSIGHT ───────────────────────────────────────────────────────────────────

@llm_bp.route("/insight", methods=["POST"])
def insight():
    if not _api_key():
        return jsonify({"error": "Groq API key not configured"}), 401

    body  = request.get_json() or {}
    topic = body.get("topic", "general")
    pid   = body.get("product_id")
    sid   = body.get("shop_id")

    user_id = session.get("user_id")
    if user_id:
        role = session.get("user_role")
        if role not in ("shopkeeper", "admin"):
            return jsonify({"error": "Forbidden: Only shopkeepers can view insights"}), 403
        if pid:
            from database import get_product
            p = get_product(int(pid), user_id)
            if not p:
                return jsonify({"error": "Forbidden: Product does not belong to you"}), 403
        analysis, pname = _load_shopkeeper_context(pid, sid)
    else:
        analysis = session.get("analysis", {})
        pname = session.get("raw_input", {}).get("product_name", "Product")

    if not analysis:
        return jsonify({"error": "No product analysis data available"}), 400

    prompt = (
        f"Explain '{topic}' for this product in simple, practical terms.\n"
        "Give a 2-3 sentence explanation, then bullet-point 2-3 specific actions "
        "the shopkeeper can take right now based on the data.\n"
        "Use **bold** for the most important number or action."
    )

    system = _shopkeeper_system_prompt(analysis, pname)
    try:
        text   = _call(system, [{"role": "user", "content": prompt}])
        return jsonify({"insight": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── ACTION PLAN ───────────────────────────────────────────────────────────────

@llm_bp.route("/action-plan", methods=["POST"])
def action_plan():
    if not _api_key():
        return jsonify({"error": "Groq API key not configured"}), 401

    body = request.get_json() or {}
    pid  = body.get("product_id")
    sid  = body.get("shop_id")

    user_id = session.get("user_id")
    if user_id:
        role = session.get("user_role")
        if role not in ("shopkeeper", "admin"):
            return jsonify({"error": "Forbidden: Only shopkeepers can view action plans"}), 403
        if pid:
            from database import get_product
            p = get_product(int(pid), user_id)
            if not p:
                return jsonify({"error": "Forbidden: Product does not belong to you"}), 403
        analysis, pname = _load_shopkeeper_context(pid, sid)
    else:
        analysis = session.get("analysis", {})
        pname = session.get("raw_input", {}).get("product_name", "Product")

    if not analysis:
        return jsonify({"error": "No product analysis data available"}), 400

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
    try:
        text   = _call(system, [{"role": "user", "content": prompt}], max_tokens=500)
        return jsonify({"plan": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── COMPARE SCENARIOS ─────────────────────────────────────────────────────────

@llm_bp.route("/compare", methods=["POST"])
def compare():
    if not _api_key():
        return jsonify({"error": "Groq API key not configured"}), 401

    body      = request.get_json() or {}
    scenarios = body.get("scenarios", [])
    pid       = body.get("product_id")
    sid       = body.get("shop_id")

    user_id = session.get("user_id")
    if user_id:
        role = session.get("user_role")
        if role not in ("shopkeeper", "admin"):
            return jsonify({"error": "Forbidden: Only shopkeepers can view comparisons"}), 403
        if pid:
            from database import get_product
            p = get_product(int(pid), user_id)
            if not p:
                return jsonify({"error": "Forbidden: Product does not belong to you"}), 403
        analysis, pname = _load_shopkeeper_context(pid, sid)
    else:
        analysis = session.get("analysis", {})
        pname = session.get("raw_input", {}).get("product_name", "Product")

    if not scenarios:
        return jsonify({"error": "No scenarios provided"}), 400

    if not analysis:
        return jsonify({"error": "No product analysis data available"}), 400

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
    try:
        text   = _call(system, [{"role": "user", "content": prompt}], max_tokens=400)
        return jsonify({"comparison": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── STATUS ────────────────────────────────────────────────────────────────────

@llm_bp.route("/status")
def status():
    key = _api_key()
    return jsonify({
        "configured": bool(key),
        "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "version": "v6-groq",
        "features": ["shopkeeper_chat", "customer_chat", "shop_isolation",
                     "sensitive_data_guard", "clean_formatting", "groq_integration"]
    })