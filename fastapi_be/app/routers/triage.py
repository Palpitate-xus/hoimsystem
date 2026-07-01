from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import User, get_current_user
from app.models import Department

router = APIRouter()

# 症状关键词 -> 科室名称 映射
TRIAGE_MAP = {
    "内科": [
        "发烧",
        "发热",
        "感冒",
        "咳嗽",
        "头痛",
        "头晕",
        "恶心",
        "呕吐",
        "腹泻",
        "腹痛",
        "胃痛",
        "胸闷",
        "心悸",
        "高血压",
        "糖尿病",
        "甲亢",
        "甲减",
        "过敏",
        "皮疹",
        "乏力",
        "消瘦",
        "失眠",
        "焦虑",
        "抑郁",
    ],
    "外科": ["骨折", "外伤", "烧伤", "烫伤", "切割伤", "摔伤", "扭伤", "拉伤", "出血", "肿胀", "疼痛", "包块", "肿瘤", "结石", "阑尾炎", "疝气", "痔疮", "肛瘘", "乳腺", "甲状腺", "静脉曲张"],
    "妇产科": ["月经", "痛经", "闭经", "绝经", "白带", "阴道炎", "宫颈炎", "宫颈糜烂", "盆腔炎", "子宫肌瘤", "卵巢囊肿", "不孕", "流产", "早产", "产检", "孕", "分娩", "产后", "避孕", "宫外孕"],
    "儿科": [
        "小儿",
        "婴儿",
        "幼儿",
        "新生儿",
        "儿童",
        "宝宝",
        "孩子",
        "生长发育",
        "疫苗",
        "预防接种",
        "小儿感冒",
        "小儿发烧",
        "小儿腹泻",
        "小儿咳嗽",
        "小儿皮疹",
        "小儿过敏",
        "小儿哮喘",
        "小儿肺炎",
        "小儿黄疸",
    ],
    "眼科": [
        "眼睛",
        "眼痛",
        "眼红",
        "眼痒",
        "流泪",
        "视力模糊",
        "视力下降",
        "近视",
        "远视",
        "散光",
        "白内障",
        "青光眼",
        "结膜炎",
        "角膜炎",
        "眼底",
        "飞蚊症",
        "干眼症",
        "麦粒肿",
        "霰粒肿",
        "斜视",
        "弱视",
    ],
    "耳鼻喉科": [
        "耳朵",
        "耳痛",
        "耳鸣",
        "听力下降",
        "耳聋",
        "耳流脓",
        "中耳炎",
        "鼻炎",
        "鼻塞",
        "流涕",
        "打喷嚏",
        "鼻出血",
        "鼻窦炎",
        "咽炎",
        "咽痛",
        "喉咙痛",
        "扁桃体炎",
        "腺样体肥大",
        "声音嘶哑",
        "声带",
        "异物",
    ],
    "口腔科": ["牙齿", "牙痛", "牙疼", "牙龈", "牙龈出血", "蛀牙", "龋齿", "拔牙", "补牙", "根管治疗", "洗牙", "矫正", "正畸", "种植牙", "口腔溃疡", "口臭", "颞下颌关节", "智齿", "牙周病"],
    "皮肤科": [
        "皮肤",
        "皮疹",
        "红斑",
        "丘疹",
        "水疱",
        "脓疱",
        "瘙痒",
        "脱皮",
        "干燥",
        "湿疹",
        "荨麻疹",
        "痤疮",
        "痘痘",
        "粉刺",
        "色斑",
        "白癜风",
        "银屑病",
        "牛皮癣",
        "脱发",
        "灰指甲",
        "疣",
        "痣",
        "瘢痕",
        "纹身",
    ],
    "骨科": [
        "骨",
        "关节",
        "关节疼痛",
        "关节肿胀",
        "关节炎",
        "风湿",
        "类风湿",
        "强直",
        "脊柱炎",
        "腰椎间盘突出",
        "颈椎病",
        "肩周炎",
        "滑膜炎",
        "半月板",
        "韧带",
        "骨折",
        "骨裂",
        "骨质疏松",
        "骨质增生",
        "骨刺",
        "股骨头坏死",
        "脊柱侧弯",
    ],
    "神经科": [
        "神经",
        "头痛",
        "偏头痛",
        "头晕",
        "眩晕",
        "昏厥",
        "抽搐",
        "癫痫",
        "瘫痪",
        "麻木",
        "刺痛",
        "中风",
        "脑梗",
        "脑出血",
        "脑瘤",
        "帕金森",
        "老年痴呆",
        "阿尔茨海默",
        "多发性硬化",
        "肌无力",
        "面瘫",
        "三叉神经痛",
    ],
    "精神科": ["精神", "心理", "情绪", "焦虑", "抑郁", "双相", "躁狂", "强迫", "恐惧", "失眠", "嗜睡", "厌食", "暴食", "精神分裂症", "幻觉", "妄想", "自闭", "多动", "注意力", "记忆", "认知", "行为"],
    "肿瘤科": ["肿瘤", "癌症", "癌", "肿块", "结节", "占位", "化疗", "放疗", "靶向", "免疫治疗", "病理", "活检", "转移", "复发", "预后"],
    "康复科": ["康复", "理疗", "针灸", "推拿", "按摩", "运动损伤", "术后康复", "中风康复", "骨折康复", "脊髓损伤", "脑瘫", "截肢", "假肢", "言语康复", "吞咽康复"],
    "急诊科": [
        "急",
        "紧急",
        "突发",
        "剧烈疼痛",
        "大出血",
        "昏迷",
        "休克",
        "呼吸困难",
        "窒息",
        "溺水",
        "触电",
        "中毒",
        "车祸",
        "高处坠落",
        "心脏骤停",
        "心梗",
        "脑梗",
        "脑出血",
        "骨折",
        "烧伤",
        "烫伤",
        "异物卡喉",
    ],
    "中医科": ["中医", "中药", "调理", "体质", "气虚", "血虚", "阴虚", "阳虚", "湿气", "火气", "上火", "脾胃", "肝肾", "经络", "针灸", "艾灸", "拔罐", "刮痧", "把脉", "方剂"],
    "体检中心": ["体检", "健康检查", "入职体检", "年度体检", "婚前检查", "孕前检查", "防癌筛查", "慢病筛查", "B超", "CT", "核磁", "血常规", "尿常规", "肝功能", "肾功能", "血脂", "血糖"],
}


