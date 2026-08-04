"""
Cross-modal review checker.

Search a product, see its photos on the left and its details and reviewer
comments on the right, and record whether each reviewer's photo agrees with
what they wrote.

Run:  streamlit run app.py
"""

import json
import os
import random
import shutil
import sqlite3
import io
import csv
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

# ----------------------------- config -----------------------------
DATA_FILE = Path(__file__).parent / "products.jsonl"
DB_FILE = Path(__file__).parent / "annotations.db"

# products.jsonl is ~290MB, too large to commit to git. When it isn't present
# locally, fetch it once from a Hugging Face dataset repo (set HF_DATASET_REPO,
# and HF_TOKEN if that dataset is private) and cache it beside this script.
def _secret(key):
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""


HF_DATASET_REPO = os.environ.get("HF_DATASET_REPO") or _secret("HF_DATASET_REPO")
HF_TOKEN = os.environ.get("HF_TOKEN") or _secret("HF_TOKEN")


def ensure_products_file():
    if DATA_FILE.exists() or not HF_DATASET_REPO:
        return
    from huggingface_hub import hf_hub_download

    with st.spinner("Downloading product catalog (first run only)..."):
        downloaded = hf_hub_download(
            repo_id=HF_DATASET_REPO,
            repo_type="dataset",
            filename="products.jsonl",
            token=HF_TOKEN or None,
        )
        shutil.copy(downloaded, DATA_FILE)

VERDICTS = [
    "Not judged",
    "Photo supports the review",
    "Photo contradicts the review",
    "Photo shows something the review never mentions",
    "Cannot tell from this photo",
]
# ------------------------------------------------------------------

st.set_page_config(page_title="Cross-modal review checker", layout="wide")

st.markdown(
    """
    <style>
      .block-container { padding-top: 2.2rem; max-width: 1400px; }
      .review-card {
        border: 1px solid rgba(128,128,128,0.28);
        border-radius: 6px;
        padding: 0.9rem 1.1rem;
        margin-bottom: 1.1rem;
      }
      .meta-line {
        font-size: 0.82rem;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        opacity: 0.62;
        margin-bottom: 0.15rem;
      }
      .fact-label {
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        opacity: 0.55;
      }
      .fact-value { font-size: 1rem; margin-bottom: 0.7rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------ data ------------------------------
@st.cache_data(show_spinner="Loading products...")
def load_products(path_str: str):
    path = Path(path_str)
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def search(products, query, limit=40):
    """Rank products by how many query words appear in the title."""
    words = [w for w in query.lower().split() if len(w) > 1]
    if not words:
        return []
    scored = []
    for p in products:
        title = (p.get("title") or "").lower()
        hits = sum(1 for w in words if w in title)
        if hits:
            # Full-phrase matches float to the top, then shorter titles.
            phrase = 1 if query.lower() in title else 0
            scored.append((phrase, hits / len(words), -len(title), p))
    scored.sort(key=lambda t: t[:3], reverse=True)
    return [t[3] for t in scored[:limit]]


# --------------------------- annotations --------------------------
def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS annotations (
            annotator    TEXT NOT NULL,
            parent_asin  TEXT NOT NULL,
            review_key   TEXT NOT NULL,
            product_title TEXT,
            review_text  TEXT,
            image_urls   TEXT,
            verdict      TEXT,
            claim        TEXT,
            notes        TEXT,
            updated_at   TEXT,
            PRIMARY KEY (annotator, parent_asin, review_key)
        )
        """
    )
    conn.commit()
    return conn


def save_annotation(conn, **row):
    row["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT OR REPLACE INTO annotations ({cols}) VALUES ({marks})",
        list(row.values()),
    )
    conn.commit()


def load_annotation(conn, annotator, parent_asin, review_key):
    cur = conn.execute(
        "SELECT verdict, claim, notes FROM annotations "
        "WHERE annotator=? AND parent_asin=? AND review_key=?",
        (annotator, parent_asin, review_key),
    )
    return cur.fetchone()


def export_csv(conn):
    cur = conn.execute("SELECT * FROM annotations ORDER BY annotator, parent_asin")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([d[0] for d in cur.description])
    writer.writerows(cur.fetchall())
    return buf.getvalue()


def review_key(r):
    return f"{r.get('user_id', '')}:{r.get('timestamp', '')}"


def show_image(url, caption=None):
    """st.image renamed its width argument across versions; handle both."""
    try:
        st.image(url, caption=caption, use_container_width=True)
    except TypeError:
        st.image(url, caption=caption, use_column_width=True)


# ------------------------------ app -------------------------------
conn = get_db()
ensure_products_file()
products = load_products(str(DATA_FILE))

