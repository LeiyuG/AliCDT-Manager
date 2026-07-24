import os
import json
import httpx
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from jose import jwt
from passlib.context import CryptContext

from models.database import init_db, get_db, Account, Instance, Log, Settings
from core.aliyun import AliyunClient
from core.cloudflare import CloudflareDNSClient
from scheduler.jobs import (
    start_scheduler,
    sync_instances,
    traffic_check,
    add_important_log,
    configure_keep_alive_job,
    MIN_KEEP_ALIVE_INTERVAL_MINUTES,
    MAX_KEEP_ALIVE_INTERVAL_MINUTES,
    DEFAULT_ROTATION_GRACE_SECONDS,
    DEFAULT_ROTATION_TIMEOUT_SECONDS,
    DEFAULT_ROTATION_TRAFFIC_PROTECT_GB,
)

SECRET_KEY = os.environ.get("SECRET_KEY", "fallback-change-me")
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_SETTING_KEYS = {"cloudflare_api_token"}


def create_token(username: str):
    expire = datetime.utcnow() + timedelta(days=7)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except Exception:
        return None


from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
security = HTTPBearer(auto_error=False)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
    if not credentials:
        raise HTTPException(status_code=401, detail="未授权")
    user = verify_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Token无效或已过期")
    return user


app = FastAPI(title="AliCDT Manager", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await init_db()
    await start_scheduler()


class LoginRequest(BaseModel):
    username: str
    password: str


class AccountCreate(BaseModel):
    name: str
    access_key_id: str
    access_key_secret: Optional[str] = None
    region_id: str
    site_type: str = "international"
    instance_id: Optional[str] = None
    traffic_limit_gb: float = 200.0
    threshold_percent: float = 95.0
    outstanding_threshold: float = 0.0
    shutdown_mode: str = "StopCharging"
    keep_alive: bool = False
    auto_start_time: Optional[str] = None
    auto_stop_time: Optional[str] = None


class SettingUpdate(BaseModel):
    key: str
    value: str


class RemarkRequest(BaseModel):
    remark: Optional[str] = None


@app.get("/api/auth/initialized")
async def is_initialized(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Settings).where(Settings.key == "admin_password_hash"))
    return {"initialized": result.scalar_one_or_none() is not None}


@app.post("/api/auth/init")
async def init_admin(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Settings).where(Settings.key == "admin_password_hash"))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="已初始化，请直接登录")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")
    hashed = pwd_context.hash(req.password)
    db.add(Settings(key="admin_username", value=req.username))
    db.add(Settings(key="admin_password_hash", value=hashed))
    await db.commit()
    return {"token": create_token(req.username), "username": req.username}


@app.post("/api/auth/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Settings).where(Settings.key == "admin_username"))
    username_row = result.scalar_one_or_none()
    result = await db.execute(select(Settings).where(Settings.key == "admin_password_hash"))
    password_row = result.scalar_one_or_none()
    if not username_row or not password_row:
        raise HTTPException(status_code=403, detail="系统未初始化")
    if req.username != username_row.value or not pwd_context.verify(req.password, password_row.value):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"token": create_token(req.username), "username": req.username}


@app.get("/api/accounts")
async def list_accounts(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account))
    accounts = result.scalars().all()
    return [
        {k: v for k, v in acc.__dict__.items() if k != "_sa_instance_state" and k != "access_key_secret"}
        for acc in accounts
    ]


@app.post("/api/accounts")
async def create_account(data: AccountCreate, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not data.access_key_secret:
        raise HTTPException(status_code=400, detail="新建账户必须填写 AccessKey Secret")
    acc = Account(**data.model_dump())
    db.add(acc)
    await db.commit()
    await db.refresh(acc)
    await sync_instances()
    await traffic_check()
    return {"id": acc.id, "message": "账户已添加"}


@app.put("/api/accounts/{account_id}")
async def update_account(account_id: int, data: AccountCreate, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).where(Account.id == account_id))
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="账户不存在")
    update_data = data.model_dump()
    if not update_data.get("access_key_secret"):
        update_data.pop("access_key_secret")
    for k, v in update_data.items():
        setattr(acc, k, v)
    await db.commit()
    return {"message": "更新成功"}


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Instance).where(Instance.account_id == account_id))
    await db.execute(delete(Account).where(Account.id == account_id))
    await db.commit()
    return {"message": "删除成功"}


