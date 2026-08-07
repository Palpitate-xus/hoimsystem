import datetime
import heapq

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, User, get_current_user, require_roles
from app.models import Department, NavigationEdge, NavigationNode
from app.schemas import (
    NavigationEdgeCreateRequest,
    NavigationEdgeDeleteRequest,
    NavigationEdgeUpdateRequest,
    NavigationNodeCreateRequest,
    NavigationNodeDeleteRequest,
    NavigationNodeUpdateRequest,
)

router = APIRouter()


def _node_data(item: NavigationNode):
    return {
        "node_id": item.node_id,
        "code": item.code,
        "name": item.name,
        "node_type": item.node_type,
        "floor": item.floor or "",
        "location": item.location or "",
        "campus_id": item.campus_id,
        "campus_name": item.campus.name if item.campus else "",
        "department_id": item.department_id,
        "department_name": item.department.name if item.department else "",
        "status": item.status,
    }


def _edge_data(item: NavigationEdge):
    return {
        "edge_id": item.edge_id,
        "from_node_id": item.from_node_id,
        "from_node_name": item.from_node.name if item.from_node else "",
        "to_node_id": item.to_node_id,
        "to_node_name": item.to_node.name if item.to_node else "",
        "distance": item.distance,
        "instruction": item.instruction or "",
        "bidirectional": item.bidirectional,
        "status": item.status,
    }


def _same_campus(left: NavigationNode, right: NavigationNode) -> bool:
    return left.campus_id == right.campus_id


