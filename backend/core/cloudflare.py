from ipaddress import ip_address

import httpx


class CloudflareError(Exception):
    pass


class CloudflareDNSClient:
    API_BASE = "https://api.cloudflare.com/client/v4"

    def __init__(self, api_token: str, zone_id: str, timeout: float = 15.0):
        self.api_token = api_token.strip()
        self.zone_id = zone_id.strip()
        self.timeout = timeout

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _check_response(data: dict):
        if data.get("success"):
            return
        errors = data.get("errors") or []
        message = "; ".join(str(item.get("message", item)) for item in errors)
        raise CloudflareError(message or "Cloudflare API 返回失败")

    async def get_a_record(self, record_name: str) -> dict:
        record_name = record_name.strip().rstrip(".")
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            response = await client.get(
                f"{self.API_BASE}/zones/{self.zone_id}/dns_records",
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
        record_name = record_name.strip().rstrip(".")
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
