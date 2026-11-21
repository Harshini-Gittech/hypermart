import os
import hmac
import hashlib
import uuid
import threading
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO
from dotenv import load_dotenv, find_dotenv
from groq import Groq

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

# Initialize Groq AI client for HyperBot & AI Wardrobe Stylist
groq_api_key = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=groq_api_key) if groq_api_key else None

# Razorpay credentials from .env
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "").strip()


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


@app.route("/api/create-order", methods=["POST"])
def create_razorpay_order():
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        return jsonify({"error": "Razorpay credentials are not configured in .env"}), 401

    data = request.get_json(silent=True) or {}
    try:
        amount_paise = int(round(float(data.get("amount", 0))))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400

    if amount_paise < 100:
        return jsonify({"error": "Amount must be at least 100 paise (₹1)"}), 400

    currency = str(data.get("currency") or "INR").upper()
    receipt = str(data.get("receipt") or f"hm_rcpt_{uuid.uuid4().hex[:12]}")

    try:
        resp = requests.post(
            "https://api.razorpay.com/v1/orders",
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            json={"amount": amount_paise, "currency": currency, "receipt": receipt},
            timeout=15,
        )
    except requests.RequestException as exc:
        return jsonify({"error": f"Failed to reach Razorpay API: {exc}"}), 500

    if resp.status_code == 401:
        return jsonify({"error": "Razorpay authentication failed"}), 401
    if not resp.ok:
        return jsonify({"error": "Razorpay order creation failed", "details": resp.text}), 500

    order_data = resp.json()
    return jsonify({
        "order_id": order_data["id"],
        "amount": order_data["amount"],
        "currency": order_data["currency"],
        "key_id": RAZORPAY_KEY_ID,
    }), 200


@app.route("/api/verify-payment", methods=["POST"])
def verify_razorpay_payment():
    if not RAZORPAY_KEY_SECRET:
        return jsonify({"error": "Razorpay secret is not configured"}), 401

    data = request.get_json(silent=True) or {}
    razorpay_order_id = str(data.get("razorpay_order_id") or "").strip()
    razorpay_payment_id = str(data.get("razorpay_payment_id") or "").strip()
    razorpay_signature = str(data.get("razorpay_signature") or "").strip()

    if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        return jsonify({"success": False, "error": "Missing payment verification fields"}), 400

    payload = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
    expected_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, razorpay_signature):
        return jsonify({"success": False, "error": "Invalid payment signature"}), 400

    return jsonify({
        "success": True,
        "order_id": razorpay_order_id,
        "payment_id": razorpay_payment_id,
    }), 200


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


@app.route("/api/wardrobe/tryon", methods=["POST"])
def api_wardrobe_tryon():
    data = request.get_json(silent=True) or {}
    gender = str(data.get("gender") or "Men")
    height_cm = float(data.get("height_cm") or 170)
    weight_kg = float(data.get("weight_kg") or 68)
    skin_tone = str(data.get("skin_tone_name") or "Warm Medium")
    items = data.get("items") or {}

    h_m = max(1.0, height_cm / 100.0)
    bmi = round(weight_kg / (h_m * h_m), 1)

    if gender == "Kids":
        size = "Kids S" if height_cm < 130 else "Kids M" if height_cm < 145 else "Kids L"
    else:
        if weight_kg < 55:
            size = "S"
        elif weight_kg < 70:
            size = "M"
        elif weight_kg < 85:
            size = "L"
        else:
            size = "XL"

    fit_label = "Slim Fit" if bmi < 20 else "Regular Fit" if bmi < 26 else "Relaxed Fit"
    equipped_list = [f"{slot.title()}: {item.get('name')}" for slot, item in items.items() if item]
    outfit_summary = ", ".join(equipped_list) if equipped_list else "No items equipped yet"

    ai_advice = f"Recommended Size: {size} ({fit_label}). This combination pairs well with a {skin_tone} skin tone."
    if groq_client and equipped_list:
        try:
            prompt = (
                f"You are HyperMart's AI Fashion Stylist. A {gender} shopper is {int(height_cm)} cm tall, "
                f"weighs {int(weight_kg)} kg (BMI {bmi}, suggested size {size}), with a {skin_tone} skin tone. "
                f"They are trying on: {outfit_summary}. "
                "Give a 2-sentence styling and fit review mentioning color harmony with their skin tone and one quick tip."
            )
            completion = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
            )
            ai_advice = completion.choices[0].message.content
        except Exception as err:
            print("Wardrobe Groq Error:", err)

    return jsonify({
        "success": True,
        "recommended_size": size,
        "fit_label": fit_label,
        "bmi": bmi,
        "advice": ai_advice
    })


