import asyncio
import json
from datetime import datetime
from html import escape
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update
from models.database import AsyncSessionLocal, Account, Instance, Log, Settings
from core.aliyun import AliyunClient
from core.cloudflare import CloudflareDNSClient
import httpx

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

DEFAULT_KEEP_ALIVE_INTERVAL_MINUTES = 5
MIN_KEEP_ALIVE_INTERVAL_MINUTES = 1
MAX_KEEP_ALIVE_INTERVAL_MINUTES = 1440
DEFAULT_ROTATION_SWITCH_TIME = "00:00"
DEFAULT_ROTATION_GRACE_SECONDS = 90
DEFAULT_ROTATION_TIMEOUT_SECONDS = 600
DEFAULT_ROTATION_TRAFFIC_PROTECT_GB = 188.0

rotation_lock = asyncio.Lock()


def parse_keep_alive_interval(value) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        return DEFAULT_KEEP_ALIVE_INTERVAL_MINUTES
    if not MIN_KEEP_ALIVE_INTERVAL_MINUTES <= interval <= MAX_KEEP_ALIVE_INTERVAL_MINUTES:
        return DEFAULT_KEEP_ALIVE_INTERVAL_MINUTES
    return interval


def build_traffic_bar(percent, threshold, segments=10) -> str:
    """Build a compact Telegram-friendly traffic bar."""
    try:
        percent = max(0.0, min(float(percent), 100.0))
    except (TypeError, ValueError):
        percent = 0.0
    try:
        threshold = max(1.0, float(threshold))
    except (TypeError, ValueError):
        threshold = 95.0

    filled = max(0, min(segments, round(percent / 100 * segments)))
    if percent >= threshold:
        color = "🟥"
    elif percent >= threshold * 0.8:
        color = "🟨"
    else:
        color = "🟩"
    return color * filled + "⬜" * (segments - filled)


async def add_important_log(category: str, message: str):
    async with AsyncSessionLocal() as db:
        log = Log(level="info", category=category, message=message)
        db.add(log)
        await db.commit()


async def add_log(level: str, category: str, message: str):
    if level == "info":
        return
    async with AsyncSessionLocal() as db:
        log = Log(level=level, category=category, message=message)
        db.add(log)
        await db.commit()


async def get_setting(key: str, default=None):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Settings).where(Settings.key == key))
        row = result.scalar_one_or_none()
        return row.value if row else default


async def set_setting(key: str, value) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Settings).where(Settings.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = str(value)
        else:
            db.add(Settings(key=key, value=str(value)))
        await db.commit()


async def get_rotation_config() -> dict:
    keys = {
        "rotation_enabled",
        "rotation_instance_a",
        "rotation_instance_b",
        "rotation_instance_ids",
        "rotation_active_instance_id",
        "rotation_switch_time",
        "rotation_grace_seconds",
        "rotation_timeout_seconds",
        "rotation_traffic_protect_gb",
        "rotation_last_switch_date",
        "rotation_last_attempt_at",
        "rotation_last_warning_key",
        "rotation_breaker_latched",
        "cloudflare_api_token",
        "cloudflare_zone_id",
        "cloudflare_record_name",
    }
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Settings).where(Settings.key.in_(keys)))
        values = {row.key: row.value for row in result.scalars().all()}

    try:
        grace_seconds = max(0, min(600, int(values.get("rotation_grace_seconds", DEFAULT_ROTATION_GRACE_SECONDS))))
    except (TypeError, ValueError):
        grace_seconds = DEFAULT_ROTATION_GRACE_SECONDS
    try:
        timeout_seconds = max(60, min(900, int(values.get("rotation_timeout_seconds", DEFAULT_ROTATION_TIMEOUT_SECONDS))))
    except (TypeError, ValueError):
        timeout_seconds = DEFAULT_ROTATION_TIMEOUT_SECONDS
    try:
        traffic_protect_gb = max(1.0, float(values.get("rotation_traffic_protect_gb", DEFAULT_ROTATION_TRAFFIC_PROTECT_GB)))
    except (TypeError, ValueError):
        traffic_protect_gb = DEFAULT_ROTATION_TRAFFIC_PROTECT_GB

    instance_ids = []
    raw_instance_ids = values.get("rotation_instance_ids", "")
    if raw_instance_ids:
        try:
            parsed_ids = json.loads(raw_instance_ids)
            if isinstance(parsed_ids, list):
                instance_ids = [
                    str(instance_id).strip()
                    for instance_id in parsed_ids
                    if str(instance_id).strip()
                ]
        except (TypeError, ValueError):
            instance_ids = []
    if not instance_ids:
        instance_ids = [
            instance_id
            for instance_id in (
                values.get("rotation_instance_a", ""),
                values.get("rotation_instance_b", ""),
            )
            if instance_id
        ]

    return {
        "enabled": values.get("rotation_enabled") == "1",
        "instance_ids": instance_ids,
        "instance_a": instance_ids[0] if instance_ids else "",
        "instance_b": instance_ids[1] if len(instance_ids) > 1 else "",
        "active_instance_id": values.get("rotation_active_instance_id", ""),
        "switch_time": values.get("rotation_switch_time", DEFAULT_ROTATION_SWITCH_TIME),
        "grace_seconds": grace_seconds,
        "timeout_seconds": timeout_seconds,
        "traffic_protect_gb": traffic_protect_gb,
        "last_switch_date": values.get("rotation_last_switch_date", ""),
        "last_attempt_at": values.get("rotation_last_attempt_at", ""),
        "last_warning_key": values.get("rotation_last_warning_key", ""),
        "breaker_latched": values.get("rotation_breaker_latched", "0") == "1",
        "cloudflare_api_token": values.get("cloudflare_api_token", ""),
        "cloudflare_zone_id": values.get("cloudflare_zone_id", ""),
        "cloudflare_record_name": values.get("cloudflare_record_name", ""),
    }


