MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def paginate(query, page: int | None = None, page_size: int | None = None):
    """对 SQLAlchemy Query 进行分页，返回 (items, total)。

    分页参数强制收敛：page >= 1，1 <= page_size <= MAX_PAGE_SIZE。
    防止 page_size=-1（SQLite 下 LIMIT -1 等价于无限制）或超大 page_size
    导致全表加载造成的资源耗尽。
    """
    total = query.count()
    page = page if isinstance(page, int) and page >= 1 else 1
    if isinstance(page_size, int) and 1 <= page_size <= MAX_PAGE_SIZE:
        size = page_size
    else:
        size = DEFAULT_PAGE_SIZE
    offset = (page - 1) * size
    items = query.offset(offset).limit(size).all()
    return items, total