@app.get("/api/instances")
async def list_instances(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Instance))
    instances = result.scalars().all()
    return [{k: v for k, v in i.__dict__.items() if k != "_sa_instance_state"} for i in instances]


@app.post("/api/instances/sync")
async def manual_sync(user=Depends(get_current_user)):
    await sync_instances()
    await traffic_check()
    return {"message": "同步完成"}


@app.post("/api/instances/{instance_id}/sync")
async def sync_single_instance(instance_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Instance).where(Instance.instance_id == instance_id))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404)
    result = await db.execute(select(Account).where(Account.id == inst.account_id))
    acc = result.scalar_one_or_none()
    client = AliyunClient(acc.access_key_id, acc.access_key_secret, acc.region_id, acc.site_type)
    status = await client.get_instance_status(instance_id)
    traffic_gb = await client.get_cdt_traffic()
    limit = acc.traffic_limit_gb or 200.0
    percent = round(traffic_gb / limit * 100, 2)
    inst.status = status
    inst.traffic_used_gb = traffic_gb
    inst.traffic_percent = percent
    inst.last_synced = datetime.utcnow()
    await db.commit()
    return {"message": "同步完成", "status": status, "traffic_gb": traffic_gb, "percent": percent}


@app.patch("/api/instances/{instance_id}/remark")
async def update_instance_remark(instance_id: str, data: RemarkRequest, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Instance).where(Instance.instance_id == instance_id))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404)
    remark = (data.remark or "").strip()
    if len(remark) > 100:
        raise HTTPException(status_code=400, detail="备注不能超过 100 个字符")
    inst.remark = remark or None
    await db.commit()
    return {"message": "更新成功"}


@app.post("/api/instances/{instance_id}/start")
async def start_instance(instance_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Instance).where(Instance.instance_id == instance_id))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404)
    result = await db.execute(select(Account).where(Account.id == inst.account_id))
    acc = result.scalar_one_or_none()
    client = AliyunClient(acc.access_key_id, acc.access_key_secret, acc.region_id, acc.site_type)
    await client.start_instance(instance_id)
    await db.execute(update(Account).where(Account.id == acc.id).values(manual_stopped=False))
    await db.commit()
    await add_important_log("system", f"手动开机: {instance_id}")
    return {"message": "开机指令已发送"}


@app.post("/api/instances/{instance_id}/stop")
async def stop_instance(instance_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Instance).where(Instance.instance_id == instance_id))
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404)
    result = await db.execute(select(Account).where(Account.id == inst.account_id))
    acc = result.scalar_one_or_none()
    client = AliyunClient(acc.access_key_id, acc.access_key_secret, acc.region_id, acc.site_type)
    await client.stop_instance(instance_id, acc.shutdown_mode)
    await db.execute(update(Account).where(Account.id == acc.id).values(manual_stopped=True))
    await db.commit()
    await add_important_log("system", f"手动关机: {instance_id}")
    return {"message": "关机指令已发送"}


@app.get("/api/billing/{account_id}")
async def get_billing(account_id: int, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).where(Account.id == account_id))
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404)
    client = AliyunClient(acc.access_key_id, acc.access_key_secret, acc.region_id, acc.site_type)
    balance = await client.get_balance()
    bill = await client.get_bill_overview()
    return {"balance": balance, "bill": bill}


@app.get("/api/settings")
async def get_settings(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Settings))
    rows = result.scalars().all()
    values = {r.key: r.value for r in rows if "password_hash" not in r.key}
    for key in SECRET_SETTING_KEYS:
        configured = bool(values.get(key))
        values[key] = ""
        values[f"{key}_configured"] = "1" if configured else "0"
    return values