async def get_instance_context(instance_id: str):
    if not instance_id:
        return None, None
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Instance).where(Instance.instance_id == instance_id))
        instance = result.scalar_one_or_none()
        if not instance:
            return None, None
        result = await db.execute(select(Account).where(Account.id == instance.account_id))
        account = result.scalar_one_or_none()
        return instance, account


def aliyun_client_for(account: Account) -> AliyunClient:
    return AliyunClient(
        account.access_key_id,
        account.access_key_secret,
        account.region_id,
        account.site_type,
    )


async def update_instance_from_aliyun(instance_id: str, client: AliyunClient):
    details = await client.get_instance(instance_id)
    if not details:
        return None
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Instance).where(Instance.instance_id == instance_id))
        instance = result.scalar_one_or_none()
        if instance:
            instance.status = details["status"]
            instance.public_ip = details["public_ip"]
            instance.is_spot = details["is_spot"]
            instance.bandwidth_mbps = details["bandwidth_mbps"]
            instance.last_synced = datetime.utcnow()
            await db.commit()
    return details


async def wait_for_instance_status(
    instance_id: str,
    client: AliyunClient,
    expected_status: str,
    timeout_seconds: int,
    poll_seconds: int = 5,
):
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_status = "Unknown"
    while asyncio.get_running_loop().time() < deadline:
        last_status = await client.get_instance_status(instance_id)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Instance)
                .where(Instance.instance_id == instance_id)
                .values(status=last_status, updated_at=datetime.utcnow())
            )
            await db.commit()
        if last_status == expected_status:
            return True, last_status
        await asyncio.sleep(poll_seconds)
    return False, last_status


async def sync_cloudflare_ddns(public_ip: str, config: dict, reason: str) -> dict:
    token = config.get("cloudflare_api_token", "")
    zone_id = config.get("cloudflare_zone_id", "")
    record_name = config.get("cloudflare_record_name", "")
    if not token or not zone_id or not record_name:
        raise RuntimeError("Cloudflare DDNS 配置不完整")

    client = CloudflareDNSClient(token, zone_id)
    result = await client.update_a_record(record_name, public_ip)
    action = "已更新" if result["changed"] else "无需更新"
    await add_important_log(
        "ddns",
        f"[{reason}] {record_name}: {result['old_ip'] or '—'} -> {result['new_ip']}（{action}）",
    )
    return result