def _match_symptoms(text: str):
    text = text.lower()
    matched = []
    for dept_name, keywords in TRIAGE_MAP.items():
        score = 0
        for kw in keywords:
            if kw in text:
                score += 1
        if score > 0:
            matched.append({"department": dept_name, "score": score, "matched_keywords": [k for k in keywords if k in text][:3]})
    matched.sort(key=lambda x: x["score"], reverse=True)
    return matched


@router.post("/triage/suggest")
def triage_suggest(req: dict, db: Session = Depends(get_db)):
    """智能导诊：根据症状描述推荐科室"""
    symptom = req.get("symptom", "")
    if not symptom or len(symptom.strip()) < 2:
        return {"code": 500, "msg": "请输入症状描述（至少2个字）"}
    matched = _match_symptoms(symptom)
    if not matched:
        # 无匹配时返回所有科室
        depts = db.query(Department).all()
        return {
            "code": 200,
            "msg": "success",
            "data": {
                "suggestions": [{"department": d.name, "score": 0, "matched_keywords": []} for d in depts],
                "matched_count": 0,
            },
        }
    # 查询科室详细信息
    suggestions = []
    for item in matched[:5]:
        dept = db.query(Department).filter(Department.name == item["department"]).first()
        suggestions.append(
            {
                "department": item["department"],
                "department_id": dept.department_id if dept else None,
                "score": item["score"],
                "matched_keywords": item["matched_keywords"],
                "location": dept.location if dept else "",
                "phone": dept.phone if dept else "",
            }
        )
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "suggestions": suggestions,
            "matched_count": len(matched),
        },
    }


@router.get("/triage/keywords")
def triage_keywords():
    """获取所有支持的症状关键词"""
    keywords = []
    for dept_name, kws in TRIAGE_MAP.items():
        keywords.extend(kws)
    return {"code": 200, "msg": "success", "data": list(set(keywords))}