@app.route("/api/hyperbot", methods=["POST"])
def api_hyperbot():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    city = (data.get("city") or "").strip()
    history = data.get("history", [])

    if not query:
        return jsonify({"reply": "Please type a question so I can help!", "recommendations": []}), 400

    try:
        recent_history = [
            {"role": m["role"], "content": str(m["content"])[:500]}
            for m in history[-6:]
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
        ]

        city_filter = city if city and city.lower() != "all" else None
        products = search_products(search_text=query, city=city_filter)

        follow_up_words = (
            "city", "where", "ship", "price", "cost", "cheap", "stock",
            "available", "it", "those", "them", "which one", "other"
        )
        is_followup = any(w in query.lower() for w in follow_up_words)

        if (not products or is_followup) and recent_history:
            prev_user_msgs = [m["content"] for m in recent_history if m["role"] == "user"]
            for prev_q in reversed(prev_user_msgs):
                prev_hits = search_products(search_text=prev_q, city=city_filter)
                if prev_hits:
                    products = prev_hits
                    break

        exact_match = len(products) > 0
        if not products:
            products = search_products()

        top_products = products[:4]

        if top_products:
            context_lines = [
                f"- {p.get('name')} | Price: ₹{p.get('price')} | Stock: {p.get('inventory_count', 0)} units | City/Warehouse: {p.get('city', 'Bengaluru')} | Category: {p.get('category', 'General')}"
                for p in top_products
            ]
            context_str = "\n".join(context_lines)
        else:
            context_str = "No products currently available."

        ai_reply = None
        if groq_client:
            system_prompt = (
                "You are HyperBot, an interactive AI Shopping Guide for HyperMart-Live. "
                "Use the conversation history and the live store inventory below to answer directly and specifically. "
                "If the user asks which city or warehouse an item is in, state the exact City/Warehouse from the inventory. "
                "If the user asks which is cheaper, compare the exact ₹ prices. "
                "Keep your reply helpful, accurate, and under 3 sentences.\n\n"
                f"Live Store Inventory:\n{context_str}"
            )

            messages_payload = [
                {"role": "system", "content": system_prompt},
                *recent_history,
                {"role": "user", "content": query}
            ]

            for model_name in ["llama-3.1-8b-instant", "meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.3-70b-versatile"]:
                try:
                    completion = groq_client.chat.completions.create(
                        model=model_name,
                        messages=messages_payload,
                        temperature=0.2,
                    )
                    ai_reply = completion.choices[0].message.content
                    break
                except Exception as model_err:
                    print(f"Model {model_name} failed:", model_err)

        if not ai_reply:
            if "city" in query.lower() or "where" in query.lower():
                city_info = ", ".join(f"{p.get('name')} ({p.get('city', 'Bengaluru')})" for p in top_products[:2])
                ai_reply = f"Here are the cities for those items: {city_info}."
            elif "cheap" in query.lower() or "price" in query.lower():
                cheapest = min(top_products, key=lambda x: float(x.get("price") or 0))
                ai_reply = f"{cheapest.get('name')} is the lowest priced at ₹{cheapest.get('price')}."
            elif top_products and exact_match:
                names = ", ".join(p.get("name") for p in top_products[:2])
                ai_reply = f"Yes! We have {names} available on HyperMart right now. Click any product below to jump straight to it!"
            elif top_products:
                ai_reply = "I couldn't find an exact match for your query, but here are items available on our website. Click any to view!"
            else:
                ai_reply = "No matching items are in stock right now."

        return jsonify({
            "reply": ai_reply,
            "recommendations": top_products
        })
    except Exception as e:
        print("HyperBot Error:", e)
        return jsonify({"reply": "Sorry, HyperBot hit a snag. Please make sure the server is running and try again.", "recommendations": []}), 500


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