async def _stop_rotation_instances_unlocked(config: dict, reason: str) -> bool:
    results = []
    for instance_id in config["instance_ids"]:
        instance, account = await get_instance_context(instance_id)
        if not instance or not account:
            results.append((instance_id, False, "实例不存在"))
            continue
        client = aliyun_client_for(account)
        try:
            status = await client.get_instance_status(instance_id)
            if status != "Stopped":
                await client.stop_instance(instance_id, "StopCharging")
                ok, status = await wait_for_instance_status(
                    instance_id, client, "Stopped", config["timeout_seconds"]
                )
            else:
                ok = True
            results.append((instance_id, ok, status))
        except Exception as exc:
            results.append((instance_id, False, str(exc)))

    all_stopped = all(item[1] for item in results)
    detail = "\n".join(
        f"  {'✅' if ok else '⚠️'} {escape(instance_id)}: {escape(str(status))}"
        for instance_id, ok, status in results
    )
    await set_setting("rotation_active_instance_id", "")
    await set_setting("rotation_last_switch_date", datetime.now().strftime("%Y-%m-%d"))
    await set_setting("rotation_breaker_latched", "1")
    await send_tg_notify(
        f"🚨 <b>轮换全局熔断</b>\n"
        f"原因: {escape(reason)}\n"
        f"{detail}\n"
        f"结果: {'全部轮换实例均已节省停机' if all_stopped else '存在停机异常，请立即检查'}"
    )
    await add_important_log("rotation", f"全局熔断: {reason}；{results}")
    return all_stopped


async def stop_rotation_instances(config: dict, reason: str) -> bool:
    if rotation_lock.locked():
        return False
    async with rotation_lock:
        return await _stop_rotation_instances_unlocked(config, reason)


async def execute_rotation(target_instance_id: str, reason: str, config: dict | None = None) -> bool:
    if rotation_lock.locked():
        return False
    async with rotation_lock:
        config = config or await get_rotation_config()
        await set_setting("rotation_last_attempt_at", datetime.now().isoformat(timespec="seconds"))
        source_instance_ids = [
            instance_id
            for instance_id in config["instance_ids"]
            if instance_id != target_instance_id
        ]
        target_instance, target_account = await get_instance_context(target_instance_id)
        if not target_instance or not target_account:
            await send_tg_notify(
                f"⚠️ <b>换班失败</b>\n原因: 目标实例不存在\n实例: {escape(target_instance_id)}"
            )
            return False
        if not target_instance.is_spot:
            await send_tg_notify(
                f"⚠️ <b>换班失败</b>\n原因: 目标不是抢占式实例\n实例: {escape(target_instance_id)}"
            )
            return False

        target_client = aliyun_client_for(target_account)
        target_started_by_rotation = False
        ddns_completed = False
        try:
            status = await target_client.get_instance_status(target_instance_id)
            if status != "Running":
                await target_client.start_instance(target_instance_id)
                target_started_by_rotation = True
                running, status = await wait_for_instance_status(
                    target_instance_id,
                    target_client,
                    "Running",
                    config["timeout_seconds"],
                )
                if not running:
                    raise RuntimeError(f"目标实例启动超时，最终状态 {status}")

            details = await update_instance_from_aliyun(target_instance_id, target_client)
            if not details or not details.get("public_ip"):
                raise RuntimeError("目标实例已运行，但未获取到公网 IP")

            ddns = await sync_cloudflare_ddns(details["public_ip"], config, reason)
            ddns_completed = True

            if config["grace_seconds"] > 0:
                await asyncio.sleep(config["grace_seconds"])

            source_results = []
            for source_instance_id in source_instance_ids:
                source_instance, source_account = await get_instance_context(source_instance_id)
                if not source_instance or not source_account:
                    source_results.append((source_instance_id, False, "实例不存在"))
                    continue
                try:
                    source_client = aliyun_client_for(source_account)
                    source_status = await source_client.get_instance_status(source_instance_id)
                    source_stop_ok = True
                    if source_status != "Stopped":
                        await source_client.stop_instance(source_instance_id, "StopCharging")
                        source_stop_ok, source_status = await wait_for_instance_status(
                            source_instance_id,
                            source_client,
                            "Stopped",
                            config["timeout_seconds"],
                        )
                    source_results.append(
                        (source_instance_id, source_stop_ok, source_status)
                    )
                except Exception as source_exc:
                    source_results.append((source_instance_id, False, str(source_exc)))

            await set_setting("rotation_active_instance_id", target_instance_id)
            await set_setting("rotation_last_switch_date", datetime.now().strftime("%Y-%m-%d"))

            display_name = target_instance.remark or target_instance_id
            stop_lines = "\n".join(
                (
                    f"✅ 已节省停机: {escape(instance_id)}"
                    if ok
                    else f"⚠️ 停机未确认: {escape(instance_id)}（{escape(str(status))}）"
                )
                for instance_id, ok, status in source_results
            ) or "ℹ️ 无需停止其他轮换实例"
            await send_tg_notify(
                f"✅ <b>实例换班完成</b>\n"
                f"原因: {escape(reason)}\n"
                f"当前实例: <b>{escape(display_name)}</b>\n"
                f"实例 ID: {escape(target_instance_id)}\n"
                f"公网 IP: {escape(details['public_ip'])}\n"
                f"DDNS: {escape(ddns['record_name'])} → {escape(ddns['new_ip'])}\n"
                f"{stop_lines}"
            )
            await add_important_log(
                "rotation",
                f"换班完成: {target_instance_id} 当班，"
                f"DDNS {ddns['record_name']} -> {ddns['new_ip']}，"
                f"其他轮换实例状态 {source_results}",
            )
            return True
        except Exception as exc:
            rollback_line = "旧实例未主动停止"
            if target_started_by_rotation and not ddns_completed:
                try:
                    await target_client.stop_instance(target_instance_id, "StopCharging")
                    rollback_ok, rollback_status = await wait_for_instance_status(
                        target_instance_id,
                        target_client,
                        "Stopped",
                        config["timeout_seconds"],
                    )
                    rollback_line = (
                        "目标实例已回滚为节省停机"
                        if rollback_ok
                        else f"目标实例回滚未确认（{rollback_status}）"
                    )
                except Exception as rollback_exc:
                    rollback_line = f"目标实例回滚失败（{rollback_exc}）"
            elif ddns_completed:
                rollback_line = "DDNS 已切换，目标实例保持运行，请立即检查旧实例状态"

            await add_log("error", "rotation", f"换班到 {target_instance_id} 失败: {exc}")
            await send_tg_notify(
                f"⚠️ <b>换班失败</b>\n"
                f"原因: {escape(reason)}\n"
                f"目标实例: {escape(target_instance_id)}\n"
                f"错误: {escape(str(exc))}\n"
                f"保护措施: {escape(rollback_line)}"
            )
            return False


