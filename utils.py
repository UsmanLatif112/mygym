from math import ceil
from flask import request


def paginate_list(items, default_per_page=20):
    """
    Paginate a plain Python list (already fetched/sorted).
    Reads 'page' from request.args, uses a fixed per_page.
    Returns a dict with the page slice and pagination metadata.
    """
    page = request.args.get('page', 1, type=int)
    per_page = default_per_page

    total = len(items)
    total_pages = max(1, ceil(total / per_page))
    page = max(1, min(page, total_pages))  # clamp to valid range

    start = (page - 1) * per_page
    end = start + per_page
    page_items = items[start:end]

    return {
        "items": page_items,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "per_page": per_page
    }