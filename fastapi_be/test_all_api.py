import requests
import json
import datetime

BASE = "http://localhost:8001"
results = []
passed = 0
failed = 0
appointment_uuid = None
registration_uuid = None
charge_id = None

def test(name, method, path, headers=None, data=None, expected_code=200, check_fn=None):
    global passed, failed
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            r = requests.get(url, headers=headers or {}, timeout=10)
        else:
            r = requests.post(url, headers={**(headers or {}), "Content-Type": "application/json"}, json=data or {}, timeout=10)

        try:
            body = r.json()
        except Exception:
            body = r.text

        ok = r.status_code == expected_code
        if ok and check_fn:
            ok = check_fn(body)

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"[{status}] {method} {path} => HTTP {r.status_code}, body: {json.dumps(body, ensure_ascii=False)[:250]}")
        results.append({"name": name, "status": status, "http": r.status_code, "body": body})
        return body if ok else None
    except Exception as e:
        failed += 1
        print(f"[FAIL] {method} {path} => ERROR: {e}")
        results.append({"name": name, "status": "FAIL", "error": str(e)})
        return None

print("=" * 60)
print("STARTING FULL API TEST SUITE")
print("=" * 60)

# ========== USER / AUTH ==========
test("publicKey", "GET", "/api/publicKey")
test("register", "POST", "/api/register", data={"username":"testuser","password":"123456","identity":"370101199001011234","address":"北京","sex":1,"phone":"13800138000","birthday":"1990-01-01"})
test("login success", "POST", "/api/login", data={"username":"370101199001011234","password":"123456"})
test("login fail", "POST", "/api/login", data={"username":"wrong","password":"wrong"}, expected_code=200, check_fn=lambda b: b.get("code") == 500)
test("userInfo", "POST", "/api/userInfo", data={"accessToken":"370101199001011234"})
test("logout", "POST", "/api/logout")
test("test echo", "POST", "/api/test", data={"data":"hello"})

# ========== ADMIN ==========
print("\n--- ADMIN ---")
test("get doctor list (empty)", "GET", "/api/doctorManagement/getList")
test("get patient list", "GET", "/api/patientManagement/getList")
test("get department list (empty)", "GET", "/api/departmentManagement/getList")

# create department
test("create department", "POST", "/api/departmentManagement/create", data={"name":"内科","phone":"01012345678","director":1,"location":"1号楼"})
test("get department list (has data)", "GET", "/api/departmentManagement/getList", check_fn=lambda b: len(b.get("data", [])) >= 1)

# create notice
test("create notice", "POST", "/api/notice/create", headers={"accesstoken":"370101199001011234"}, data={"title":"通知1","content":"内容","isemergency":1,"towho":["医生","病人"],"expiredtime":"2026-12-31"})
test("get notice list", "GET", "/api/notice/getList", headers={"accesstoken":"370101199001011234"})

# ========== DOCTOR ==========
print("\n--- DOCTOR ---")
# register doctor
test("register doctor", "POST", "/api/doctorManagement/register", data={"username":"doc01","password":"123456","name":"王医生","title":"主任医师","sex":"男","phone":"13900139000","department":1,"permission":"doctor","education":"博士"})

# login as doctor
test("login doctor", "POST", "/api/login", data={"username":"doc01","password":"123456"})

# get doctor list after register
test("get doctor list (has data)", "GET", "/api/doctorManagement/getList", check_fn=lambda b: len(b.get("data", [])) >= 1)

# create schedule for today (Wednesday)
today_weekday = datetime.datetime.now().weekday()
weekdays_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期天"]
today_cn = weekdays_cn[today_weekday]
test("doctor schedule register (today)", "POST", "/api/doctorScheduleManagement/register", headers={"accesstoken":"doc01"}, data={"schedule":[f"{today_cn}上午", f"{today_cn}下午"],"specialist":1,"number":20,"doctor":1})
test("doctor schedule getList", "GET", "/api/doctorScheduleManagement/getList", headers={"accesstoken":"doc01"})

