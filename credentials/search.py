import os
from opensearchpy import OpenSearch
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

client = OpenSearch(
    hosts=[os.getenv("OPENSEARCH_URI")],
    verify_certs=False,
    ssl_show_warn=False
)
INDEX_NAME = "products"

def search_products(search_text=None, category=None, city=None, max_price=None):
    must_clauses = []
    filter_clauses = []

    if search_text and search_text.strip():
        q = search_text.strip()
        must_clauses.append({
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": q,
                            "fields": ["name^3", "tags^2", "category^2", "city"],
                            "fuzziness": "AUTO",
                            "operator": "or"
                        }
                    },
                    {
                        "multi_match": {
                            "query": q,
                            "type": "phrase_prefix",
                            "fields": ["name^2", "tags", "category"]
                        }
                    }
                ],
                "minimum_should_match": 1
            }
        })
    else:
        must_clauses.append({"match_all": {}})

    if category and category.lower() != "all":
        filter_clauses.append({"term": {"category.keyword": category}})
    if city and city.lower() != "all":
        filter_clauses.append({"term": {"city.keyword": city}})
    if max_price:
        try:
            parsed = int(max_price)
            if parsed > 0:
                filter_clauses.append({"range": {"price": {"lte": parsed}}})
        except ValueError:
            pass

    body = {
        "query": {
            "bool": {
                "must": must_clauses,
                "filter": filter_clauses
            }
        }
    }

    res = client.search(index=INDEX_NAME, body=body, size=50)
    return [{"id": int(h["_id"]), **h["_source"]} for h in res["hits"]["hits"]]

def update_search_stock(product_id, new_count):
    client.update(
        index=INDEX_NAME,
        id=str(product_id),
        body={"doc": {"inventory_count": new_count}},
        refresh="wait_for"
    )