import pytest

from app.database import Base
from app.models import Department


@pytest.fixture(autouse=True)
def isolate_navigation_database(db_session):
    yield
    bind = db_session.get_bind()
    Base.metadata.drop_all(bind=bind)
    Base.metadata.create_all(bind=bind)


@pytest.mark.asyncio
class TestNavigation:
    async def test_admin_can_build_and_query_shortest_route(self, async_client, seed_data, auth_headers, db_session):
        headers = auth_headers(seed_data["admin_user"].username)
        start_department_id = seed_data["department"].department_id
        second_department = Department(name="外科", phone="", location="2号楼", director=None)
        db_session.add(second_department)
        db_session.commit()
        db_session.refresh(second_department)
        entrance = await async_client.post(
            "/api/navigation/admin/nodes",
            headers=headers,
            json={"code": "main-entrance", "name": "门诊大厅", "node_type": "entrance", "location": "1号门"},
        )
        start = await async_client.post(
            "/api/navigation/admin/nodes",
            headers=headers,
            json={"code": "internal-medicine", "name": "内科节点", "node_type": "department", "department_id": start_department_id},
        )
        end = await async_client.post(
            "/api/navigation/admin/nodes",
            headers=headers,
            json={"code": "surgery", "name": "外科节点", "node_type": "department", "department_id": second_department.department_id},
        )
        assert entrance.json()["code"] == start.json()["code"] == end.json()["code"] == 200
        entrance_id = entrance.json()["data"]["node_id"]
        start_id = start.json()["data"]["node_id"]
        end_id = end.json()["data"]["node_id"]
        for from_id, to_id, distance, instruction in (
            (start_id, entrance_id, 10, "沿一号主通道前往大厅"),
            (entrance_id, end_id, 5, "从大厅转向外科"),
            (start_id, end_id, 30, "走长廊直行"),
        ):
            response = await async_client.post(
                "/api/navigation/admin/edges",
                headers=headers,
                json={"from_node_id": from_id, "to_node_id": to_id, "distance": distance, "instruction": instruction, "bidirectional": 1},
            )
            assert response.json()["code"] == 200

        route = await async_client.get(
            "/api/navigation/route/departments",
            headers=headers,
            params={"start_department_id": start_department_id, "end_department_id": second_department.department_id},
        )
        assert route.status_code == 200
        assert route.json()["data"]["total_distance"] == 15
        assert len(route.json()["data"]["steps"]) == 2
        assert route.json()["data"]["steps"][0]["instruction"] == "沿一号主通道前往大厅"

    async def test_route_requires_configured_nodes_and_node_delete_is_safe(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["admin_user"].username)
        missing = await async_client.get(
            "/api/navigation/route/departments",
            headers=headers,
            params={"start_department_id": seed_data["department"].department_id, "end_department_id": 999999},
        )
        assert missing.status_code == 200
        assert missing.json()["code"] == 404

        node = await async_client.post("/api/navigation/admin/nodes", headers=headers, json={"code": "delete-me", "name": "待删节点"})
        node_id = node.json()["data"]["node_id"]
        deleted = await async_client.request("DELETE", "/api/navigation/admin/nodes", headers=headers, json={"node_id": node_id})
        assert deleted.json()["code"] == 200

    async def test_non_admin_cannot_manage_navigation_graph(self, async_client, seed_data, auth_headers):
        response = await async_client.post(
            "/api/navigation/admin/nodes",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"code": "blocked", "name": "不应创建"},
        )
        assert response.status_code == 403