@router.get("/navigation/nodes")
def list_navigation_nodes(campus_id: int | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(NavigationNode).filter(NavigationNode.status == 1)
    if campus_id is not None:
        query = query.filter(NavigationNode.campus_id == campus_id)
    return {"code": 200, "msg": "success", "data": [_node_data(item) for item in query.order_by(NavigationNode.node_id).all()]}


@router.get("/navigation/route")
def find_navigation_route(start_node_id: int, end_node_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start = db.query(NavigationNode).filter(NavigationNode.node_id == start_node_id, NavigationNode.status == 1).first()
    end = db.query(NavigationNode).filter(NavigationNode.node_id == end_node_id, NavigationNode.status == 1).first()
    if not start or not end:
        return {"code": 404, "msg": "起点或终点导航节点不存在"}
    if not _same_campus(start, end):
        return {"code": 400, "msg": "起点和终点不属于同一院区"}
    if start.node_id == end.node_id:
        return {"code": 200, "msg": "success", "data": {"total_distance": 0, "nodes": [_node_data(start)], "steps": []}}
    nodes = {item.node_id: item for item in db.query(NavigationNode).filter(NavigationNode.status == 1, NavigationNode.campus_id == start.campus_id).all()}
    graph = {node_id: [] for node_id in nodes}
    for edge in db.query(NavigationEdge).filter(NavigationEdge.status == 1).all():
        if edge.from_node_id not in nodes or edge.to_node_id not in nodes:
            continue
        graph[edge.from_node_id].append((edge.to_node_id, edge.distance, edge.instruction))
        if edge.bidirectional:
            graph[edge.to_node_id].append((edge.from_node_id, edge.distance, edge.instruction))
    distances = {start.node_id: 0.0}
    previous = {}
    queue = [(0.0, start.node_id)]
    while queue:
        distance, node_id = heapq.heappop(queue)
        if distance > distances.get(node_id, float("inf")):
            continue
        if node_id == end.node_id:
            break
        for next_id, edge_distance, instruction in graph.get(node_id, []):
            candidate = distance + edge_distance
            if candidate < distances.get(next_id, float("inf")):
                distances[next_id] = candidate
                previous[next_id] = (node_id, instruction, edge_distance)
                heapq.heappush(queue, (candidate, next_id))
    if end.node_id not in distances:
        return {"code": 404, "msg": "未找到可用院内路线"}
    path = [end.node_id]
    while path[-1] != start.node_id:
        path.append(previous[path[-1]][0])
    path.reverse()
    steps = []
    for index in range(1, len(path)):
        _, instruction, edge_distance = previous[path[index]]
        steps.append({"from_node_id": path[index - 1], "to_node_id": path[index], "distance": edge_distance, "instruction": instruction or f"前往{nodes[path[index]].name}"})
    return {"code": 200, "msg": "success", "data": {"total_distance": round(distances[end.node_id], 2), "nodes": [_node_data(nodes[node_id]) for node_id in path], "steps": steps}}


@router.get("/navigation/route/departments")
def find_department_route(start_department_id: int, end_department_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start = db.query(NavigationNode).filter(NavigationNode.department_id == start_department_id, NavigationNode.status == 1).order_by(NavigationNode.node_id).first()
    end = db.query(NavigationNode).filter(NavigationNode.department_id == end_department_id, NavigationNode.status == 1).order_by(NavigationNode.node_id).first()
    if not start or not end:
        return {"code": 404, "msg": "起点或终点尚未配置院内导航节点"}
    return find_navigation_route(start.node_id, end.node_id, current_user, db)


@router.get("/navigation/admin/nodes")
def admin_list_navigation_nodes(current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "msg": "success", "data": [_node_data(item) for item in db.query(NavigationNode).order_by(NavigationNode.node_id).all()]}


@router.post("/navigation/admin/nodes")
def admin_create_navigation_node(req: NavigationNodeCreateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    if db.query(NavigationNode).filter(NavigationNode.code == req.code.strip()).first():
        return {"code": 400, "msg": "导航节点编码已存在"}
    department = db.query(Department).filter(Department.department_id == req.department_id).first() if req.department_id else None
    if req.department_id and not department:
        return {"code": 400, "msg": "关联科室不存在"}
    if department and req.campus_id is not None and department.campus_id != req.campus_id:
        return {"code": 400, "msg": "科室与院区不匹配"}
    now = datetime.datetime.now()
    item = NavigationNode(
        code=req.code.strip(),
        name=req.name.strip(),
        node_type=req.node_type.strip(),
        floor=req.floor.strip(),
        location=req.location.strip(),
        campus_id=req.campus_id if req.campus_id is not None else (department.campus_id if department else None),
        department_id=req.department_id,
        status=req.status,
        create_time=now,
        update_time=now,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"code": 200, "msg": "success", "data": _node_data(item)}


@router.put("/navigation/admin/nodes")
def admin_update_navigation_node(req: NavigationNodeUpdateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(NavigationNode).filter(NavigationNode.node_id == req.node_id).first()
    if not item:
        return {"code": 404, "msg": "导航节点不存在"}
    duplicate = db.query(NavigationNode).filter(NavigationNode.code == req.code.strip(), NavigationNode.node_id != req.node_id).first()
    if duplicate:
        return {"code": 400, "msg": "导航节点编码已存在"}
    department = db.query(Department).filter(Department.department_id == req.department_id).first() if req.department_id else None
    if req.department_id and not department:
        return {"code": 400, "msg": "关联科室不存在"}
    if department and req.campus_id is not None and department.campus_id != req.campus_id:
        return {"code": 400, "msg": "科室与院区不匹配"}
    item.code = req.code.strip()
    item.name = req.name.strip()
    item.node_type = req.node_type.strip()
    item.floor = req.floor.strip()
    item.location = req.location.strip()
    item.campus_id = req.campus_id if req.campus_id is not None else (department.campus_id if department else None)
    item.department_id = req.department_id
    item.status = req.status
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _node_data(item)}


@router.delete("/navigation/admin/nodes")
def admin_delete_navigation_node(req: NavigationNodeDeleteRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(NavigationNode).filter(NavigationNode.node_id == req.node_id).first()
    if not item:
        return {"code": 404, "msg": "导航节点不存在"}
    if db.query(NavigationEdge).filter((NavigationEdge.from_node_id == req.node_id) | (NavigationEdge.to_node_id == req.node_id)).first():
        return {"code": 400, "msg": "节点仍被路线使用，不能删除"}
    db.delete(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/navigation/admin/edges")
def admin_list_navigation_edges(current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "msg": "success", "data": [_edge_data(item) for item in db.query(NavigationEdge).order_by(NavigationEdge.edge_id).all()]}


def _validate_edge_nodes(db: Session, from_node_id: int, to_node_id: int):
    if from_node_id == to_node_id:
        return None, None, "起点和终点不能相同"
    from_node = db.query(NavigationNode).filter(NavigationNode.node_id == from_node_id).first()
    to_node = db.query(NavigationNode).filter(NavigationNode.node_id == to_node_id).first()
    if not from_node or not to_node:
        return None, None, "路线节点不存在"
    if not _same_campus(from_node, to_node):
        return None, None, "路线两端必须属于同一院区"
    return from_node, to_node, None


@router.post("/navigation/admin/edges")
def admin_create_navigation_edge(req: NavigationEdgeCreateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    from_node, to_node, error = _validate_edge_nodes(db, req.from_node_id, req.to_node_id)
    if error:
        return {"code": 400, "msg": error}
    now = datetime.datetime.now()
    item = NavigationEdge(
        from_node_id=from_node.node_id,
        to_node_id=to_node.node_id,
        distance=req.distance,
        instruction=req.instruction.strip(),
        bidirectional=req.bidirectional,
        status=req.status,
        create_time=now,
        update_time=now,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"code": 200, "msg": "success", "data": _edge_data(item)}


@router.put("/navigation/admin/edges")
def admin_update_navigation_edge(req: NavigationEdgeUpdateRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(NavigationEdge).filter(NavigationEdge.edge_id == req.edge_id).first()
    if not item:
        return {"code": 404, "msg": "路线不存在"}
    _, _, error = _validate_edge_nodes(db, req.from_node_id, req.to_node_id)
    if error:
        return {"code": 400, "msg": error}
    item.from_node_id = req.from_node_id
    item.to_node_id = req.to_node_id
    item.distance = req.distance
    item.instruction = req.instruction.strip()
    item.bidirectional = req.bidirectional
    item.status = req.status
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _edge_data(item)}


@router.delete("/navigation/admin/edges")
def admin_delete_navigation_edge(req: NavigationEdgeDeleteRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(NavigationEdge).filter(NavigationEdge.edge_id == req.edge_id).first()
    if not item:
        return {"code": 404, "msg": "路线不存在"}
    db.delete(item)
    db.commit()
    return {"code": 200, "msg": "success"}