async def rotation_check(force_reason: str | None = None) -> bool:
    config = await get_rotation_config()
    if not config["enabled"]:
        return False
    targets = config["instance_ids"]
    if len(targets) < 2 or len(set(targets)) != len(targets):
        return False

    active_id = config["active_instance_id"] or targets[0]
    if active_id not in targets:
        active_id = targets[0]
    active_index = targets.index(active_id)
    candidates = targets[active_index + 1:] + targets[:active_index]

    active_instance, _ = await get_instance_context(active_id)
    candidate_instances = []
    for candidate_id in candidates:
        candidate_instance, _ = await get_instance_context(candidate_id)
        if candidate_instance:
            candidate_instances.append(candidate_instance)
    if not active_instance or len(candidate_instances) != len(candidates):
        return False

    protect = config["traffic_protect_gb"]
    active_over = (active_instance.traffic_used_gb or 0) >= protect
    available_candidates = [
        instance
        for instance in candidate_instances
        if (instance.traffic_used_gb or 0) < protect
    ]
    now = datetime.now()
    retry_cooldown = False
    if config.get("last_attempt_at"):
        try:
            last_attempt = datetime.fromisoformat(config["last_attempt_at"])
            retry_cooldown = (now - last_attempt).total_seconds() < 600
        except ValueError:
            pass

    if active_over:
        if not available_candidates:
            if config.get("breaker_latched"):
                return False
            return await stop_rotation_instances(
                config,
                f"双账号流量均达到保护值 {protect:g}GB",
            )
        if retry_cooldown:
            return False
        return await execute_rotation(
            available_candidates[0].instance_id,
            force_reason or f"当前账号流量达到保护值 {protect:g}GB",
            config,
        )

    if config.get("breaker_latched"):
        await set_setting("rotation_breaker_latched", "0")

    if retry_cooldown:
        return False
    if not config["last_switch_date"]:
        return await execute_rotation(active_id, "启用每日轮换", config)

    due_today = (
        config["last_switch_date"] != now.strftime("%Y-%m-%d")
        and now.strftime("%H:%M") >= config["switch_time"]
    )
    if force_reason or due_today:
        if not available_candidates:
            warning_key = f"{now.strftime('%Y-%m-%d')}:all-backups-over"
            if config.get("last_warning_key") != warning_key:
                await set_setting("rotation_last_warning_key", warning_key)
                await send_tg_notify(
                    f"⚠️ <b>自动换班已跳过</b>\n"
                    f"原因: 其他轮换账号流量均达到保护值\n"
                    f"保护值: {protect:g}GB\n"
                    f"当前实例保持运行，请检查流量配置"
                )
            await add_log(
                "warning",
                "rotation",
                f"计划换班跳过：备用实例账号流量已达到 {protect:g}GB",
            )
            return False
        return await execute_rotation(
            available_candidates[0].instance_id,
            force_reason or "每日自动轮换",
            config,
        )
    return False