@app.post("/api/settings")
async def update_settings(items: List[SettingUpdate], user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    existing_result = await db.execute(select(Settings))
    existing_values = {row.key: row.value for row in existing_result.scalars().all()}
    submitted_values = {item.key: item.value for item in items}
    merged_values = {**existing_values, **submitted_values}
    keep_alive_interval = None

    if merged_values.get("rotation_enabled", "0") not in {"0", "1"}:
        raise HTTPException(status_code=400, detail="轮换开关参数无效")

    rotation_enabled = merged_values.get("rotation_enabled", "0") == "1"

    def parse_rotation_ids(values):
        raw_ids = str(values.get("rotation_instance_ids") or "").strip()
        if raw_ids:
            try:
                parsed_ids = json.loads(raw_ids)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="轮换实例列表格式无效")
            if not isinstance(parsed_ids, list):
                raise HTTPException(status_code=400, detail="轮换实例列表格式无效")
            return [
                str(instance_id).strip()
                for instance_id in parsed_ids
                if str(instance_id).strip()
            ]
        return [
            instance_id
            for instance_id in (
                str(values.get("rotation_instance_a") or "").strip(),
                str(values.get("rotation_instance_b") or "").strip(),
            )
            if instance_id
        ]

    rotation_ids = parse_rotation_ids(merged_values)
    rotation_active = (
        merged_values.get("rotation_active_instance_id", "").strip()
        or (rotation_ids[0] if rotation_ids else "")
    )
    rotation_time = merged_values.get("rotation_switch_time", "00:00").strip()
    try:
        datetime.strptime(rotation_time, "%H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="每日切换时间格式必须为 HH:MM")

    def parse_rotation_number(key, default, minimum, maximum, label, cast):
        raw = merged_values.get(key, str(default))
        try:
            value = cast(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{label}格式无效")
        if not minimum <= value <= maximum:
            raise HTTPException(status_code=400, detail=f"{label}必须在 {minimum}～{maximum} 之间")
        return value

    rotation_grace = parse_rotation_number(
        "rotation_grace_seconds", DEFAULT_ROTATION_GRACE_SECONDS, 0, 600, "切换缓冲秒数", int
    )
    rotation_timeout = parse_rotation_number(
        "rotation_timeout_seconds", DEFAULT_ROTATION_TIMEOUT_SECONDS, 60, 900, "状态确认超时秒数", int
    )
    rotation_protect = parse_rotation_number(
        "rotation_traffic_protect_gb",
        DEFAULT_ROTATION_TRAFFIC_PROTECT_GB,
        1,
        10000,
        "流量保护值",
        float,
    )

    if rotation_enabled:
        if len(rotation_ids) < 2:
            raise HTTPException(status_code=400, detail="请至少选择两台抢占式实例参与轮换")
        if len(set(rotation_ids)) != len(rotation_ids):
            raise HTTPException(status_code=400, detail="轮换实例不能重复")
        if rotation_active not in set(rotation_ids):
            raise HTTPException(status_code=400, detail="当前当班实例必须在轮换列表中")

        result = await db.execute(
            select(Instance).where(Instance.instance_id.in_(rotation_ids))
        )
        rotation_instances = result.scalars().all()
        if len(rotation_instances) != len(rotation_ids):
            raise HTTPException(status_code=400, detail="部分轮换实例不存在，请先同步实例")
        non_spot = [instance.instance_id for instance in rotation_instances if not instance.is_spot]
        if non_spot:
            raise HTTPException(
                status_code=400,
                detail=f"只有抢占式实例可以参与轮换：{', '.join(non_spot)}",
            )
        if len({instance.account_id for instance in rotation_instances}) != len(rotation_instances):
            raise HTTPException(
                status_code=400,
                detail="每个阿里云账号只能选择一台实例参与轮换",
            )

        cloudflare_token = submitted_values.get("cloudflare_api_token", "").strip() or existing_values.get("cloudflare_api_token", "")
        if not cloudflare_token:
            raise HTTPException(status_code=400, detail="请填写 Cloudflare API Token")
        if not merged_values.get("cloudflare_zone_id", "").strip():
            raise HTTPException(status_code=400, detail="请填写 Cloudflare Zone ID")
        if not merged_values.get("cloudflare_record_name", "").strip():
            raise HTTPException(status_code=400, detail="请填写需要更新的完整域名")

    normalized_rotation = {
        "rotation_enabled": "1" if rotation_enabled else "0",
        "rotation_instance_ids": json.dumps(rotation_ids, ensure_ascii=False),
        "rotation_instance_a": rotation_ids[0] if rotation_ids else "",
        "rotation_instance_b": rotation_ids[1] if len(rotation_ids) > 1 else "",
        "rotation_active_instance_id": rotation_active,
        "rotation_switch_time": rotation_time,
        "rotation_grace_seconds": str(rotation_grace),
        "rotation_timeout_seconds": str(rotation_timeout),
        "rotation_traffic_protect_gb": str(rotation_protect),
    }
    submitted_values.update(normalized_rotation)

    existing_rotation_ids = parse_rotation_ids(existing_values)
    targets_changed = (
        existing_rotation_ids != rotation_ids
        or existing_values.get("rotation_active_instance_id", "") != rotation_active
    )
    just_enabled = existing_values.get("rotation_enabled", "0") != "1" and rotation_enabled
    if rotation_enabled and (just_enabled or targets_changed):
        submitted_values["rotation_last_switch_date"] = ""

    for key, submitted_value in submitted_values.items():
        value = submitted_value
        if key == "keep_alive_interval_minutes":
            try:
                keep_alive_interval = int(value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="保活检查间隔必须是整数分钟")
            if not MIN_KEEP_ALIVE_INTERVAL_MINUTES <= keep_alive_interval <= MAX_KEEP_ALIVE_INTERVAL_MINUTES:
                raise HTTPException(
                    status_code=400,
                    detail=f"保活检查间隔必须在 {MIN_KEEP_ALIVE_INTERVAL_MINUTES}～{MAX_KEEP_ALIVE_INTERVAL_MINUTES} 分钟之间",
                )
            value = str(keep_alive_interval)

        if key in SECRET_SETTING_KEYS and not str(value).strip():
            continue

        result = await db.execute(select(Settings).where(Settings.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.add(Settings(key=key, value=value))
    await db.commit()
    if keep_alive_interval is not None:
        await configure_keep_alive_job(keep_alive_interval)
    return {
        "message": "保存成功",
        "keep_alive_interval_minutes": keep_alive_interval,
    }


@app.post("/api/settings/test-cloudflare")
async def test_cloudflare(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Settings).where(
            Settings.key.in_(
                ["cloudflare_api_token", "cloudflare_zone_id", "cloudflare_record_name"]
            )
        )
    )
    values = {row.key: row.value for row in result.scalars().all()}
    token = values.get("cloudflare_api_token", "")
    zone_id = values.get("cloudflare_zone_id", "")
    record_name = values.get("cloudflare_record_name", "")
    if not token or not zone_id or not record_name:
        raise HTTPException(status_code=400, detail="请先保存完整的 Cloudflare DDNS 配置")
    try:
        record = await CloudflareDNSClient(token, zone_id).get_a_record(record_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cloudflare 验证失败: {exc}")
    return {
        "message": "Cloudflare 连接成功",
        "record_name": record.get("name"),
        "content": record.get("content"),
        "proxied": bool(record.get("proxied")),
    }


@app.post("/api/settings/test-tg")
async def test_tg(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Settings).where(Settings.key == "tg_bot_token"))
    token_row = result.scalar_one_or_none()
    result = await db.execute(select(Settings).where(Settings.key == "tg_chat_id"))
    chat_row = result.scalar_one_or_none()
    if not token_row or not chat_row or not token_row.value or not chat_row.value:
        raise HTTPException(status_code=400, detail="请先保存 Bot Token 和 Chat ID")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{token_row.value}/sendMessage",
                json={"chat_id": chat_row.value, "text": "✅ AliCDT Manager 测试消息发送成功"}
            )
            data = r.json()
            if not data.get("ok"):
                raise HTTPException(status_code=400, detail=f"TG返回错误: {data.get('description')}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发送失败: {e}")
    return {"message": "测试消息已发送"}


@app.post("/api/settings/test-daily-report")
async def test_daily_report(user=Depends(get_current_user)):
    from scheduler.jobs import _do_daily_report
    await _do_daily_report()
    return {"message": "流量汇报已发送"}


@app.post("/api/settings/change-password")
async def change_password(data: dict, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    new_hash = pwd_context.hash(data.get("password", ""))
    result = await db.execute(select(Settings).where(Settings.key == "admin_password_hash"))
    row = result.scalar_one_or_none()
    if row:
        row.value = new_hash
    await db.commit()
    return {"message": "密码已更新"}


@app.get("/api/logs")
async def get_logs(category: Optional[str] = None, limit: int = 100, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = select(Log).order_by(Log.id.desc()).limit(limit)
    if category:
        query = select(Log).where(Log.category == category).order_by(Log.id.desc()).limit(limit)
    result = await db.execute(query)
    logs = result.scalars().all()
    return [{k: v for k, v in l.__dict__.items() if k != "_sa_instance_state"} for l in logs]


@app.delete("/api/logs")
async def clear_logs(category: Optional[str] = None, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if category:
        await db.execute(delete(Log).where(Log.category == category))
    else:
        await db.execute(delete(Log))
    await db.commit()
    return {"message": "日志已清空"}


if os.path.exists("/app/frontend/dist"):
    app.mount("/assets", StaticFiles(directory="/app/frontend/dist/assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        return FileResponse("/app/frontend/dist/index.html")
