from typing import Optional

import aiohttp


class LinkedInClient:
    AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    API_BASE = "https://api.linkedin.com"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_auth_url(self) -> str:
        params = (
            f"?response_type=code"
            f"&client_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&scope=w_member_social"
        )
        return f"{self.AUTH_URL}{params}"

    async def exchange_code(self, code: str) -> tuple[str, str]:
        """Exchange auth code for access_token and person URN. Returns (access_token, person_urn)."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.TOKEN_URL, data=data) as resp:
                resp.raise_for_status()
                token_data = await resp.json()
                access_token = token_data["access_token"]

            headers = {"Authorization": f"Bearer {access_token}"}
            async with session.get(f"{self.API_BASE}/v2/me", headers=headers) as resp:
                resp.raise_for_status()
                me_data = await resp.json()
                person_id = me_data["id"]
                person_urn = f"urn:li:person:{person_id}"

            return access_token, person_urn

    async def register_image_upload(self, access_token: str, person_urn: str) -> tuple[str, str]:
        """Register an image for upload. Returns (upload_url, asset_urn)."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": person_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.API_BASE}/v2/assets?action=registerUpload",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                upload_url = data["value"]["uploadMechanism"][
                    "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
                ]["uploadUrl"]
                asset_urn = data["value"]["asset"]
                return upload_url, asset_urn

    async def upload_image(self, upload_url: str, access_token: str, image_bytes: bytes) -> None:
        """Upload image binary to LinkedIn."""
        headers = {"Authorization": f"Bearer {access_token}"}
        async with aiohttp.ClientSession() as session:
            async with session.put(upload_url, headers=headers, data=image_bytes) as resp:
                resp.raise_for_status()

    async def upload_image_full(self, access_token: str, person_urn: str, image_bytes: bytes) -> str:
        """Full image upload pipeline. Returns asset URN."""
        upload_url, asset_urn = await self.register_image_upload(access_token, person_urn)
        await self.upload_image(upload_url, access_token, image_bytes)
        return asset_urn

    async def create_post(
        self,
        access_token: str,
        person_urn: str,
        text: str,
        image_asset_urns: Optional[list[str]] = None,
    ) -> dict:
        """Create a LinkedIn UGC post with optional images."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        media = []
        if image_asset_urns:
            for asset_urn in image_asset_urns:
                media.append(
                    {
                        "status": "READY",
                        "media": asset_urn,
                    }
                )

        share_media_category = "IMAGE" if image_asset_urns else "NONE"

        payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": share_media_category,
                    "media": media,
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.API_BASE}/v2/ugcPosts",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