async def send_tg_notify(message: str):
    bot_token = await get_setting("tg_bot_token")
    chat_id = await get_setting("tg_chat_id")
    if not bot_token or not chat_id:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            )
    except Exception as e:
        async with AsyncSessionLocal() as db:
            db.add(Log(level="warning", category="notify", message=f"TG通知发送失败: {e}"))
            await db.commit()


async def traffic_check():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Account).where(Account.enabled == True))
        accounts = result.scalars().all()

    rotation_config = await get_rotation_config()
    rotation_due_reason = None
    rotation_target_ids = set(rotation_config["instance_ids"])
    active_rotation_account_id = None
    if rotation_config["enabled"]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Instance).where(Instance.instance_id.in_(rotation_target_ids))
            )
            rotation_instances = result.scalars().all()
        active_rotation_instance = next(
            (
                instance for instance in rotation_instances
                if instance.instance_id == rotation_config["active_instance_id"]
            ),
            None,
        )
        if active_rotation_instance:
            active_rotation_account_id = active_rotation_instance.account_id

    for account in accounts:
        try:
            client = AliyunClient(
                account.access_key_id, account.access_key_secret,
                account.region_id, account.site_type,
            )
            traffic_gb = await client.get_cdt_traffic()
            limit = account.traffic_limit_gb or 200.0
            percent = round(traffic_gb / limit * 100, 2)

            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(Instance)
                    .where(Instance.account_id == account.id)
                    .values(traffic_used_gb=traffic_gb, traffic_percent=percent, last_synced=datetime.utcnow())
                )
                await db.commit()

            trigger_reason = None
            selected_primary_managed = account.instance_id in rotation_target_ids
            rotation_managed = account.id == active_rotation_account_id

            if rotation_managed and traffic_gb >= rotation_config["traffic_protect_gb"]:
                rotation_due_reason = (
                    f"当前账号流量 {traffic_gb:g}GB 达到保护值 "
                    f"{rotation_config['traffic_protect_gb']:g}GB"
                )

            if (
                not selected_primary_managed
                and percent >= account.threshold_percent
                and not account.manual_stopped
            ):
                trigger_reason = f"流量超阈值 {traffic_gb}GB/{percent}%（阈值{account.threshold_percent}%）"

            if not trigger_reason and account.outstanding_threshold and account.outstanding_threshold > 0 and not account.manual_stopped:
                try:
                    bill = await client.get_bill_overview()
                    outstanding = bill.get("total_outstanding", 0)
                    if outstanding >= account.outstanding_threshold:
                        symbol = bill.get("symbol", "$")
                        outstanding_reason = (
                            f"待还金额超阈值 {symbol}{outstanding}"
                            f"（阈值{symbol}{account.outstanding_threshold}）"
                        )
                        if rotation_managed:
                            rotation_due_reason = outstanding_reason
                        elif not selected_primary_managed:
                            trigger_reason = outstanding_reason
                except Exception:
                    pass

            if trigger_reason and account.instance_id:
                async with AsyncSessionLocal() as db:
                    inst_result = await db.execute(
                        select(Instance).where(Instance.instance_id == account.instance_id)
                    )
                    inst = inst_result.scalar_one_or_none()

                if inst and inst.status != "Stopped":
                    await client.stop_instance(account.instance_id, account.shutdown_mode)
                    async with AsyncSessionLocal() as db:
                        await db.execute(
                            update(Account).where(Account.id == account.id).values(manual_stopped=True)
                        )
                        await db.commit()
                    stopped, final_status = await wait_for_instance_status(
                        account.instance_id,
                        client,
                        "Stopped",
                        rotation_config["timeout_seconds"],
                    )
                    if stopped:
                        await send_tg_notify(
                            f"🚨 <b>熔断停机完成</b>\n"
                            f"账户: {escape(account.name)}\n"
                            f"实例: {escape(account.instance_id)}\n"
                            f"原因: {escape(trigger_reason)}\n"
                            f"状态: Stopped（已核实）\n"
                            f"模式: {escape(account.shutdown_mode)}"
                        )
                        await add_important_log(
                            "traffic",
                            f"[{account.name}] 熔断: {trigger_reason}，已确认进入 Stopped",
                        )
                    else:
                        message = f"熔断停机未确认，最终状态 {final_status}"
                        await add_log("error", "traffic", f"[{account.name}] {message}")
                        await send_tg_notify(
                            f"⚠️ <b>熔断停机异常</b>\n"
                            f"账户: {escape(account.name)}\n"
                            f"实例: {escape(account.instance_id)}\n"
                            f"错误: {escape(message)}"
                        )

        except Exception:
            pass

    if rotation_due_reason:
        await rotation_check(force_reason=rotation_due_reason)


