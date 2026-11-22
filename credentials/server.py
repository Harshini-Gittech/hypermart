import os
import threading
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO
from dotenv import load_dotenv, find_dotenv

from db import get_conn, release_conn
from search import search_products, update_search_stock
from kafka_client import create_producer, create_consumer
from seller_routes import seller_bp, init_seller_tables

try:
    import razorpay
except ImportError:
    razorpay = None

app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
CORS(app)
app.register_blueprint(seller_bp)

try:
    from payments_routes import payments_bp
    app.register_blueprint(payments_bp)
    print("[Razorpay] Registered payments_routes blueprint.")
except Exception as pe:
    print(f"[Razorpay] Blueprint import note: {pe}")

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
app.config["SOCKETIO"] = socketio

KAFKA_TOPIC = "order_placed"
producer = create_producer()

@app.route("/")
def serve_index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/api/search", methods=["GET"])
def api_search():
    q = (request.args.get("q") or "").strip()
    try:
        rows = search_products(q)
        return jsonify(rows)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500



@app.route("/api/orders", methods=["GET"])
def api_orders():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT o.id, o.product_id, p.name, p.price, p.city, o.quantity, o.order_date
                FROM orders o
                JOIN products p ON p.id = o.product_id
                ORDER BY o.order_date DESC, o.id DESC
                LIMIT 50;
            """)
            orders = [{
                "id": r[0],
                "product_id": r[1],
                "name": r[2],
                "price": float(r[3]),
                "city": r[4] or "Bengaluru",
                "quantity": int(r[5]),
                "order_date": r[6].isoformat() if r[6] else ""
            } for r in cur.fetchall()]
            return jsonify(orders)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        release_conn(conn)

@app.route("/api/checkout", methods=["POST"])
def api_checkout():
    data = request.get_json(force=True)
    cart = data.get("cart") or []
    if not cart:
        return jsonify({"success": False, "message": "Cart is empty"}), 400

    conn = get_conn()
    created_orders = []
    try:
        with conn.cursor() as cur:
            for item in cart:
                prod_id = int(item.get("id") or 0)
                qty = max(1, int(item.get("quantity") or 1))
                if prod_id <= 0:
                    continue

                cur.execute(
                    "SELECT inventory_count FROM products WHERE id = %s;",
                    (prod_id,)
                )
                prow = cur.fetchone()
                if not prow:
                    conn.rollback()
                    return jsonify({"success": False, "message": f"Product #{prod_id} not found"}), 404
                if int(prow[0]) < qty:
                    conn.rollback()
                    return jsonify({"success": False, "message": f"Insufficient stock for product #{prod_id}"}), 409

                cur.execute("""
                    INSERT INTO orders (product_id, quantity)
                    VALUES (%s, %s)
                    RETURNING id;
                """, (prod_id, qty))
                order_id = cur.fetchone()[0]
                created_orders.append({"order_id": order_id, "product_id": prod_id, "quantity": qty})

            conn.commit()

        for co in created_orders:
            publish_order_event(co["order_id"], co["product_id"], co["quantity"])

        first_id = created_orders[0]["order_id"] if created_orders else None
        return jsonify({
            "success": True,
            "order_id": first_id,
            "orders": created_orders
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        release_conn(conn)


@app.route("/api/payments/create-order", methods=["POST"])
def server_create_razorpay_order():
    try:
        data = request.get_json(silent=True) or {}
        product_id = int(data.get("product_id") or 0)
        quantity = max(1, int(data.get("quantity") or 1))
        include_gst = bool(data.get("include_gst", True))

        if product_id <= 0:
            return jsonify({"success": False, "message": "Invalid product_id"}), 400

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name, price, inventory_count FROM products WHERE id = %s;",
                    (product_id,)
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "message": "Product not found"}), 404
            name, unit_price, stock = row[0], float(row[1]), int(row[2])
            if stock < quantity:
                return jsonify({"success": False, "message": "Insufficient stock"}), 400
        finally:
            release_conn(conn)

        subtotal = unit_price * quantity
        total_inr = subtotal * 1.18 if include_gst else subtotal
        amount_paise = int(round(total_inr * 100))

        if amount_paise < 100:
            return jsonify({"success": False, "message": "Minimum order amount is ₹1.00"}), 400

        client, key_id = _get_razorpay_client()
        order = client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"hm_p{product_id}_q{quantity}",
            "notes": {
                "product_id": str(product_id),
                "quantity": str(quantity),
                "include_gst": str(include_gst).lower()
            }
        })

        return jsonify({
            "success": True,
            "key_id": key_id,
            "order_id": order["id"],
            "amount": amount_paise,
            "currency": "INR",
            "product_name": name
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/payments/verify", methods=["POST"])
def server_verify_razorpay_payment():
    try:
        data = request.get_json(silent=True) or {}
        razorpay_order_id = (data.get("razorpay_order_id") or "").strip()
        razorpay_payment_id = (data.get("razorpay_payment_id") or "").strip()
        razorpay_signature = (data.get("razorpay_signature") or "").strip()
        product_id = int(data.get("product_id") or 0)
        quantity = max(1, int(data.get("quantity") or 1))

        if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature or product_id <= 0:
            return jsonify({"success": False, "message": "Missing payment verification details"}), 400

        client, _ = _get_razorpay_client()
        try:
            client.utility.verify_payment_signature({
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature
            })
        except Exception:
            return jsonify({"success": False, "message": "Razorpay signature verification failed"}), 400

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE products
                    SET inventory_count = inventory_count - %s
                    WHERE id = %s AND inventory_count >= %s
                    RETURNING id;
                """, (quantity, product_id, quantity))
                if not cur.fetchone():
                    conn.rollback()
                    return jsonify({"success": False, "message": "Product out of stock"}), 409

                cur.execute("""
                    INSERT INTO orders (product_id, quantity)
                    VALUES (%s, %s)
                    RETURNING id;
                """, (product_id, quantity))
                db_order_id = cur.fetchone()[0]
                conn.commit()

            publish_order_event(db_order_id, product_id, quantity)

            return jsonify({
                "success": True,
                "order_id": db_order_id,
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id
            })
        except Exception as e:
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
    ensure_tables()
    try:
        init_seller_tables()
    except Exception as e:
        print(f"[Seller Tables Warning] {e}")

    t = threading.Thread(target=kafka_consumer_loop, daemon=True)
    t.start()

    port = int(os.getenv("PORT", "5050"))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)