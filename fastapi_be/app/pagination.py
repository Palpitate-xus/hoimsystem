def paginate(query, page: int | None = None, page_size: int | None = None):
    """对 SQLAlchemy Query 进行分页，返回 (items, total)。"""
    total = query.count()
    if page and page_size:
        offset = (page - 1) * page_size
        items = query.offset(offset).limit(page_size).all()
    else:
        items = query.all()
    return items, total