async def keep_alive_check():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Account).where(Account.enabled == True, Account.keep_alive == True)
        )
        accounts = result.scalars().all()

    rotation_config = await get_rotation_config()
    rotation_targets = (
        set(rotation_config["instance_ids"])
        if rotation_config["enabled"]
        else set()
    )

    checks = []
    for account in accounts:
        if not account.instance_id:
            continue
        if account.instance_id in rotation_targets:
            continue
        checks.append((account, account.instance_id, False))

    if rotation_config["enabled"] and rotation_config["active_instance_id"]:
        active_instance, active_account = await get_instance_context(
            rotation_config["active_instance_id"]
        )
        if active_instance and active_account:
            checks.append((active_account, active_instance.instance_id, True))

    seen_instance_ids = set()
    for account, instance_id, rotation_managed in checks:
        if instance_id in seen_instance_ids:
            continue
        seen_instance_ids.add(instance_id)
        if account.manual_stopped and not rotation_managed:
            continue
        try:
            client = aliyun_client_for(account)
            status = await client.get_instance_status(instance_id)

            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(Instance)
                    .where(Instance.instance_id == instance_id)
                    .values(status=status, updated_at=datetime.utcnow())
                )
                await db.commit()

            if status == "Stopped":
                await client.start_instance(instance_id)
                running, final_status = await wait_for_instance_status(
                    instance_id,
                    client,
                    "Running",
                    rotation_config["timeout_seconds"],
                )
                if not running:
                    raise RuntimeError(f"启动超时，最终状态 {final_status}")

                details = await update_instance_from_aliyun(instance_id, client)
                if not details or not details.get("public_ip"):
                    raise RuntimeError("实例已运行，但未获取到公网 IP")

                ddns_line = "DDNS: 未配置，已跳过"
                if rotation_managed:
                    ddns = await sync_cloudflare_ddns(
                        details["public_ip"],
                        rotation_config,
                        "抢占恢复",
                    )
                    ddns_line = f"DDNS: {ddns['record_name']} → {ddns['new_ip']}"

                await send_tg_notify(
                    f"🟢 <b>抢占恢复完成</b>\n"
                    f"账户: {escape(account.name)}\n"
                    f"实例: {escape(instance_id)}\n"
                    f"状态: Running（已核实）\n"
                    f"公网 IP: {escape(details['public_ip'])}\n"
                    f"{escape(ddns_line)}"
                )
                await add_important_log(
                    "keepalive",
                    f"[{account.name}] 实例 {instance_id} 已确认恢复 Running，"
                    f"公网 IP {details['public_ip']}，{ddns_line}",
                )
            elif status == "Unknown":
                await add_log(
                    "warning",
                    "keepalive",
                    f"[{account.name}] 实例 {instance_id} 状态 Unknown，可能已被释放，无法直接重新启动",
                )

        except Exception as exc:
            await add_log("error", "keepalive", f"[{account.name}] 保活恢复失败: {exc}")
            await send_tg_notify(
                f"⚠️ <b>保活恢复失败</b>\n"
                f"账户: {escape(account.name)}\n"
                f"实例: {escape(instance_id)}\n"
                f"错误: {escape(str(exc))}"
            )


