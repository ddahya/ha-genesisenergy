# Genesis Energy Integration for Home Assistant (Beta)

[![hacs_badge](https://img.shields.io/badge/HACS-Beta-orange.svg)](https://github.com/hacs/default)

This is the **Beta / Testing branch** for the Genesis Energy (NZ) Home Assistant integration. 

> [!WARNING]
> **Beta Status — Untested Release:**  
> This version contains recent adaptations for Genesis Energy's new website and API changes. These changes are currently in testing.

### ✨ Key Changes & Enhancements

#### 1. Modern Authentication with PKCE & 90-Day Token Persistence
* **Azure AD B2C PKCE Standard:** Implemented modern PKCE (`code_challenge` / `code_verifier` with SHA-256) for authentication, eliminating login session drops.
* **Persistent 90-Day Refresh Tokens:** Stored refresh tokens permanently in Home Assistant storage (`config_entry.data`). Tokens rotate silently in the background, eliminating login prompts and email verification codes on restarts.
* **Two-Step Config Flow:** Added automated fallback handling for 2-step verification codes in `config_flow.py`.

#### 2. Full Compatibility with the New Genesis Website
* **Consolidated Bill Summary (`billSummaryV2`):** Migrated billing sensors (`Electricity Used`, `Gas Used`, `Total Used`, `Estimated Total`, `Estimated Future Use`) to Genesis's new unified V2 endpoint.
* **Real-Time Eco Tracker (`/generationMix/realTime`):** Restored the `Grid Generation Eco-Friendly` sensor using live NZ grid generation metrics (Hydro, Wind, Geothermal, Solar, Gas, Coal).
* **Restored Dynamic Tariff Sensors:** Reconnected electricity and gas tariff price sensors (`EV Low Day`, `EV Low Night`, `Daily Fixed`, `Gas Variable`) directly from `/v2/private/billing/plans`.

#### 3. Retroactive Power Shout Booking & Top Recommended Hours
* **Retroactive Past Bookings (Up to 31 Days):** Enabled support for Genesis's new feature allowing free Power Shout hours to be booked for past dates within the last 31 days.
* **Top 5 Recommended Past Hours:** Added `recommended_hours`, `recommended_hours_count`, and `top_recommended_hour` attributes to `sensor.genesis_energy_power_shout_balance`, surfacing the 5 highest-cost past hours where redeeming free power yields maximum savings.

#### 4. Energy Dashboard & Statistics Engine Improvements
* **Instant Startup Sync:** Added `async_added_to_hass()` lifecycle hook so Home Assistant immediately processes and imports the 4-day usage buffer into the Energy Dashboard upon boot without waiting an hour.
* **Fixed 12:00 AM Sum Spikes:** Re-engineered the preceding baseline lookup to query the true historical baseline sum across all database history, preventing sum resets and artificial 12:00 AM spikes.
* **Solar Export Support:** Maintained raw negative smart meter values for solar export (HomeGen credit), ensuring midday solar generation displays properly on the Energy Dashboard.
* **Value-Change Detection:** Added total consumption sum to the sensor hash check so newly published or updated meter reads (including gas) trigger statistic imports immediately.
* **Home Assistant 2026.11 Statistics Compliance:** Added `mean_type=StatisticMeanType.NONE` and `unit_class=None` to `StatisticMetaData`, eliminating deprecation warnings.

#### 5. Service-Aware Polling & Concurrency Optimization
* **Conditional Service Polling:** Automatically detects active account channels (Electricity, Gas, EV Plan, Power Shout, LPG) and only polls endpoints relevant to the account, reducing hourly requests by up to 80%.
* **Concurrency Semaphore (`asyncio.Semaphore(8)`):** Limited concurrent API connections to prevent Cloudflare `502 Bad Gateway` and `500 Internal Server Error` drops.
* **Fixed `"both"` Fuel Backfill:** Fixed an inverted `in` condition bug so calling `genesisenergy.backfill_statistics` with `fuel_type: "both"` backfills both Electricity and Gas in a single call.
* **Fixed Infinite Reload Loop:** Prevented background token rotation from triggering unnecessary full integration reloads.
* **Fixed `AttributeError: 'NoneType'`:** Added defensive null checks across all billing summary sensors.