with st.sidebar:
    st.subheader("Who is checking")
    annotator = st.text_input(
        "Your name", value=st.session_state.get("annotator", ""),
        placeholder="e.g. nagbhushan",
    ).strip()
    st.session_state["annotator"] = annotator

    st.divider()
    st.caption(f"{len(products):,} products loaded")
    done = conn.execute(
        "SELECT COUNT(*) FROM annotations WHERE verdict != ?", ("Not judged",)
    ).fetchone()[0]
    mine = conn.execute(
        "SELECT COUNT(*) FROM annotations WHERE annotator=? AND verdict != ?",
        (annotator, "Not judged"),
    ).fetchone()[0] if annotator else 0
    st.metric("Judgements recorded", f"{done:,}", delta=f"{mine:,} by you")

    st.download_button(
        "Download all judgements (CSV)",
        data=export_csv(conn),
        file_name="cross_modal_judgements.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.title("Cross-modal review checker")
st.write(
    "Find a product, then read each reviewer's words next to the photo they "
    "uploaded. Mark the ones where the two disagree."
)

if not products:
    st.error(
        f"No product file at {DATA_FILE}. Run prepare_app_data.py first, then "
        "put products.jsonl beside this script."
    )
    st.stop()

with st.form("search_form"):
    c1, c2, c3 = st.columns([6, 1, 1])
    query = c1.text_input(
        "Product name", value=st.session_state.get("query", ""),
        placeholder="Paste or type a product name",
        label_visibility="collapsed",
    )
    submitted = c2.form_submit_button("Submit", use_container_width=True)
    surprise = c3.form_submit_button("Random", use_container_width=True)

if surprise:
    st.session_state["selected"] = random.choice(products)["parent_asin"]
    st.session_state["matches"] = None
elif submitted:
    st.session_state["query"] = query
    matches = search(products, query)
    st.session_state["matches"] = [p["parent_asin"] for p in matches]
    st.session_state["selected"] = matches[0]["parent_asin"] if matches else None
    if not matches:
        st.warning("No product title contains those words. Try fewer or broader words.")

index = {p["parent_asin"]: p for p in products}
match_ids = st.session_state.get("matches")

if match_ids and len(match_ids) > 1:
    chosen = st.selectbox(
        f"{len(match_ids)} products matched — pick one",
        options=match_ids,
        format_func=lambda pa: index[pa]["title"][:110],
        index=match_ids.index(st.session_state["selected"])
        if st.session_state.get("selected") in match_ids else 0,
    )
    st.session_state["selected"] = chosen

selected = st.session_state.get("selected")
if not selected:
    st.stop()

p = index[selected]
st.divider()

left, right = st.columns([2, 3], gap="large")

with left:
    if p["catalog_images"]:
        show_image(p["catalog_images"][0])
        if len(p["catalog_images"]) > 1:
            cols = st.columns(min(3, len(p["catalog_images"]) - 1))
            for col, url in zip(cols, p["catalog_images"][1:4]):
                with col:
                    show_image(url)
    else:
        st.info("This product has no catalog photo in the metadata.")
    st.caption("Seller photos. Reviewer photos appear beside each review.")

with right:
    st.subheader(p["title"])
    f1, f2, f3 = st.columns(3)
    f1.markdown(
        f"<div class='fact-label'>Rating</div><div class='fact-value'>"
        f"{p.get('average_rating', '—')} ({p.get('rating_number') or 0:,})</div>",
        unsafe_allow_html=True,
    )
    f2.markdown(
        f"<div class='fact-label'>Price</div><div class='fact-value'>"
        f"{p.get('price') or '—'}</div>",
        unsafe_allow_html=True,
    )
    f3.markdown(
        f"<div class='fact-label'>Store</div><div class='fact-value'>"
        f"{p.get('store') or '—'}</div>",
        unsafe_allow_html=True,
    )
    st.caption(f"parent_asin `{p['parent_asin']}`")

    if p.get("features"):
        with st.expander("Listed features"):
            for f in p["features"]:
                st.markdown(f"- {f}")
    if p.get("description"):
        with st.expander("Description"):
            st.write(p["description"])

st.divider()
st.subheader(f"Reviews with photos ({len(p['reviews'])})")

if not annotator:
    st.info("Enter your name in the sidebar to start recording judgements.")

for i, r in enumerate(p["reviews"]):
    key = review_key(r)
    st.markdown("<div class='review-card'>", unsafe_allow_html=True)

    rc_left, rc_right = st.columns([2, 3], gap="large")

    with rc_left:
        urls = r.get("image_urls", [])
        for url in urls[:3]:
            show_image(url)
        if len(urls) > 3:
            st.caption(f"+{len(urls) - 3} more photos on this review")

    with rc_right:
        stars = "★" * int(r.get("rating") or 0) + "☆" * (5 - int(r.get("rating") or 0))
        st.markdown(
            f"<div class='meta-line'>{stars} &nbsp;·&nbsp; "
            f"{'verified purchase' if r.get('verified_purchase') else 'unverified'} "
            f"&nbsp;·&nbsp; {r.get('helpful_vote') or 0} found this helpful</div>",
            unsafe_allow_html=True,
        )
        if r.get("title"):
            st.markdown(f"**{r['title']}**")
        st.write(r.get("text", ""))

        if annotator:
            saved = load_annotation(conn, annotator, p["parent_asin"], key)
            prev_verdict, prev_claim, prev_notes = saved if saved else ("Not judged", "", "")

            verdict = st.radio(
                "Do the photo and the words agree?",
                VERDICTS,
                index=VERDICTS.index(prev_verdict) if prev_verdict in VERDICTS else 0,
                key=f"v_{p['parent_asin']}_{i}",
                horizontal=False,
            )
            claim = st.text_input(
                "Which sentence does the photo bear on?",
                value=prev_claim or "",
                key=f"c_{p['parent_asin']}_{i}",
                placeholder="Copy the exact phrase, e.g. 'the casing arrived without a scratch'",
            )
            notes = st.text_input(
                "Anything else worth noting",
                value=prev_notes or "",
                key=f"n_{p['parent_asin']}_{i}",
            )
            if st.button("Save judgement", key=f"s_{p['parent_asin']}_{i}"):
                save_annotation(
                    conn,
                    annotator=annotator,
                    parent_asin=p["parent_asin"],
                    review_key=key,
                    product_title=p["title"],
                    review_text=r.get("text", ""),
                    image_urls=json.dumps(r.get("image_urls", [])),
                    verdict=verdict,
                    claim=claim,
                    notes=notes,
                )
                st.success("Saved.")

    st.markdown("</div>", unsafe_allow_html=True)
