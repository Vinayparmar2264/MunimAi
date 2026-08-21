# 🏪 MunimAI — Smart Retail AI Advisor & Demand Forecaster

**MunimAI** is a premium, full-stack SaaS platform designed to empower local shopkeepers and customers through machine learning-driven forecasting, interactive AI advice, and geolocation-based shopping. 

Built using a modern glassmorphism design, it integrates custom Scikit-Learn predictive models with the Groq API (utilizing high-performance reasoning models) to automate inventory health, demand velocity, pricing markdowns, and customer satisfaction analysis.

---

## 🌟 Core Features

### 1. 🏪 Shopkeeper Capabilities
*   **Multi-Shop Management**: Manage multiple physical store outlets from a single shopkeeper account.
*   **AI-Powered Demand Forecasting**: Uses custom ML regression models to predict sales velocity, 7-day, and 30-day demand.
*   **Smart Restock & EOQ Alerts**: Recommends replenishment timelines and computes the **Economic Order Quantity (EOQ)** to minimize ordering and carrying costs.
*   **AI Narrative Summaries**: Explains complex sales forecasts and metrics in plain, simple language using Groq's reasoning engine.
*   **Context-Aware AI Assistant**: A dedicated chat drawer that knows your inventory stats, product velocity, and health scores to answer decision-making queries.

### 2. 🛍️ Customer Capabilities
*   **Nearby Shops Map**: Integrated interactive Leaflet maps showing nearby participating stores with dynamic routing.
*   **Live Storefront Catalogs**: Browse shop-specific inventory, check stock visibility, and view active AI-recommended discounts.
*   **Direct Store Chat**: Ask questions directly to shop assistants to enquire about active pricing and item details.

### 3. 🛡️ Security & Enterprise Design
*   **Strict Shop Isolation**: Shopkeepers can only access and query analyses for products they own. Unauthorized attempts are blocked by active security checks.
*   **Sensitive Data Guardrails**: Prevents customer-facing chats from leaking internal business metrics (e.g., cost price, profit margins, exact stock volumes).
*   **SSE Stream Parser**: Provides instantaneous, smooth word-by-word streaming responses in the chat bubble.

---

## 🛠️ Technology Stack

*   **Backend**: Flask (Python 3.12)
*   **Database**: PostgreSQL / Supabase
*   **Machine Learning**: Scikit-Learn (Gradient Boosting Regressors)
*   **AI Integration**: Groq API (`openai/gpt-oss-120b`)
*   **Frontend**: Vanilla HTML5, CSS3 (Glassmorphism layout, responsive navigation grids), Leaflet.js

---

## 🚀 Quick Start Guide

### 1. Clone the Repository
```bash
git clone https://github.com/Vinayparmar2264/MunimAi.git
cd MunimAi
```

### 2. Set Up Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create a `.env` file in the root directory:
```env
GROQ_API_KEY=gsk_your_key_here
DATABASE_URL=postgresql://your_postgres_credentials
SECRET_KEY=your_flask_secret_key
```

### 4. Train the Forecasting Models
Generate the predictive model binaries (`models/*.pkl`) using the training script:
```bash
python train.py
```

### 5. Launch the Server
```bash
python app.py
```
Open your browser and navigate to `http://localhost:5000`.

---

## 📁 Code Architecture

*   `app.py`: Core Flask app setup, forecasting logic, and general user routes.
*   `llm.py`: Backend integration for Groq API, system prompts, sensitive data guardrails, and streaming chat endpoints.
*   `database.py`: PostgreSQL/Supabase database client, cursor utilities, and query models.
*   `train.py`: Training script that uses historical retail datasets to export Scikit-Learn forecasting models.
*   `shopkeeper.py` / `shop.py` / `customer.py`: Sub-blueprints modularizing features by user roles.
*   `static/`: Assets, custom CSS design tokens, and frontend scripts.
*   `templates/`: Responsive template layout files (base, auth, customer, shopkeeper).

---