# pharmaceutical
test("pharmaceutical create", "POST", "/api/pharmaceuticalManagement/create", data={"name":"阿司匹林","stock":100,"price":"15.5","expireddate":"2027-06-01","supplier":"华北制药","remark":"常用药"})
test("pharmaceutical getList", "GET", "/api/pharmaceuticalManagement/getList")
test("pharmaceutical stock query", "POST", "/api/pharmaceuticalManagement/stock_query", data={"id":1})

# register another patient for prescription
test("register patient2", "POST", "/api/register", data={"username":"patient2","password":"123456","identity":"370101199001015678","address":"上海","sex":0,"phone":"13700137000","birthday":"1992-02-02"})

# create prescription as doctor
test("prescription create", "POST", "/api/prescriptionManagement/create", headers={"accesstoken":"doc01"}, data={"patient":2,"phas":[{"id":1,"number":2}]})

# get prescription list (doctor view)
resp = test("prescription getList (doctor)", "GET", "/api/prescriptionManagement/getList", headers={"accesstoken":"doc01"})

# get prescription list (patient view)
test("prescription getList (patient)", "GET", "/api/prescriptionManagement/getList", headers={"accesstoken":"370101199001011234"})

# ========== PATIENT ==========
print("\n--- PATIENT ---")

# appointment
test("appointment list", "GET", "/api/appointmentManagement/appointmentList")

# create appointment as patient1
resp = test("appointment create", "POST", "/api/appointmentManagement/create", headers={"accesstoken":"370101199001011234"}, data={"id":1,"date":"2026-05-01","department_id":1,"doctor_id":1,"time":"上午","specialist":1})

# get appointment list
resp = test("appointment getList", "GET", "/api/appointmentManagement/getList", headers={"accesstoken":"370101199001011234"})
if resp and resp.get("data"):
    appointment_uuid = resp["data"][0]["uuid"]

# cancel appointment
if appointment_uuid:
    test("appointment cancel", "POST", "/api/appointmentManagement/cancel", data={"uuid": appointment_uuid})
    test("appointment getList after cancel", "GET", "/api/appointmentManagement/getList", headers={"accesstoken":"370101199001011234"}, check_fn=lambda b: b.get("data") and b["data"][0].get("status") == "已取消")

# registration - need schedule for today to show in registrationList
test("registration list (today)", "GET", "/api/registrationManagement/registrationList", headers={"accesstoken":"370101199001011234"})

# create registration
resp = test("registration create", "POST", "/api/registrationManagement/create", headers={"accesstoken":"370101199001011234"}, data={"id":1,"doctor_id":1,"department_id":1,"specialist":1})

# get registration list
resp = test("registration getList", "GET", "/api/registrationManagement/getList", headers={"accesstoken":"370101199001011234"})
if resp and resp.get("data"):
    registration_uuid = resp["data"][0]["uuid"]

# cancel registration
if registration_uuid:
    test("registration cancel", "POST", "/api/registrationManagement/cancel", data={"uuid": registration_uuid})
    test("registration getList after cancel", "GET", "/api/registrationManagement/getList", headers={"accesstoken":"370101199001011234"}, check_fn=lambda b: b.get("data") and b["data"][0].get("status") == "已取消")

# charge
resp = test("charge getList (patient)", "GET", "/api/chargeManagement/getList", headers={"accesstoken":"370101199001011234"})
if resp and resp.get("data"):
    charge_id = resp["data"][0]["id"]

if charge_id:
    test("charge commit", "POST", "/api/chargeManagement/charge", data={"id": charge_id})
    test("charge getList after commit", "GET", "/api/chargeManagement/getList", headers={"accesstoken":"370101199001011234"}, check_fn=lambda b: b.get("data") and b["data"][0].get("status") == 1)

# charge getList as admin (using patient accesstoken since there's no dedicated admin user in test)
test("charge getList (admin)", "GET", "/api/chargeManagement/getList", headers={"accesstoken":"370101199001011234"})

# get patient list after all registrations
test("get patient list (final)", "GET", "/api/patientManagement/getList", check_fn=lambda b: len(b.get("data", [])) >= 2)

print("\n" + "=" * 60)
print(f"RESULTS: {passed} passed, {failed} failed, total {passed+failed}")
print("=" * 60)

if failed > 0:
    print("\nFAILED TESTS:")
    for r in results:
        if r["status"] == "FAIL":
            print(f"  - {r['name']}")