async def scheduled_power():
    now = datetime.now().strftime("%H:%M")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Account).where(Account.enabled == True))
        accounts = result.scalars().all()
    rotation_config = await get_rotation_config()
    rotation_targets = (
        set(rotation_config["instance_ids"])
        if rotation_config["enabled"]
        else set()
    )

    for account in accounts:
        if not account.instance_id:
            continue
        if account.instance_id in rotation_targets:
            continue
        client = AliyunClient(
            account.access_key_id, account.access_key_secret,
            account.region_id, account.site_type,
        )
        try:
            if account.auto_stop_time and account.auto_stop_time == now:
                await client.stop_instance(account.instance_id, account.shutdown_mode)
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(Account).where(Account.id == account.id).values(manual_stopped=True)
                    )
                    await db.commit()
                stopped, final_status = await wait_for_instance_status(
                    account.instance_id,
                    client,
                    "Stopped",
                    rotation_config["timeout_seconds"],
                )
                if not stopped:
                    raise RuntimeError(f"定时关机未确认，最终状态 {final_status}")
                await add_important_log("scheduler", f"[{account.name}] 定时关机已确认 {now}")
                await send_tg_notify(
                    f"⏰ <b>定时关机完成</b>\n"
                    f"账户: {escape(account.name)}\n"
                    f"实例: {escape(account.instance_id)}\n"
                    f"状态: Stopped（已核实）\n"
                    f"时间: {now}"
                )

            if account.auto_start_time and account.auto_start_time == now:
                await client.start_instance(account.instance_id)
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(Account).where(Account.id == account.id).values(manual_stopped=False)
                    )
                    await db.commit()
                running, final_status = await wait_for_instance_status(
                    account.instance_id,
                    client,
                    "Running",
                    rotation_config["timeout_seconds"],
                )
                if not running:
                    raise RuntimeError(f"定时开机未确认，最终状态 {final_status}")
                await add_important_log("scheduler", f"[{account.name}] 定时开机已确认 {now}")
                await send_tg_notify(
                    f"⏰ <b>定时开机完成</b>\n"
                    f"账户: {escape(account.name)}\n"
                    f"实例: {escape(account.instance_id)}\n"
                    f"状态: Running（已核实）\n"
                    f"时间: {now}"
                )

        except Exception as e:
            async with AsyncSessionLocal() as db:
                db.add(Log(level="error", category="scheduler", message=f"[{account.name}] 定时任务失败: {e}"))
                await db.commit()
            await send_tg_notify(
                f"⚠️ <b>定时任务异常</b>\n"
                f"账户: {escape(account.name)}\n"
                f"实例: {escape(account.instance_id)}\n"
                f"错误: {escape(str(e))}"
            )


async def sync_instances():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Account).where(Account.enabled == True))
        accounts = result.scalars().all()

    for account in accounts:
        try:
            client = AliyunClient(
                account.access_key_id, account.access_key_secret,
                account.region_id, account.site_type,
            )
            instances = await client.get_instances()
            async with AsyncSessionLocal() as db:
                for inst in instances:
                    result = await db.execute(
                        select(Instance).where(Instance.instance_id == inst["instance_id"])
                    )
                    existing = result.scalar_one_or_none()
                    if existing:
                        existing.status = inst["status"]
                        existing.public_ip = inst["public_ip"]
                        existing.is_spot = inst["is_spot"]
                        existing.bandwidth_mbps = inst["bandwidth_mbps"]
                        existing.last_synced = datetime.utcnow()
                    else:
                        new_inst = Instance(account_id=account.id, **inst)
                        db.add(new_inst)
                await db.commit()
        except Exception:
            pass


async def monthly_reset():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Account).where(Account.enabled == True))
        accounts = result.scalars().all()

    rotation_config = await get_rotation_config()
    rotation_targets = (
        set(rotation_config["instance_ids"])
        if rotation_config["enabled"]
        else set()
    )
    if rotation_config["enabled"] and rotation_config["instance_ids"]:
        await set_setting("rotation_breaker_latched", "0")
        await execute_rotation(
            rotation_config["instance_ids"][0],
            "月度流量重置",
            rotation_config,
        )

    restarted = []
    for account in accounts:
        if account.instance_id in rotation_targets:
            continue
        if not account.manual_stopped:
            continue
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(Account).where(Account.id == account.id).values(manual_stopped=False)
                )
                await db.commit()

            if account.instance_id:
                client = AliyunClient(
                    account.access_key_id, account.access_key_secret,
                    account.region_id, account.site_type,
                )
                await client.start_instance(account.instance_id)
                restarted.append(account.name)

        except Exception:
            pass

    if restarted:
        await send_tg_notify(
            f"🔄 <b>每月流量重置</b>\n"
            f"新的一个月开始，以下账户已自动恢复并启动：\n"
            + "\n".join(f"  • {name}" for name in restarted)
        )
        await add_important_log("system", f"每月重置，已恢复并启动: {', '.join(restarted)}")


