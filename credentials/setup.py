from db import get_conn, release_conn
from search import client, INDEX_NAME

SAMPLE_PRODUCTS = [
    {"id": 1, "name": "Bluetooth Earphones Pro", "category": "Audio", "price": 1999, "inventory_count": 5, "city": "Bengaluru", "image_url": "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=500&q=80", "tags": "music, earbuds, wireless, pods, bass, calls, gym, audio"},
    {"id": 2, "name": "Nexus Smart Watch Ultra", "category": "Wearables", "price": 4500, "inventory_count": 2, "city": "Mumbai", "image_url": "https://images.unsplash.com/photo-1546868871-7041f2a55e12?w=500&q=80", "tags": "fitness, tracker, health, steps, heart rate, clock, sports, wrist"},
    {"id": 3, "name": "Wireless Ergonomic Mouse", "category": "Accessories", "price": 850, "inventory_count": 10, "city": "Bengaluru", "image_url": "https://images.unsplash.com/photo-1527864550417-7fd91fc51a46?w=500&q=80", "tags": "computer, pc, office, wfh, click, cursor, laptop accessory"},
    {"id": 4, "name": "Sennheiser Studio Headphones", "category": "Audio", "price": 14999, "inventory_count": 8, "city": "Delhi", "image_url": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500&q=80", "tags": "music, sound, anc, noise cancelling, studio, gaming, headset, over ear"},
    {"id": 5, "name": "Mechanical Gaming Keyboard", "category": "Accessories", "price": 3499, "inventory_count": 15, "city": "Pune", "image_url": "https://images.unsplash.com/photo-1595225476474-87563907a212?w=500&q=80", "tags": "typing, rgb, gamer, pc, esports, coding, switches, desk"},
    {"id": 6, "name": "4K Ultra HD Creator Monitor", "category": "Displays", "price": 28000, "inventory_count": 4, "city": "Hyderabad", "image_url": "https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?w=500&q=80", "tags": "screen, display, wfh, coding, editing, desktop, tv, crisp"},
    {"id": 7, "name": "Ergonomic Mesh Office Chair", "category": "Furniture", "price": 8500, "inventory_count": 12, "city": "Chennai", "image_url": "https://images.unsplash.com/photo-1505843490538-5133c6c7d0e1?w=500&q=80", "tags": "seat, back pain, lumbar, wfh, study, desk, swivel, comfort"},
    {"id": 8, "name": "100W GaN Type-C Fast Charger", "category": "Accessories", "price": 999, "inventory_count": 25, "city": "Bengaluru", "image_url": "https://images.unsplash.com/photo-1583863788434-e58a36330cf0?w=500&q=80", "tags": "power, adapter, cable, battery, usb, fast charging, travel"},
    {"id": 9, "name": "Pro Titanium 5G Smartphone", "category": "Smartphones", "price": 79999, "inventory_count": 6, "city": "Bengaluru", "image_url": "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=500&q=80", "tags": "mobile, phone, camera, iphone, android, calling, 5g, flagship"},
    {"id": 10, "name": "Ultrabook 14 OLED Laptop", "category": "Laptops", "price": 94999, "inventory_count": 4, "city": "Mumbai", "image_url": "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=500&q=80", "tags": "macbook, notebook, computer, coding, college, work, portable, pc"}
]

def initialize_system():
    print("Setting up PostgreSQL...")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DROP TABLE IF EXISTS orders;
                DROP TABLE IF EXISTS products;
                CREATE TABLE products (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255),
                    category VARCHAR(100),
                    price INT,
                    inventory_count INT,
                    city VARCHAR(100),
                    image_url VARCHAR(500)
                );
                CREATE TABLE orders (
                    id SERIAL PRIMARY KEY,
                    product_id INT REFERENCES products(id),
                    quantity INT,
                    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            for p in SAMPLE_PRODUCTS:
                cur.execute(
                    """INSERT INTO products (id, name, category, price, inventory_count, city, image_url)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (p["id"], p["name"], p["category"], p["price"], p["inventory_count"], p["city"], p["image_url"])
                )
        conn.commit()
    finally:
        release_conn(conn)

    print("Setting up OpenSearch with Related-Word Synonym Analyzer...")
    if client.indices.exists(index=INDEX_NAME):
        client.indices.delete(index=INDEX_NAME)

    client.indices.create(
        index=INDEX_NAME,
        body={
            "settings": {
                "analysis": {
                    "filter": {
                        "product_synonyms": {
                            "type": "synonym",
                            "synonyms": [
                                "earbuds, earphones, headphones, headset, pods, audio, music, sound",
                                "mobile, phone, smartphone, cellphone, iphone, android",
                                "laptop, notebook, ultrabook, macbook, computer, pc",
                                "monitor, screen, display, tv",
                                "chair, seat, stool, furniture, lumbar, ergonomic",
                                "charger, adapter, power, cable, usb, type-c",
                                "watch, smartwatch, wearable, fitness, tracker",
                                "keyboard, mouse, gaming, gamer, peripheral, accessories",
                                "wfh, office, desk, work, study, coding"
                            ]
                        }
                    },
                    "analyzer": {
                        "related_search_analyzer": {
                            "tokenizer": "standard",
                            "filter": ["lowercase", "product_synonyms"]
                        }
                    }
                }
            },
            "mappings": {
                "properties": {
                    "name": {"type": "text", "analyzer": "related_search_analyzer"},
                    "category": {"type": "text", "analyzer": "related_search_analyzer", "fields": {"keyword": {"type": "keyword"}}},
                    "tags": {"type": "text", "analyzer": "related_search_analyzer"},
                    "city": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "price": {"type": "integer"},
                    "inventory_count": {"type": "integer"}
                }
            }
        }
    )

    for p in SAMPLE_PRODUCTS:
        client.index(index=INDEX_NAME, id=str(p["id"]), body=p)
    client.indices.refresh(index=INDEX_NAME)

    print("Setup complete! Now run: python credentials/server.py")

if __name__ == "__main__":
    initialize_system()