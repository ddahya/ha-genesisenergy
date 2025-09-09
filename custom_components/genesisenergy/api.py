# custom_components/genesisenergy/api.py

import aiohttp
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
import json
from urllib.parse import parse_qs
import socket
import asyncio

from .exceptions import CannotConnect, InvalidAuth

_LOGGER = logging.getLogger(__name__)

BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

class GenesisEnergyApi:
    """API to interact with Genesis Energy services."""
    TOKEN_VALIDITY_BUFFER_MINUTES = 5

    def __init__(self, email: str, password: str) -> None:
        self._client_id = "8e41676f-7601-4490-9786-85d74f387f47"
        self._redirect_uri = 'https://myaccount.genesisenergy.co.nz/auth/redirect'
        self._url_token_base = "https://auth.genesisenergy.co.nz/auth.genesisenergy.co.nz"
        self._url_data_base = "https://web-api.genesisenergy.co.nz/"
        self._p = "B2C_1A_signin"
        self._email = email
        self._password = password
        self._token: str | None = None
        self._refresh_token: str | None = None
        self._access_token_absolute_expiry_ts: float = 0.0
        self._refresh_token_absolute_expiry_ts: float = 0.0
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

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
            if line.startswith("var SETTINGS = ") and line.endswith(";"):
                json_string = line.removeprefix("var SETTINGS = ").removesuffix(";")
                try: return json.loads(json_string)
                except json.JSONDecodeError as e: _LOGGER.error(f"JSONDecodeError: {e}"); return None
        _LOGGER.warning("SETTINGS variable not found."); return None

    async def _perform_full_login(self) -> bool:
        """Performs a full login using a temporary, clean session and manual cookie management."""
        _LOGGER.info("Attempting full login with a temporary, clean session...")
        
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector, cookie_jar=aiohttp.DummyCookieJar()) as session:
            cookies = {}
            
            def update_cookies_from_response(response):
                for cookie in response.cookies.values():
                    cookies[cookie.key] = cookie.value

            def get_cookie_header():
                return "; ".join([f"{k}={v}" for k, v in cookies.items()]) if cookies else None

            try:
                base_headers = {"User-Agent": BROWSER_USER_AGENT}
                # Step 1
                _LOGGER.debug("Login Step 1: Fetching initial auth page...")
                url_s1 = f"{self._url_token_base}/oauth2/v2.0/authorize"
                p_s1 = {'p': self._p, 'client_id': self._client_id, 'response_type': 'code', 'response_mode': 'query', 'scope': f'openid offline_access {self._client_id}', 'redirect_uri': self._redirect_uri}
                async with session.get(url_s1, params=p_s1, headers=base_headers) as r_s1:
                    txt_s1 = await r_s1.text()
                    update_cookies_from_response(r_s1)
                    r_s1.raise_for_status()
                sjson = self._get_setting_json(txt_s1)
                if not sjson: raise CannotConnect("Login S1: no settings_json")
                tid, csrf = sjson.get("transId"), sjson.get("csrf")
                if not tid or not csrf: raise CannotConnect("Login S1: no tid/csrf")
                
                # Step 2
                _LOGGER.debug("Login Step 2: Posting email...")
                url_s2 = f"{self._url_token_base}/{self._p}/SelfAsserted?tx={tid}&p={self._p}"
                pay_s2 = {"request_type": "RESPONSE", "email": self._email}
                hdr_s2 = {**base_headers, 'X-CSRF-TOKEN': csrf, 'Cookie': get_cookie_header()}
                async with session.post(url_s2, headers=hdr_s2, data=pay_s2) as r_s2:
                    update_cookies_from_response(r_s2)
                    r_s2.raise_for_status()

                # Step 3
                _LOGGER.debug("Login Step 3: Confirming email...")
                url_s3 = f"{self._url_token_base}/{self._p}/api/SelfAsserted/confirmed"
                p_s3 = {'csrf_token': csrf, 'tx': tid, 'p': self._p}
                hdr_s3 = {**base_headers, 'Referer': str(url_s2), 'Cookie': get_cookie_header()}
                async with session.get(url_s3, params=p_s3, headers=hdr_s3) as r_s3:
                    update_cookies_from_response(r_s3)
                    r_s3.raise_for_status()
                if 'x-ms-cpim-csrf' in cookies: csrf = cookies['x-ms-cpim-csrf']
                else: raise CannotConnect("Login S3: CSRF cookie missing after confirm")

                # Step 4
                _LOGGER.debug("Login Step 4: Posting password...")
                url_s4 = f"{self._url_token_base}/{self._p}/SelfAsserted?tx={tid}&p={self._p}"
                pay_s4 = {"request_type": "RESPONSE", "signInName": self._email, "password": self._password}
                hdr_s4 = {**base_headers, 'X-CSRF-TOKEN': csrf, 'Cookie': get_cookie_header()}
                async with session.post(url_s4, headers=hdr_s4, data=pay_s4) as r_s4:
                    update_cookies_from_response(r_s4)
                    if r_s4.status != 200:
                        s4_text = await r_s4.text()
                        if "The username or password provided in the request are invalid" in s4_text: raise InvalidAuth("Invalid username or password.")
                        r_s4.raise_for_status()

                # Step 5
                _LOGGER.debug("Login Step 5: Finalizing login to get redirect...")
                url_s5 = f"{self._url_token_base}/{self._p}/api/CombinedSigninAndSignup/confirmed"
                p_s5 = {'rememberMe': 'false', 'csrf_token': csrf, 'tx': tid, 'p': self._p}
                hdr_s5 = {**base_headers, 'Cookie': get_cookie_header()}
                async with session.get(url_s5, params=p_s5, headers=hdr_s5, allow_redirects=False) as r_s5:
                    if r_s5.status != 302: raise CannotConnect(f"Login S5: status {r_s5.status}")
                    loc = r_s5.headers.get('Location', '')
                if not loc: raise CannotConnect("Login S5: no location header")
                
                # Step 6
                _LOGGER.debug("Login Step 6: Exchanging code for token...")
                qpr = parse_qs(loc.split('?', 1)[1])
                if 'error' in qpr: raise InvalidAuth(f"Login S5 error: {qpr['error'][0]}")
                if 'code' not in qpr: raise CannotConnect("Login S5: no auth code")
                code = qpr['code'][0]
                url_s6 = f"{self._url_token_base}/{self._p}/oauth2/v2.0/token"
                p_s6 = {'p': self._p, 'grant_type': 'authorization_code', 'client_id': self._client_id, 'scope': f'openid offline_access {self._client_id}', 'redirect_uri': self._redirect_uri, 'code': code}
                async with session.get(url_s6, params=p_s6, headers=base_headers) as r_s6:
                    if r_s6.status == 200:
                        data_s6 = await r_s6.json()
                        self._token = data_s6.get('access_token'); self._refresh_token = data_s6.get('refresh_token')
                        expires_in = data_s6.get('expires_in', 0); rt_expires_in = data_s6.get('refresh_token_expires_in', 0)
                        now_ts = datetime.now(timezone.utc).timestamp()
                        self._access_token_absolute_expiry_ts = (now_ts + int(expires_in)) if expires_in else 0
                        self._refresh_token_absolute_expiry_ts = (now_ts + int(rt_expires_in)) if rt_expires_in else 0
                        if not self._token: raise InvalidAuth("Login S6: no access token")
                        _LOGGER.info("Full login successful.")
                        return True
                    else: raise CannotConnect(f"Login S6: status {r_s6.status}")
            
            except aiohttp.ClientError as e:
                _LOGGER.warning(
                    "A network error occurred during login (e.g., DNS failure, timeout). "
                    "This is expected if internet is unavailable. Error: %s", e
                )
                raise CannotConnect(f"Network error during login: {e}") from e
            except Exception as e:
                _LOGGER.error(f"Login FAILED with an unexpected exception: {e}", exc_info=True)
                raise CannotConnect(f"A low-level error occurred during login: {e}") from e

    async def _refresh_access_token(self) -> bool:
        """Refreshes the access token and handles network errors gracefully."""
        _LOGGER.info("Attempting to refresh access token...")
        if not self._refresh_token: return False
        
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector) as session:
            payload = {"grant_type": "refresh_token", "client_id": self._client_id, "scope": f"openid offline_access {self._client_id}", "redirect_uri": self._redirect_uri, "refresh_token": self._refresh_token}
            url = f"{self._url_token_base}/oauth2/v2.0/token?p={self._p}"
            try:
                async with session.post(url, data=payload, headers={"User-Agent": BROWSER_USER_AGENT}) as response:
                    if response.status == 200:
                        data = await response.json()
                        self._token = data.get("access_token")
                        new_expires_in = data.get("expires_in")
                        if self._token and new_expires_in is not None:
                            now_ts = datetime.now(timezone.utc).timestamp()
                            self._access_token_absolute_expiry_ts = now_ts + int(new_expires_in)
                            _LOGGER.info("Access token refreshed successfully.")
                            new_rt = data.get("refresh_token")
                            if new_rt and new_rt != self._refresh_token:
                                self._refresh_token = new_rt
                                new_rt_expires_in = data.get("refresh_token_expires_in")
                                if new_rt_expires_in is not None: self._refresh_token_absolute_expiry_ts = now_ts + int(new_rt_expires_in)
                                _LOGGER.info("Refresh token was rotated.")
                            return True
                        _LOGGER.warning("Token refresh response was OK but malformed.")
                        return False
                    else:
                        if response.status in [400, 401]:
                            _LOGGER.warning("Refresh token is invalid. Forcing full re-login.")
                            self._refresh_token = None
                            self._refresh_token_absolute_expiry_ts = 0
                        else:
                            _LOGGER.error(f"Unexpected status {response.status} during token refresh.")
                        return False
            # Catch specific network errors first
            except aiohttp.ClientError as e:
                _LOGGER.warning("A network error occurred during token refresh: %s", e)
                # We raise CannotConnect so the coordinator knows to retry later
                raise CannotConnect(f"Network error during token refresh: {e}") from e
            # Catch other unexpected errors
            except Exception as e:
                _LOGGER.exception("An unexpected error occurred during token refresh.")
                return False

    async def _ensure_valid_token(self) -> None:
        """Ensures the access token is valid, refreshing if necessary, using a lock to prevent race conditions."""
        current_time_utc_ts = datetime.now(timezone.utc).timestamp()
        if self._token and self._access_token_absolute_expiry_ts > (current_time_utc_ts + self.TOKEN_VALIDITY_BUFFER_MINUTES * 60):
            return

        async with self._lock:
            if self._token and self._access_token_absolute_expiry_ts > (datetime.now(timezone.utc).timestamp() + self.TOKEN_VALIDITY_BUFFER_MINUTES * 60):
                return
            
            _LOGGER.info("Token has expired or is invalid. Proceeding with refresh/login under lock.")

            try:
                if self._refresh_token and (self._refresh_token_absolute_expiry_ts == 0 or self._refresh_token_absolute_expiry_ts > datetime.now(timezone.utc).timestamp()):
                    if await self._refresh_access_token():
                        # If refresh was successful, we're done
                        return
            except CannotConnect:
                 # If refresh fails due to network, re-raise to stop the update.
                 # This prevents an immediate, and likely failing, full login attempt.
                raise

            # If refresh failed for any other reason or was not possible, perform a full login
            if not await self._perform_full_login(): raise CannotConnect("Full login failed.")
            if not (self._token and self._access_token_absolute_expiry_ts > (datetime.now(timezone.utc).timestamp() + self.TOKEN_VALIDITY_BUFFER_MINUTES * 60)): raise InvalidAuth("Token invalid after login.")


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
                    self._token = None; self._access_token_absolute_expiry_ts = 0
                    raise InvalidAuth(f"Unauthorized (401) for {description}")
                else:
                    raise CannotConnect(f"API error for {description}: {response.status} - {await response.text()}")
        except aiohttp.ClientError as e: raise CannotConnect(f"HTTP client error for {description}: {e}") from e
        except json.JSONDecodeError as e: raise CannotConnect(f"Invalid JSON from {description}: {e}") from e
    
    async def get_energy_data(self, days_to_fetch: int = 4):
        from_date = (datetime.now() - timedelta(days=days_to_fetch)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")
        payload = {'startDate': from_date, 'endDate': to_date, 'intervalType': "HOURLY"}
        return await self._make_api_call("POST", "/v2/private/electricity/site-usage", json_payload=payload, description="electricity usage")
        
    async def get_ev_plan_usage(self):
        """Gets electricity usage specifically for an EV plan."""
        return await self._make_api_call("GET", "/v2/private/evPlan/electricityUsage", description="EV plan usage")

    async def get_gas_data(self, days_to_fetch: int = 4):
        from_date = (datetime.now() - timedelta(days=days_to_fetch)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")
        params = {'startDate': from_date, 'endDate': to_date, 'intervalType': "HOURLY"}
        return await self._make_api_call("GET", "/v2/private/naturalgas/advanced/usage", params=params, description="gas usage")
    
    async def get_electricity_forecast(self):
        """Gets the electricity forecast."""
        return await self._make_api_call("GET", "/v2/private/electricityForecast", description="electricity forecast")
        
    async def get_usage_breakdown(self):
        """Gets the electricity usage breakdown by category."""
        return await self._make_api_call("GET", "/v2/private/insights/usagebreakdown", params={"environment": "web"}, description="usage breakdown")

    async def get_energy_data_for_period(self, start_date_str: str, end_date_str: str):
        payload = {'startDate': start_date_str, 'endDate': end_date_str, 'intervalType': "HOURLY"}
        return await self._make_api_call("POST", "/v2/private/electricity/site-usage", json_payload=payload, description=f"electricity usage for {start_date_str}-{end_date_str}")
    async def get_gas_data_for_period(self, start_date_str: str, end_date_str: str):
        params = {'startDate': start_date_str, 'endDate': end_date_str, 'intervalType': "HOURLY"}
        return await self._make_api_call("GET", "/v2/private/naturalgas/advanced/usage", params=params, description=f"gas usage for {start_date_str}-{end_date_str}")
    async def get_powershout_info(self): return await self._make_api_call("GET", "/v2/private/powershoutcurrency", description="Power Shout info")
    async def get_powershout_balance(self): return await self._make_api_call("GET", "/v2/private/powershoutcurrency/balance", description="Power Shout balance")
    async def get_powershout_bookings(self): return await self._make_api_call("GET", "/v2/private/powershoutcurrency/bookings", description="Power Shout bookings")
    async def get_powershout_offers(self): return await self._make_api_call("GET", "/v2/private/powershoutcurrency/offers", description="Power Shout offers")
    async def get_powershout_expiring_hours(self): return await self._make_api_call("GET", "/v2/private/powershoutcurrency/expiringHours", description="Power Shout expiring")
    async def add_powershout_booking(self, start_date_str: str, duration: int, supply_agreement_id: str, supply_point_id: str, loyalty_account_id: str):
        payload = {"startDate": start_date_str, "supplyAgreementId": supply_agreement_id, "duration": duration, "supplyPointId": supply_point_id, "loyaltyAccountId": loyalty_account_id}
        return await self._make_api_call("POST", "/v2/private/powershoutcurrency/booking/add", json_payload=payload, description="add Power Shout booking", expect_json=False)
    
    async def accept_powershout_offer(
        self,
        loyalty_account_id: str,
        member_id: str,
        campaign_offer_id: str,
        quantity: int,
        offer_code: str
    ) -> bool:
        """Accepts a Power Shout offer."""
        payload = {
            "loyaltyAccountId": loyalty_account_id,
            "memberId": member_id,
            "campaignOfferId": campaign_offer_id,
            "quantity": quantity,
            "offerCode": offer_code,
        }
        response = await self._make_api_call(
            "POST",
            "/v2/private/powershoutcurrency/offer/accept",
            json_payload=payload,
            description="accept Power Shout offer",
            expect_json=False
        )
        return response.get("status") == 200
        
    async def get_billing_plans(self):
        return await self._make_api_call("GET", "/v2/private/billing/plans", description="billing plans")
    async def get_widget_property_list(self):
        return await self._make_api_call("GET", "/v2/private/drd/widget/propertyList", description="widget property list")
    async def get_widget_property_switcher(self):
        return await self._make_api_call("GET", "/v2/private/drd/widget/propertySwitcher", description="widget property switcher")
    async def get_widget_hero_info(self):
        return await self._make_api_call("GET", "/v2/private/drd/widget/hero/info", description="widget hero info")
    async def get_widget_sidekick(self):
        return await self._make_api_call("GET", "/v2/private/drd/widget/sidekick", description="widget sidekick")
    async def get_widget_bill_summary(self):
        return await self._make_api_call("GET", "/v2/private/drd/widget/billSummary", description="widget bill summary")
    async def get_widget_dashboard_powershout(self): 
        return await self._make_api_call("GET", "/v2/private/drd/widget/powerShout", description="widget dashboard Power Shout")
    async def get_widget_eco_tracker(self):
        return await self._make_api_call("GET", "/v2/private/drd/widget/ecoTracker", description="widget eco tracker")
    async def get_widget_dashboard_list(self, tab_id: str = "newDashboard"):
        params = {"tabId": tab_id}
        return await self._make_api_call("GET", "/v2/private/drd/widgets/list", params=params, description="widget dashboard list")
    async def get_widget_action_tile_list(self):
        return await self._make_api_call("GET", "/v2/private/drd/actionTile/list", description="widget action tile list")
    async def get_electricity_aggregated_bill_period(self, start_date: str, end_date: str):
        payload = {'startDate': start_date, 'endDate': end_date}
        return await self._make_api_call("POST", "/v2/private/electricity/aggregated-site-bill-period", json_payload=payload, description="electricity aggregated bill period")
    async def get_naturalgas_aggregated_bill_period(self, start_date: str, end_date: str):
        params = {'startDate': start_date, 'endDate': end_date}
        return await self._make_api_call("GET", "/v2/private/naturalgas/advanced/usage", params=params, description="naturalgas aggregated bill period")
    async def get_next_best_action(self):
        return await self._make_api_call("GET", "/v2/private/nextBestAction", description="next best action")
    
    async def get_generation_mix(self):
        """Gets the generation mix forecast for the next two days."""
        return await self._make_api_call("GET", "/v2/private/generationMix/nextTwoDays", description="generation mix")