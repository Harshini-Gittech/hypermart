# HyperMart — Interactive 3D & AR Real-Time Marketplace

HyperMart is a full-stack, event-driven e-commerce platform combining an interactive **3D & WebXR/AR product studio**, a **voice-enabled multi-turn RAG AI shopping assistant (HyperBot)**, **seller workflows and payment routes**, a **dynamic personalization dashboard**, and **real-time inventory synchronization** across PostgreSQL, OpenSearch, and Apache Kafka[cite: 18, 19, 22].

---

## System Architecture

```text
+---------------------------------------------------------------------------------------------------+
|                                   CLIENT BROWSER (public/index.html)                              |
|                                                                                                   |
|  +---------------------------+  +----------------------------+  +------------------------------+  |
|  |   Three.js & <model-      |  |    HyperBot Voice + RAG    |  |   Auto-Recommendation        |  |
|  |   viewer> 3D / AR Studio  |  |    AI Shopping Assistant   |  |   Dashboard, Seller Views &  |  |
|  |  - 360° PBR / Exploded    |  |  - Web Speech API (en-IN)  |  |   2-Step Checkout / Payments |  |
|  |  - CAD Wireframe & .GLB   |  |  - Multi-turn chatHistory  |  |  - Socket.IO Live Stock Sync |  |
|  +-------------+-------------+  +-------------+--------------+  +--------------+---------------+  |
+----------------|------------------------------|--------------------------------|------------------+
                 | Static / 3D / Media Assets   | POST /api/hyperbot             | GET /api/search
                 | (models/, uploads/, intro.mp4)| (Query + History)              | Seller / Payment / Checkout
                 v                              v                                v
+---------------------------------------------------------------------------------------------------+
|                             FLASK + SOCKET.IO BACKEND (credentials/server.py)                     |
|                                                                                                   |
|  +---------------------------+  +----------------------------+  +------------------------------+  |
|  |   Search & Discovery API  |  |   HyperBot RAG Engine      |  |   Payments, Seller Routes &  |  |
|  |  - Related-Word & Fuzzy   |  |  - 1. Retrieve (OpenSearch)|  |   Transactional Checkout API |  |
|  |    Query Matching         |  |  - 2. Augment (Live Stock) |  |  - Row-Level Locking         |  |
|  |  - Category & City Filter |  |  - 3. Generate (Groq LLM)  |  |    (SELECT ... FOR UPDATE)   |  |
|  +-------------+-------------+  +-------------+--------------+  +------+---------------+-------+  |
+----------------|------------------------------|------------------------|---------------|----------+
                 |                              |                        |               |
                 v                              |                        |               v
+---------------------------------+             |                        |  +-----------------------+
|         AIVEN OPENSEARCH        |<------------+                        |  |   AIVEN POSTGRESQL    |
|  (credentials/search.py)        |                                      |  |  (credentials/db.py)  |
|  - Product Catalog & Tag Index  |             +------------------------+  |  - products           |
|  - Real-Time Stock Updates      |             | Produce: 'order_placed'   |  - orders             |
+----------------+----------------+             v                           +-----------------------+
                 ^                +---------------------------------+
                 |                |       AIVEN APACHE KAFKA        |
                 |                |  (credentials/kafka_client.py)  |
                 |                +----------------+----------------+
                 |                                 |
                 |  Update Index                   | Consume: 'order_placed'
                 +------ [ Background Kafka Consumer Thread ] ------+
                                 |
                                 +---> Socket.IO Broadcast ('stock_updated') ---> Connected Clients
```

### Event-Driven Data Flow
1. **Search & Discovery:** Queries hit `/api/search`, querying **Aiven OpenSearch** for fuzzy and related-word matches across product names, tags, categories, and warehouse cities.
2. **HyperBot Voice & Multi-Turn RAG:** User voice or text queries (along with recent `chatHistory`) are sent to `/api/hyperbot`. The backend retrieves matching live products from OpenSearch, augments a system prompt with real-time prices, stock counts, and warehouse locations, and generates a grounded response via **Groq LLM** (`llama-3.1-8b-instant` with automatic model fallback).
3. **Payments, Seller Actions & Atomic Checkout:** Checkout, payment flows (`payments_routes.py`), and seller actions (`seller_routes.py`) coordinate with **PostgreSQL** using row-level locking (`FOR UPDATE`) to decrement inventory safely, record orders, and publish `order_placed` events to **Apache Kafka**[cite: 22].
4. **Live Storefront Sync:** A background Kafka consumer thread updates the OpenSearch stock document and emits a `stock_updated` WebSocket event via **Flask-SocketIO**, updating inventory badges across all active browsers in real time[cite: 18].

---

## Key Features

