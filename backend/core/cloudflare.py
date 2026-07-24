from ipaddress import ip_address

import httpx


class CloudflareError(Exception):
    pass


class CloudflareDNSClient:
    API_BASE = "https://api.cloudflare.com/client/v4"

    def __init__(
        self,
        api_token: str = "",
        zone_id: str = "",
        timeout: float = 15.0,
        auth_email: str = "",
        auth_key: str = "",
        zone_name: str = "",
    ):
        self.api_token = api_token.strip()
        self.zone_id = zone_id.strip()
        self.auth_email = auth_email.strip()
        self.auth_key = auth_key.strip()
        self.zone_name = zone_name.strip().rstrip(".").lower()
        self.timeout = timeout

    @property
    def headers(self) -> dict:
        if self.api_token:
            return {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            }
        if self.auth_email and self.auth_key:
            return {
                "X-Auth-Email": self.auth_email,
                "X-Auth-Key": self.auth_key,
                "Content-Type": "application/json",
            }
        raise CloudflareError("Cloudflare 认证信息不完整")

    @staticmethod
    def _check_response(data: dict):
        if data.get("success"):
            return
        errors = data.get("errors") or []
        message = "; ".join(str(item.get("message", item)) for item in errors)
        raise CloudflareError(message or "Cloudflare API 返回失败")

    async def resolve_zone_id(self) -> str:
        if self.zone_id:
            return self.zone_id
        if not self.zone_name:
            raise CloudflareError("未配置 Zone ID 或 Zone 名称")

        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            response = await client.get(
                f"{self.API_BASE}/zones",
                params={"name": self.zone_name, "per_page": 50},
            )
            response.raise_for_status()
            data = response.json()
            self._check_response(data)

        zones = [
            item for item in data.get("result", [])
            if str(item.get("name", "")).rstrip(".").lower() == self.zone_name
        ]
        if not zones:
            raise CloudflareError(f"未找到 Zone: {self.zone_name}")
        if len(zones) > 1:
            raise CloudflareError(f"找到多个同名 Zone，无法自动确定: {self.zone_name}")
        self.zone_id = zones[0].get("id", "")
        if not self.zone_id:
            raise CloudflareError(f"Zone 缺少 ID: {self.zone_name}")
        return self.zone_id

    def qualify_record_name(self, record_name: str) -> str:
        record_name = record_name.strip().rstrip(".").lower()
        if not record_name:
            raise CloudflareError("DNS 记录名称不能为空")
        if not self.zone_name:
            return record_name
        if record_name == "@":
            return self.zone_name
        if record_name == self.zone_name or record_name.endswith(f".{self.zone_name}"):
            return record_name
        return f"{record_name}.{self.zone_name}"

    async def get_a_record(self, record_name: str) -> dict:
        zone_id = await self.resolve_zone_id()
        record_name = self.qualify_record_name(record_name)
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            response = await client.get(
                f"{self.API_BASE}/zones/{zone_id}/dns_records",
                params={"type": "A", "name": record_name, "per_page": 100},
            )
            response.raise_for_status()
            data = response.json()
            self._check_response(data)

        records = [
            item for item in data.get("result", [])
            if item.get("type") == "A" and item.get("name", "").rstrip(".") == record_name
        ]
        if not records:
            raise CloudflareError(f"未找到 A 记录: {record_name}")
        if len(records) > 1:
            raise CloudflareError(f"找到多个同名 A 记录，请先在 Cloudflare 中清理: {record_name}")
        return records[0]

    async def update_a_record(self, record_name: str, public_ip: str) -> dict:
        record_name = self.qualify_record_name(record_name)
        try:
            parsed_ip = ip_address(public_ip)
        except ValueError as exc:
            raise CloudflareError(f"无效公网 IP: {public_ip}") from exc
        if parsed_ip.version != 4:
            raise CloudflareError("当前仅支持更新 Cloudflare A 记录")

        record = await self.get_a_record(record_name)
        old_ip = record.get("content", "")
        if old_ip == str(parsed_ip):
            return {
                "changed": False,
                "record_id": record.get("id"),
                "record_name": record_name,
                "old_ip": old_ip,
                "new_ip": str(parsed_ip),
                "proxied": bool(record.get("proxied")),
            }

        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            response = await client.patch(
                f"{self.API_BASE}/zones/{self.zone_id}/dns_records/{record['id']}",
                json={"content": str(parsed_ip)},
            )
            response.raise_for_status()
            updated = response.json()
            self._check_response(updated)
            result = updated.get("result") or {}
            return {
                "changed": True,
                "record_id": result.get("id", record.get("id")),
                "record_name": result.get("name", record_name),
                "old_ip": old_ip,
                "new_ip": result.get("content", str(parsed_ip)),
                "proxied": bool(result.get("proxied", record.get("proxied"))),
            }
