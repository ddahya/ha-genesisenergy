# custom_components/genesisenergy/api.py

import aiohttp
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
import json
from urllib.parse import parse_qs
import socket
import asyncio
import base64
import hashlib
import os

from homeassistant.util import dt as dt_util
from .exceptions import CannotConnect, InvalidAuth

_LOGGER = logging.getLogger(__name__)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

def _generate_pkce() -> tuple[str, str]:
    """Generates a secure PKCE code verifier and code challenge."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8").rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest()).decode("utf-8").rstrip("=")
    return verifier, challenge


class GenesisEnergyApi:
    """API client with Azure AD B2C PKCE & persistent 90-day token support."""
    TOKEN_VALIDITY_BUFFER_MINUTES = 5

    def __init__(self, email: str, password: str, refresh_token: str | None = None, token_update_callback=None) -> None:
        self._client_id = "8e41676f-7601-4490-9786-85d74f387f47"
        self._redirect_uri = 'https://myaccount.genesisenergy.co.nz/auth/redirect'
        self._url_token_base = "https://auth.genesisenergy.co.nz/auth.genesisenergy.co.nz"
        self._url_data_base = "https://web-api.genesisenergy.co.nz/"
        self._p = "B2C_1A_signin"
        self._email = email
        self._password = password
        self._token: str | None = None
        self._refresh_token: str | None = refresh_token
        self._access_token_absolute_expiry_ts: float = 0.0
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()
        self._token_update_callback = token_update_callback
        self._code_verifier: str | None = None

        self._mfa_context: dict[str, Any] = {}

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            _LOGGER.debug("Creating new long-lived API session with IPv4-only connector.")
            connector = aiohttp.TCPConnector(family=socket.AF_INET)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            _LOGGER.debug("Managed API session closed.")
            self._session = None
    
    def _get_setting_json(self, page: str) -> Mapping[str, Any] | None:
        for line in page.splitlines():
            if line.strip().startswith("var SETTINGS = ") and line.strip().endswith(";"):
                json_string = line.strip().removeprefix("var SETTINGS = ").removesuffix(";")
                try: return json.loads(json_string)
                except json.JSONDecodeError as e: _LOGGER.error(f"JSONDecodeError: {e}"); return None
        return None

    async def async_start_login(self) -> str:
        """Authenticates with PKCE. Returns 'SUCCESS' or 'MFA_REQUIRED'."""
        _LOGGER.info("Starting PKCE login flow...")
        self._code_verifier, code_challenge = _generate_pkce()

        cookie_jar = aiohttp.CookieJar(quote_cookie=False)
        session = aiohttp.ClientSession(cookie_jar=cookie_jar)
        base_headers = {"User-Agent": BROWSER_USER_AGENT}

        try:
            # 1. Authorize Page with PKCE
            url_s1 = f"{self._url_token_base}/oauth2/v2.0/authorize"
            params_s1 = {
                "p": self._p,
                "client_id": self._client_id,
                "response_type": "code",
                "response_mode": "query",
                "scope": f"openid offline_access {self._client_id}",
                "redirect_uri": self._redirect_uri,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "deviceId": "null",
                "platform": "Web"
            }
            async with session.get(url_s1, params=params_s1, headers=base_headers) as r1:
                txt_s1 = await r1.text()
                r1.raise_for_status()

            sjson1 = self._get_setting_json(txt_s1)
            if not sjson1: raise CannotConnect("Login S1: no settings_json")
            tid, csrf = sjson1.get("transId"), sjson1.get("csrf")
            if not tid or not csrf: raise CannotConnect("Login S1: no tid/csrf")

            # 2. Post Email
            url_s2 = f"{self._url_token_base}/{self._p}/SelfAsserted?tx={tid}&p={self._p}"
            h2 = {**base_headers, 'X-CSRF-TOKEN': csrf, 'X-Requested-With': 'XMLHttpRequest'}
            async with session.post(url_s2, headers=h2, data={"request_type": "RESPONSE", "email": self._email}) as r2:
                r2.raise_for_status()

            # 3. Confirm Email
            url_s3 = f"{self._url_token_base}/{self._p}/api/SelfAsserted/confirmed"
            async with session.get(url_s3, params={'csrf_token': csrf, 'tx': tid, 'p': self._p}, headers={**base_headers, 'Referer': url_s2}) as r3:
                r3.raise_for_status()
                for cookie in session.cookie_jar:
                    if cookie.key == "x-ms-cpim-csrf":
                        csrf = cookie.value

            # 4. Post Password
            url_s4 = f"{self._url_token_base}/{self._p}/SelfAsserted?tx={tid}&p={self._p}"
            h4 = {**base_headers, 'X-CSRF-TOKEN': csrf, 'X-Requested-With': 'XMLHttpRequest'}
            async with session.post(url_s4, headers=h4, data={"request_type": "RESPONSE", "signInName": self._email, "password": self._password}) as r4:
                if r4.status != 200:
                    s4_text = await r4.text()
                    if "invalid" in s4_text.lower(): raise InvalidAuth("Invalid username or password.")
                    r4.raise_for_status()

            # 5. CombinedSigninAndSignup
            url_s5 = f"{self._url_token_base}/{self._p}/api/CombinedSigninAndSignup/confirmed"
            async with session.get(url_s5, params={'rememberMe': 'false', 'csrf_token': csrf, 'tx': tid, 'p': self._p}, headers=base_headers, allow_redirects=False) as r5:
                loc = r5.headers.get('Location', '')
                txt_s5 = await r5.text()

                sjson5 = self._get_setting_json(txt_s5)
                if sjson5 and sjson5.get("csrf"): csrf = sjson5["csrf"]
                if sjson5 and sjson5.get("transId"): tid = sjson5["transId"]
                for cookie in session.cookie_jar:
                    if cookie.key == "x-ms-cpim-csrf": csrf = cookie.value

            # Direct Success with PKCE
            if "code=" in loc:
                auth_code = parse_qs(loc.split('?', 1)[1])['code'][0]
                await session.close()
                await self._exchange_code_for_tokens(auth_code)
                return "SUCCESS"

            # Step 14 confirmation if MFA requested
            url_step14 = f"{self._url_token_base}/{self._p}/api/SelfAsserted/confirmed"
            async with session.get(url_step14, params={"csrf_token": csrf, "tx": tid, "p": self._p}, headers={**base_headers, "Referer": url_s4}) as r14:
                txt_14 = await r14.text()
                sjson14 = self._get_setting_json(txt_14)
                if sjson14 and sjson14.get("csrf"): csrf = sjson14["csrf"]
                if sjson14 and sjson14.get("transId"): tid = sjson14["transId"]
                for cookie in session.cookie_jar:
                    if cookie.key == "x-ms-cpim-csrf": csrf = cookie.value

            self._mfa_context = {
                "tid": tid,
                "csrf": csrf,
                "session": session,
                "url_step14": url_step14,
                "url_s5": url_s5,
            }
            return "MFA_REQUIRED"

        except (InvalidAuth, CannotConnect):
            await session.close()
            raise
        except Exception as e:
            await session.close()
            _LOGGER.error("Error during PKCE login initiation: %s", e)
            raise CannotConnect(f"Login error: {e}") from e

    async def async_submit_mfa_code(self, verification_code: str) -> bool:
        """Submits 6-digit email code and exchanges for 90-day tokens."""
        if not self._mfa_context:
            raise CannotConnect("MFA session expired. Please start over.")

        tid = self._mfa_context["tid"]
        csrf = self._mfa_context["csrf"]
        session: aiohttp.ClientSession = self._mfa_context["session"]
        url_step14 = self._mfa_context["url_step14"]
        url_s5 = self._mfa_context["url_s5"]

        h_send = {
            "User-Agent": BROWSER_USER_AGENT,
            "X-CSRF-TOKEN": csrf,
            "Origin": "https://auth.genesisenergy.co.nz",
            "Referer": f"{url_step14}?csrf_token={csrf}&tx={tid}&p={self._p}",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01"
        }

        try:
            url_verify = f"{self._url_token_base}/{self._p}/SelfAsserted/DisplayControlAction/vbeta/emailVerificationControl/VerifyCode?tx={tid}&p={self._p}"
            async with session.post(url_verify, headers=h_send, data={"readOnlyEmail": self._email, "verificationCode": verification_code}) as r_ver:
                ver_text = await r_ver.text()
                if r_ver.status != 200 or '"status":"200"' not in ver_text:
                    raise InvalidAuth("Invalid verification code.")

            url_form = f"{self._url_token_base}/{self._p}/SelfAsserted?tx={tid}&p={self._p}"
            async with session.post(url_form, headers=h_send, data={"readOnlyEmail": self._email, "verificationCode": verification_code, "request_type": "RESPONSE"}) as r_form:
                if r_form.status != 200:
                    raise CannotConnect("MFA form confirmation failed.")

            async with session.get(url_s5, params={"rememberMe": "false", "csrf_token": csrf, "tx": tid, "p": self._p}, headers={"User-Agent": BROWSER_USER_AGENT}, allow_redirects=False) as r_final:
                final_loc = r_final.headers.get("Location", "")

            if "code=" not in final_loc:
                raise CannotConnect("Failed to parse code from redirect.")

            auth_code = parse_qs(final_loc.split("?", 1)[1])["code"][0]
            await self._exchange_code_for_tokens(auth_code)
            return True

        finally:
            await session.close()
            self._mfa_context = {}

    async def _exchange_code_for_tokens(self, auth_code: str) -> None:
        """Exchanges auth code for access & 90-day refresh tokens with PKCE verifier."""
        url_token = f"{self._url_token_base}/{self._p}/oauth2/v2.0/token"
        payload = {
            "p": self._p,
            "grant_type": "authorization_code",
            "client_id": self._client_id,
            "scope": f"openid offline_access {self._client_id}",
            "redirect_uri": self._redirect_uri,
            "code": auth_code,
        }
        if self._code_verifier:
            payload["code_verifier"] = self._code_verifier

        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(url_token, data=payload, headers={"User-Agent": BROWSER_USER_AGENT}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._token = data.get("access_token")
                    self._refresh_token = data.get("refresh_token")
                    expires_in = data.get("expires_in", 3600)
                    now_ts = datetime.now(timezone.utc).timestamp()
                    self._access_token_absolute_expiry_ts = now_ts + int(expires_in)

                    _LOGGER.info("Tokens captured! Refresh token valid for 90 days. ✅")
                    if self._token_update_callback and self._refresh_token:
                        self._token_update_callback(self._refresh_token)
                else:
                    _LOGGER.error("Token exchange failed with status %s: %s", resp.status, await resp.text())
                    raise CannotConnect("Token exchange failed.")

    async def _refresh_access_token(self) -> bool:
        """Refreshes the access token using the stored 90-day refresh token."""
        if not self._refresh_token:
            return False

        _LOGGER.debug("Refreshing access token via 90-day refresh token...")
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector) as session:
            payload = {
                "grant_type": "refresh_token",
                "client_id": self._client_id,
                "scope": f"openid offline_access {self._client_id}",
                "redirect_uri": self._redirect_uri,
                "refresh_token": self._refresh_token,
            }
            url = f"{self._url_token_base}/oauth2/v2.0/token?p={self._p}"
            try:
                async with session.post(url, data=payload, headers={"User-Agent": BROWSER_USER_AGENT}) as response:
                    if response.status == 200:
                        data = await response.json()
                        self._token = data.get("access_token")
                        new_expires_in = data.get("expires_in", 3600)
                        now_ts = datetime.now(timezone.utc).timestamp()
                        self._access_token_absolute_expiry_ts = now_ts + int(new_expires_in)
                        new_rt = data.get("refresh_token")
                        if new_rt and new_rt != self._refresh_token:
                            self._refresh_token = new_rt
                            if self._token_update_callback:
                                self._token_update_callback(self._refresh_token)
                        _LOGGER.debug("Access token renewed successfully in background. ✅")
                        return True
                    return False
            except Exception as e:
                _LOGGER.debug("Token refresh network issue: %s", e)
                return False

    async def _ensure_valid_token(self) -> None:
        """Ensures access token is valid, refreshing via 90-day refresh token."""
        current_time = datetime.now(timezone.utc).timestamp()
        if self._token and self._access_token_absolute_expiry_ts > (current_time + self.TOKEN_VALIDITY_BUFFER_MINUTES * 60):
            return

        async with self._lock:
            if self._token and self._access_token_absolute_expiry_ts > (datetime.now(timezone.utc).timestamp() + self.TOKEN_VALIDITY_BUFFER_MINUTES * 60):
                return

            if self._refresh_token:
                if await self._refresh_access_token():
                    return

            res = await self.async_start_login()
            if res != "SUCCESS":
                raise InvalidAuth("Login re-authentication required.")

    async def _make_api_call(self, method: str, endpoint: str, params: dict | None = None, json_payload: dict | None = None, description: str = "data", expect_json: bool = True) -> Any:
        await self._ensure_valid_token()
        session = await self._get_session()
        headers = {"authorization": "Bearer " + str(self._token), "brand-id": "GENE"}
        if method.upper() == "POST" and json_payload is not None: headers["Content-Type"] = "application/json"
        
        url = f"{self._url_data_base}{endpoint}"
        try:
            async with session.request(method, url, headers=headers, params=params, json=json_payload) as response:
                if 200 <= response.status < 300:
                    if response.status == 204: return True
                    if expect_json:
                        text = await response.text()
                        return json.loads(text) if text else {}
                    return {"status": response.status, "text": await response.text()}
                elif response.status == 401:
                    self._token = None
                    self._access_token_absolute_expiry_ts = 0
                    raise InvalidAuth(f"Unauthorized (401) for {description}")
                else:
                    raise CannotConnect(f"API error for {description}: {response.status} - {await response.text()}")
        except aiohttp.ClientError as e: raise CannotConnect(f"HTTP client error for {description}: {e}") from e
        except json.JSONDecodeError as e: raise CannotConnect(f"Invalid JSON from {description}: {e}") from e

    async def get_energy_data(self, days_to_fetch: int = 4):
        now_local = dt_util.now()
        from_date = (now_local - timedelta(days=days_to_fetch)).strftime("%Y-%m-%d")
        to_date = now_local.strftime("%Y-%m-%d")
        payload = {'startDate': from_date, 'endDate': to_date, 'intervalType': "HOURLY"}
        return await self._make_api_call("POST", "/v2/private/electricity/site-usage", json_payload=payload, description="electricity usage")
        
    async def get_ev_plan_usage(self): return await self._make_api_call("GET", "/v2/private/evPlan/electricityUsage", description="EV plan usage")
    async def get_gas_data(self, days_to_fetch: int = 4):
        now_local = dt_util.now()
        from_date = (now_local - timedelta(days=days_to_fetch)).strftime("%Y-%m-%d")
        to_date = now_local.strftime("%Y-%m-%d")
        params = {'startDate': from_date, 'endDate': to_date, 'intervalType': "HOURLY"}
        return await self._make_api_call("GET", "/v2/private/naturalgas/advanced/usage", params=params, description="gas usage")
    async def get_electricity_forecast(self): return await self._make_api_call("GET", "/v2/private/electricityForecast", description="electricity forecast")
    async def get_energy_data_for_period(self, start_date_str: str, end_date_str: str):
        payload = {'startDate': start_date_str, 'endDate': end_date_str, 'intervalType': "HOURLY"}
        return await self._make_api_call("POST", "/v2/private/electricity/site-usage", json_payload=payload, description=f"electricity usage for {start_date_str}-{end_date_str}")
    async def get_gas_data_for_period(self, start_date_str: str, end_date_str: str):
        params = {'startDate': start_date_str, 'endDate': end_date_str, 'intervalType': "HOURLY"}
        return await self._make_api_call("GET", "/v2/private/naturalgas/advanced/usage", params=params, description=f"gas usage for {start_date_str}-{end_date_str}")

    async def get_powershout_info(self): return await self._make_api_call("GET", "/v2/private/powershoutcurrency/eligible/accounts", description="Power Shout eligible accounts info")
    async def get_powershout_balance(self): return await self._make_api_call("GET", "/v2/private/powershoutcurrency/balance", description="Power Shout balance")
    async def get_powershout_bookings(self): return await self._make_api_call("GET", "/v2/private/powershoutcurrency/bookings", description="Power Shout bookings")
    async def get_powershout_offers(self): return await self._make_api_call("GET", "/v2/private/powershoutcurrency/offers", description="Power Shout offers")
    async def get_powershout_expiring_hours(self): return await self._make_api_call("GET", "/v2/private/powershoutcurrency/expiringHours", description="Power Shout expiring")
    async def get_powershout_recommended_hours(self, account_id: str, billing_account_id: str, icp_number: str, supply_agreement_id: str):
        params = {"accountId": account_id, "billingAccountId": billing_account_id, "icpNumber": icp_number, "supplyAgreementId": supply_agreement_id}
        return await self._make_api_call("GET", "/v2/private/powershout/recommendedHours", params=params, description="Power Shout recommended hours")
    async def get_powershout_vouchers_for_date(self, selected_date_str: str, supply_point_id: str):
        return await self._make_api_call("GET", "/v2/private/powershoutcurrency/bookings", params={"selectedDate": selected_date_str, "supplyPointId": supply_point_id}, description="Power Shout vouchers for date")
    async def add_powershout_booking(self, start_date_str: str, duration: int, supply_agreement_id: str, supply_point_id: str, loyalty_account_id: str, eco_hours: list, vouchers: list):
        payload = {"startDate": start_date_str, "supplyAgreementId": supply_agreement_id, "duration": duration, "supplyPointId": supply_point_id, "loyaltyAccountId": loyalty_account_id, "ecoHours": eco_hours, "vouchers": vouchers}
        return await self._make_api_call("POST", "/v2/private/powershoutcurrency/booking/add", json_payload=payload, description="add Power Shout booking", expect_json=False)
    async def accept_powershout_offer(self, loyalty_account_id: str, member_id: str, campaign_offer_id: str, quantity: int, offer_code: str) -> bool:
        payload = {"loyaltyAccountId": loyalty_account_id, "memberId": member_id, "campaignOfferId": campaign_offer_id, "quantity": quantity, "offerCode": offer_code}
        response = await self._make_api_call("POST", "/v2/private/powershoutcurrency/offer/accept", json_payload=payload, description="accept Power Shout offer", expect_json=False)
        return response.get("status") == 200

    async def get_billing_plans(self): return await self._make_api_call("GET", "/v2/private/billing/plans", description="billing plans")
    async def get_widget_bill_summary_v2(self): return await self._make_api_call("GET", "/v2/private/drd/widget/billSummaryV2", description="widget bill summary V2")
    async def get_generation_mix_realtime(self): return await self._make_api_call("GET", "/v2/private/generationMix/realTime", description="generation mix real-time")
    async def get_widget_property_list(self): return await self._make_api_call("GET", "/v2/private/drd/widget/propertyList", description="widget property list")
    async def get_widget_property_switcher(self): return await self._make_api_call("GET", "/v2/private/drd/widget/propertySwitcher", description="widget property switcher")
    async def get_widget_hero_info(self): return await self._make_api_call("GET", "/v2/private/drd/widget/hero/info", description="widget hero info")
    async def get_widget_sidekick(self): return await self._make_api_call("GET", "/v2/private/drd/widget/sidekick", description="widget sidekick")
    async def get_widget_bill_summary(self): return await self._make_api_call("GET", "/v2/private/drd/widget/billSummary", description="widget bill summary")
    async def get_widget_dashboard_powershout(self): return await self._make_api_call("GET", "/v2/private/drd/widget/powerShout", description="widget dashboard Power Shout")
    async def get_widget_eco_tracker(self): return await self._make_api_call("GET", "/v2/private/drd/widget/ecoTracker", description="widget eco tracker")
    async def get_widget_dashboard_list(self, tab_id: str = "newDashboard"): return await self._make_api_call("GET", "/v2/private/drd/widgets/list", params={"tabId": tab_id}, description="widget dashboard list")
    async def get_widget_action_tile_list(self): return await self._make_api_call("GET", "/v2/private/drd/actionTile/list", description="widget action tile list")
    async def get_next_best_action(self): return await self._make_api_call("GET", "/v2/private/nextBestAction", description="next best action")
    async def get_generation_mix(self): return await self._make_api_call("GET", "/v2/private/generationMix/nextTwoDays", description="generation mix")
    async def get_lpg_order_status(self): return await self._make_api_call("GET", "/v2/private/lpg/orderStatus", description="LPG order status")
    async def get_lpg_delivery_history(self, sa_id: str): return await self._make_api_call("GET", "/v2/private/lpg/deliveryHistory", params={"supplyAgreementId": sa_id, "skip": 0, "pageSize": 40}, description="LPG delivery history")
    async def get_lpg_delivery_summary(self, sa_id: str): return await self._make_api_call("GET", "/v2/private/lpg/deliverySummary", params={"supplyAgreementId": sa_id}, description="LPG delivery summary")