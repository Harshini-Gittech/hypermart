import os
import hmac
import hashlib
import razorpay
from flask import Blueprint, request, jsonify

payments_bp = Blueprint("payments_bp", __name__)


def _acquire_db_conn():
    try:
        from db import db_pool  # type: ignore
        return ("pool", db_pool, db_pool.getconn())
    except ImportError:
        from db import get_conn, release_conn  # type: ignore
        return ("fn", release_conn, get_conn())


def _release_db_conn(mode, release_handle, conn):
    if conn is None:
        return
    if mode == "pool":
        release_handle.putconn(conn)
    else:
        release_handle(conn)


def _get_razorpay_client():
    key_id = (os.getenv("RAZORPAY_KEY_ID") or "").strip()
    key_secret = (os.getenv("RAZORPAY_KEY_SECRET") or "").strip()
    if not key_id or not key_secret:
        raise RuntimeError("RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET is missing in .env")
    return razorpay.Client(auth=(key_id, key_secret)), key_id


@payments_bp.errorhandler(404)
@payments_bp.errorhandler(500)
def handle_payment_errors(err):
    code = getattr(err, "code", 500)
    msg = getattr(err, "description", None) or str(err)
    return jsonify({"success": False, "message": msg}), code


@payments_bp.route("/api/payments/create-order", methods=["POST"])
def create_razorpay_order():
    try:
        data = request.get_json(silent=True) or {}
        product_id = int(data.get("product_id") or 0)
        quantity = max(1, int(data.get("quantity") or 1))
        include_gst = bool(data.get("include_gst", True))

        if product_id <= 0:
            return jsonify({"success": False, "message": "Invalid product_id"}), 400

        mode, release_handle, conn = _acquire_db_conn()
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
            _release_db_conn(mode, release_handle, conn)

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
        return jsonify({"success": False, "message": f"Order creation failed: {e}"}), 500


@payments_bp.route("/api/payments/verify", methods=["POST"])
def verify_razorpay_payment():
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

        mode, release_handle, conn = _acquire_db_conn()
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

            return jsonify({
                "success": True,
                "order_id": db_order_id,
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id
            })
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "message": str(e)}), 500
        finally:
            _release_db_conn(mode, release_handle, conn)
    except Exception as e:
        return jsonify({"success": False, "message": f"Verification error: {e}"}), 500


@payments_bp.route("/api/payments/webhook", methods=["POST"])
def razorpay_webhook():
    webhook_secret = (os.getenv("RAZORPAY_WEBHOOK_SECRET") or "").strip()
    received_sig = (request.headers.get("X-Razorpay-Signature") or "").strip()
    raw_body = request.get_data()

    if not webhook_secret or not received_sig:
        return jsonify({"success": False}), 400

    expected_sig = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, received_sig):
        return jsonify({"success": False, "message": "Invalid webhook signature"}), 400

    return jsonify({"success": True}), 200