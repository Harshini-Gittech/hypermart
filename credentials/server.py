import os
import threading
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO
from dotenv import load_dotenv, find_dotenv

from db import get_conn, release_conn
from search import search_products, update_search_stock
from kafka_client import create_producer, create_consumer

load_dotenv(find_dotenv())

# Points to ../public regardless of where you run the command from
PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))

app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

producer = create_producer()

@app.route("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")

@app.route("/api/search", methods=["GET"])
def api_search():
    try:
        q = request.args.get("q")
        category = request.args.get("category")
        city = request.args.get("city")
        max_price = request.args.get("maxPrice")
        results = search_products(q, category, city, max_price)
        return jsonify(results)
    except Exception as e:
        print("Search Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/api/orders", methods=["GET"])
def api_orders():
    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT o.id, o.quantity, o.order_date, p.name, p.price, p.city
                FROM orders o
                JOIN products p ON o.product_id = p.id
                ORDER BY o.order_date DESC
                LIMIT 25
            """)
            rows = cur.fetchall()
        orders = [
            {
                "id": r[0],
                "quantity": r[1],
                "order_date": r[2].isoformat() if r[2] else None,
                "name": r[3],
                "price": r[4],
                "city": r[5]
            }
            for r in rows
        ]
        return jsonify(orders)
    except Exception as e:
        print("Orders Error:", e)
        return jsonify({"error": str(e)}), 500
    finally:
        release_conn(conn)

@app.route("/api/checkout", methods=["POST"])
def api_checkout():
    data = request.get_json(silent=True) or {}
    cart = data.get("cart", [])

    if not cart:
        return jsonify({"success": False, "message": "Cart is empty"}), 400

    conn = None
    try:
        conn = get_conn()
        sorted_cart = sorted(cart, key=lambda x: int(x["id"]))
        kafka_events = []

        with conn.cursor() as cur:
            for item in sorted_cart:
                product_id = int(item["id"])
                quantity = int(item["quantity"])
                if quantity <= 0:
                    raise ValueError("Invalid quantity in cart.")

                cur.execute(
                    "SELECT inventory_count, price, name, city FROM products WHERE id = %s FOR UPDATE",
                    (product_id,)
                )
                row = cur.fetchone()
                if not row or row[0] < quantity:
                    name = row[2] if row else f"Item #{product_id}"
                    raise ValueError(f"Oops! {name} does not have enough stock left.")

                inv_count, price, name, city = row
                new_count = inv_count - quantity

                cur.execute("UPDATE products SET inventory_count = %s WHERE id = %s", (new_count, product_id))
                cur.execute("INSERT INTO orders (product_id, quantity) VALUES (%s, %s)", (product_id, quantity))

                kafka_events.append({
                    "productId": product_id,
                    "newCount": new_count,
                    "price": price * quantity,
                    "productName": name,
                    "city": city
                })

        conn.commit()

        for ev in kafka_events:
            producer.send("order_placed", value=ev)
        producer.flush()

        return jsonify({"success": True, "message": "Order placed successfully!"})
    except Exception as e:
        print("Checkout Error:", e)
        if conn:
            conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        release_conn(conn)

def start_kafka_consumer():
    try:
        consumer = create_consumer("order_placed")
        print("[Kafka] Consumer listening on 'order_placed'...")
        for msg in consumer:
            try:
                event = msg.value
                print(f"[Kafka Event] Product {event['productId']} | Stock: {event['newCount']} | Revenue: ₹{event['price']}")
                update_search_stock(event["productId"], event["newCount"])
                socketio.emit("stock_updated", event)
            except Exception as err:
                print("[Kafka Message Error]", err)
    except Exception as err:
        print("[Kafka Consumer Startup Error]", err)

if __name__ == "__main__":
    threading.Thread(target=start_kafka_consumer, daemon=True).start()
    port = int(os.getenv("PORT", 3000))
    print(f"Python server running on http://localhost:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)