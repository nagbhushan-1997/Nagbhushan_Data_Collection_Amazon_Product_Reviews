"""
Stage 3: build the file the annotation app reads.

Joins the image-bearing reviews from stage 1-2 against raw_meta_Electronics
on parent_asin, keeps products with enough image reviews to be worth judging,
and writes one product per line.

Run this once. The app then loads products.jsonl and never touches the raw data.
"""

import json
import gzip
from pathlib import Path
from collections import defaultdict

# ----------------------------- config -----------------------------
IMAGE_REVIEWS = Path(r"E:\\work_dsi\\Nagbhushan_Data_Creation_Amazon\\datasets\\amazon2023\\out\\electronics_image_reviews.jsonl")

OUT_FILE = Path(r"E:\\work_dsi\\Nagbhushan_Data_Creation_Amazon\\datasets\\amazon2023\\out\\products.jsonl")

META_MODE = "local"                  # "stream" or "local"
LOCAL_META_FILE = Path(
    r"C:\Users\NSH43\.cache\huggingface\hub\datasets--McAuley-Lab--Amazon-Reviews-2023"
    r"\snapshots\2b6d039ed471f2ba5fd2acb718bf33b0a7e5598e\raw\meta_categories\meta_Electronics.jsonl"
)

MIN_IMAGE_REVIEWS = 5                # products below this are not summarizable
MAX_REVIEWS_PER_PRODUCT = 30         # cap so the app stays responsive
MAX_PRODUCTS = 20000                 # keep the annotation set finite
# ------------------------------------------------------------------


def iter_meta():
    if META_MODE == "stream":
        from datasets import load_dataset
        ds = load_dataset(
            "McAuley-Lab/Amazon-Reviews-2023",
            "raw_meta_Electronics",
            split="full",
            streaming=True,
        )
        for rec in ds:
            yield rec
    else:
        opener = gzip.open if LOCAL_META_FILE.suffix == ".gz" else open
        with opener(LOCAL_META_FILE, "rt", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if line:
                    yield json.loads(line)


def catalog_images(raw, limit=3):
    """Pull seller/catalog image URLs out of the metadata images struct."""
    if not isinstance(raw, dict):
        return []
    for key in ("hi_res", "large", "thumb"):
        vals = raw.get(key) or []
        urls = [u for u in vals if u and u != "None"]
        if urls:
            return urls[:limit]
    return []


def main():
    print("Loading image reviews...")
    by_product = defaultdict(list)
    with IMAGE_REVIEWS.open("r", encoding="utf-8") as fp:
        for line in fp:
            r = json.loads(line)
            pa = r.get("parent_asin")
            if pa:
                by_product[pa].append(r)

    # Sort each product's reviews: most images first, then most helpful.
    # Reviews with several photos give annotators more to work with.
    eligible = {}
    for pa, revs in by_product.items():
        if len(revs) < MIN_IMAGE_REVIEWS:
            continue
        revs.sort(key=lambda r: (r.get("n_images", 0), r.get("helpful_vote") or 0),
                  reverse=True)
        eligible[pa] = revs[:MAX_REVIEWS_PER_PRODUCT]

    print(f"{len(by_product):,} products seen, {len(eligible):,} with >= {MIN_IMAGE_REVIEWS} image reviews")

    print("Scanning metadata for those products...")
    written = 0
    wanted = set(eligible)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w", encoding="utf-8") as out:
        for i, m in enumerate(iter_meta(), 1):
            if i % 200_000 == 0:
                print(f"  scanned {i:,} meta records, matched {written:,}", flush=True)

            pa = m.get("parent_asin")
            if pa not in wanted:
                continue

            desc = m.get("description") or []
            feats = m.get("features") or []

            product = {
                "parent_asin": pa,
                "title": m.get("title") or "(untitled)",
                "store": m.get("store"),
                "price": m.get("price"),
                "average_rating": m.get("average_rating"),
                "rating_number": m.get("rating_number"),
                "main_category": m.get("main_category"),
                "categories": m.get("categories") or [],
                "features": feats[:8],
                "description": " ".join(desc)[:1200] if desc else "",
                "catalog_images": catalog_images(m.get("images")),
                "reviews": eligible[pa],
            }
            out.write(json.dumps(product, ensure_ascii=False) + "\n")
            written += 1
            wanted.discard(pa)

            if written >= MAX_PRODUCTS or not wanted:
                break

    print(f"\nWrote {written:,} products to {OUT_FILE}")


if __name__ == "__main__":
    main()