async def _do_daily_report():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Account).where(Account.enabled == True))
        accounts = result.scalars().all()
        result2 = await db.execute(select(Instance))
        instances = result2.scalars().all()
    rotation_config = await get_rotation_config()
    rotation_targets = (
        set(rotation_config["instance_ids"])
        if rotation_config["enabled"]
        else set()
    )

    instances_by_account = {}
    for inst in instances:
        instances_by_account.setdefault(inst.account_id, []).append(inst)
    for account_instances in instances_by_account.values():
        account_instances.sort(key=lambda item: (item.id or 0, item.instance_id))

    enabled_account_ids = {account.id for account in accounts}
    instance_count = sum(
        len(account_instances)
        for account_id, account_instances in instances_by_account.items()
        if account_id in enabled_account_ids
    )

    lines = [
        "📊 <b>每日流量汇报</b>",
        f"🕛 {datetime.now().strftime('%Y-%m-%d %H:%M')} 北京时间",
        f"🖥 共 {instance_count} 台实例",
        "━━━━━━━━━━━━━━━━",
    ]

    for account in accounts:
        account_instances = instances_by_account.get(account.id, [])
        billing_line = "💰 账单获取失败"
        try:
            client = AliyunClient(
                account.access_key_id, account.access_key_secret,
                account.region_id, account.site_type,
            )
            balance = await client.get_balance()
            bill = await client.get_bill_overview()
            symbol = balance.get("symbol", "$") if balance else "$"
            avail = balance.get("available_amount", 0) if balance else 0
            outst = bill.get("total_outstanding", 0) if bill else 0
            billing_line = f"💰 余额: {symbol}{avail}  待还: {symbol}{outst}"
        except Exception:
            pass

        if not account_instances:
            lines.append(f"⚪ <b>{escape(account.name)}</b>\n  暂无实例数据")
            lines.append("━━━━━━━━━━━━━━━━")
            continue

        for inst in account_instances:
            status_icon = "🟢" if inst.status == "Running" else "🔴"
            bar = build_traffic_bar(inst.traffic_percent, account.threshold_percent)
            display_name = escape(inst.remark or inst.instance_id)
            instance_id_line = f"  🆔 实例 ID: {escape(inst.instance_id)}\n" if inst.remark else ""
            instance_kind = "抢占式实例" if inst.is_spot else "普通实例"
            rotation_line = ""
            if inst.instance_id in rotation_targets:
                rotation_role = (
                    "🟢 当前当班"
                    if inst.instance_id == rotation_config["active_instance_id"]
                    else "⚪ 轮换待机"
                )
                rotation_line = f"  🔁 轮换: {rotation_role}\n"
            block = (
                f"{status_icon} <b>{display_name}</b>\n"
                f"{instance_id_line}"
                f"  🌐 公网 IP: {escape(inst.public_ip or '—')}\n"
                f"  🧩 类型: {instance_kind}\n"
                f"{rotation_line}"
                f"  🖥 状态: {inst.status}  地域: {escape(inst.region_id or '—')}\n"
                f"  📡 账户流量: {inst.traffic_used_gb:.2f}GB / {account.traffic_limit_gb}GB\n"
                f"  {bar}  {inst.traffic_percent:.1f}%\n"
                f"  🛡 熔断阈值: {account.threshold_percent}%\n"
                f"  {billing_line}"
            )
            lines.append(block)
            lines.append("━━━━━━━━━━━━━━━━")

    await send_tg_notify("\n".join(lines))
    await add_important_log("system", "每日流量汇报已发送")


async def daily_traffic_report():
    enabled = await get_setting("tg_daily_report", "0")
    if enabled != "1":
        return
    await _do_daily_report()


async def configure_keep_alive_job(interval_minutes=None):
    if interval_minutes is None:
        configured_value = await get_setting(
            "keep_alive_interval_minutes",
            str(DEFAULT_KEEP_ALIVE_INTERVAL_MINUTES),
        )
        interval_minutes = parse_keep_alive_interval(configured_value)
    else:
        interval_minutes = parse_keep_alive_interval(interval_minutes)

    scheduler.add_job(
        keep_alive_check,
        IntervalTrigger(minutes=interval_minutes),
        id="keep_alive",
        replace_existing=True,
    )
    return interval_minutes


async def start_scheduler():
    scheduler.add_job(traffic_check, IntervalTrigger(minutes=10), id="traffic_check", replace_existing=True)
    await configure_keep_alive_job()
    scheduler.add_job(scheduled_power, IntervalTrigger(minutes=1), id="scheduled_power", replace_existing=True)
    scheduler.add_job(sync_instances, IntervalTrigger(minutes=2), id="sync_instances", replace_existing=True)
    scheduler.add_job(rotation_check, IntervalTrigger(minutes=1), id="rotation_check", replace_existing=True)
    scheduler.add_job(daily_traffic_report, CronTrigger(hour=0, minute=0), id="daily_report", replace_existing=True)
    scheduler.add_job(monthly_reset, CronTrigger(day=1, hour=0, minute=1), id="monthly_reset", replace_existing=True)
    scheduler.start()
