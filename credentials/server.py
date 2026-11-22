import os
import threading
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

ALLOWED_ORIGINS = [
    "https://hypermart-one.vercel.app",
    "http://127.0.0.1:5050",
    "http://localhost:5050",
]

app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me-in-production")

CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})
socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, async_mode="threading")

# Import and register your existing modules/blueprints from credentials/ here, e.g.:
# from db import ensure_tables
# from seller_routes import init_seller_tables, seller_bp
# from payments_routes import payments_bp
# app.register_blueprint(payments_bp)
# app.register_blueprint(seller_bp)


@app.route("/health", methods=["GET"])
def health_check():
  return jsonify({"status": "ok"}), 200


@app.route("/", methods=["GET"])
def serve_index():
  index_path = os.path.join(PUBLIC_DIR, "index.html")
  if os.path.exists(index_path):
    return send_from_directory(PUBLIC_DIR, "index.html")
  return jsonify({"service": "HyperMart API"}), 200


def start_kafka_consumer():
  try:
    # Connect your existing Kafka consumer loop from kafka_client.py here
    pass
  except Exception as e:
    print(f"[Kafka Consumer Startup Error] {e}")


if __name__ == "__main__":
  try:
    from db import ensure_tables

    ensure_tables()
  except Exception as e:
    print(f"[DB Init Warning] {e}")

  try:
    from seller_routes import init_seller_tables

    init_seller_tables()
  except Exception as e:
    print(f"[Seller Tables Warning] {e}")

  t = threading.Thread(target=start_kafka_consumer, daemon=True)
  t.start()

  port = int(os.getenv("PORT", "5050"))
  socketio.run(app, host="0.0.0.0", port=port, debug=False)