* **Interactive 3D & AR Product Studio:** Inspect products in 360° with real-time PBR material swatches, **Exploded View**, **CAD Wireframe** mode, **AR Desk View** (`<model-viewer>` WebXR / Scene Viewer / Quick Look), and `.GLB` / `.GLTF` models[cite: 22].
* **HyperBot AI Voice + RAG Assistant:** Supports hands-free `en-IN` speech-to-text input, text-to-speech voice replies, 6-turn conversational memory for follow-up questions, and clickable product jump-cards.
* **Seller & Payment Workflows:** Dedicated backend route modules (`payments_routes.py` and `seller_routes.py`), seller view assets (`public/uploads/seller_views/`), and client feature scripts (`public/app-features.js`)[cite: 22].
* **Auto-Recommended Product Dashboard:** Dynamically ranks and spotlights products based on live stock alerts, wishlist items, and user 3D inspection signals[cite: 19].
* **Real-Time Multi-User Inventory Sync:** Prevents overselling using PostgreSQL row-level locking and broadcasts live stock decrements via Kafka + Socket.IO[cite: 18].
* **2-Step Checkout & Order Tracking:** Includes delivery address validation, UPI QR generation, Card/COD payment simulation, promo codes (`HYPER10`), and live order tracking.

---

## Repository Structure

```text
mart test/
├── .vscode/                      # Editor / IDE workspace settings
├── credentials/                  # Backend application, routes, database & streaming connectors
│   ├── __pycache__/              # Compiled Python bytecode cache
│   ├── db.py                     # PostgreSQL connection pool management (get_conn / release_conn)
│   ├── kafka_client.py           # Kafka producer and consumer factory utilities
│   ├── payments_routes.py        # Payment processing endpoints and transaction helpers
│   ├── requirements.txt          # Python dependencies (Flask, SocketIO, Groq, OpenSearch, Kafka, Psycopg2)
│   ├── search.py                 # Aiven OpenSearch client, indexing, search & stock update helpers
│   ├── seller_routes.py          # Seller management and listing routes
│   ├── server.py                 # Main Flask + Socket.IO server, REST APIs & HyperBot RAG pipeline
│   └── setup.py                  # Database & OpenSearch schema/seed initialization script
├── public/                       # Frontend SPA, scripts, 3D assets & uploads
│   ├── models/                   # Local 3D product models (e.g., headphones.glb, calculator.glb)
│   ├── uploads/                  # Uploaded media & generated assets
│   │   ├── ai_products/          # AI-generated product images
│   │   ├── models/               # Uploaded 3D model files
│   │   └── seller_views/         # Seller-specific visual assets
│   ├── app-features.js           # Modular frontend feature logic
│   ├── index.html                # Main UI, Tailwind styling, 3D viewer & HyperBot widget
│   └── intro.mp4                 # Storefront / showcase intro video
├── .env                          # Environment secrets (ignored by Git — see setup below)
├── .gitignore                    # Excludes .env, __pycache__, virtual environments & SSL certs
└── README.md                     # Project architecture & documentation
```
*(Note: If you place this folder inside your `hypermart` Git repository, rename or map the root folder path accordingly while keeping the `credentials/` and `public/` structure intact.)*

---

## Tech Stack

| Layer | Technologies |
| :--- | :--- |
| **Frontend** | HTML5, Tailwind CSS, Vanilla JavaScript (`app-features.js`, `index.html`), Three.js, Google `<model-viewer>`, Socket.IO Client, Web Speech API |
| **Backend** | Python 3, Flask, Flask-CORS, Flask-SocketIO, Modular Route Blueprints (`payments_routes.py`, `seller_routes.py`) |
| **AI & RAG** | Groq SDK (`llama-3.1-8b-instant`, `llama-4-scout-17b`, `llama-3.3-70b-versatile`) + OpenSearch Retrieval |
| **Data & Streaming** | Aiven PostgreSQL (`psycopg2`), Aiven OpenSearch (`opensearch-py`), Aiven Apache Kafka (`kafka-python-ng`) |

---

## Getting Started (Local Setup)

### 1. Prerequisites
* Python 3.10+
* Google Chrome (recommended for Web Speech API voice input/output)
* Access credentials for **PostgreSQL**, **OpenSearch**, **Apache Kafka**, and a **Groq API Key**

### 2. Install Python Dependencies
```bash
py -m pip install -r credentials/requirements.txt
```

### 3. Configure Environment Variables
Create a `.env` file in the project root with your service credentials:

```env
PORT=3000

# Groq LLM API Key (for HyperBot)
GROQ_API_KEY=your_groq_api_key

# PostgreSQL Configuration
PG_HOST=your_postgres_host
PG_PORT=your_postgres_port
PG_DATABASE=defaultdb
PG_USER=avnadmin
PG_PASSWORD=your_postgres_password

# OpenSearch Configuration
OPENSEARCH_URI=https://user:password@your-opensearch-host:port

# Apache Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS=your-kafka-host:port
```

*(Note: Never commit `.env` or SSL certificate files to Git.)*

### 4. Initialize Database & Search Index (First-Time Setup)
```bash
py credentials/setup.py
```

### 5. Run the Server
```bash
py credentials/server.py
```
Open **`http://localhost:3000`** in your browser[cite: 18].

---

## API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the single-page storefront (`public/index.html`) |
| `GET` | `/api/search` | Searches OpenSearch (`?q=&category=&city=&maxPrice=`) |
| `GET` | `/api/orders` | Fetches recent orders joined with product metadata |
| `POST` | `/api/checkout` | Validates stock with row locking, creates orders, and emits Kafka `order_placed` events |
| `POST` | `/api/hyperbot` | Multi-turn RAG endpoint (`{ query, city, history }`) returning grounded AI replies & product cards |
| `POST` / `GET` | Payment & Seller Routes | Endpoints registered in `payments_routes.py` and `seller_routes.py` |
