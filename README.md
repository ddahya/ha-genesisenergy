# Genesis Energy Integration for Home Assistant

A custom integration for Home Assistant to connect with Genesis Energy (New Zealand). It automatically retrieves hourly electricity and gas usage, daily costs, forecasts, category breakdowns, LPG details, EV plan savings, Power Shout balances/offers, and billing information.

![Energy Dashboard Reporting](/homeassistant-energy-graph.png "Energy Dashboard Reporting")

---

## ✨ Features

* 📊 **Energy Dashboard & Statistics Engine:**
  * Creates long-term statistics for **Electricity Consumption (kWh)** and **Gas Consumption (kWh)**.
  * Tracks daily **Electricity Cost (NZD)** and **Gas Cost (NZD)**.
  * **Instant Startup Sync:** Ingests the 4-day usage buffer into statistics upon startup without waiting for an hourly poll cycle.
  * **Continuous Historical Sums:** Re-engineered baseline tracking eliminates 12:00 AM sum drops and artificial spikes.
  * **Solar Export Support:** Accurately retains negative smart meter reads for HomeGen credit so solar generation displays correctly on the Energy Dashboard.
* 🛠️ **Automatic Data Correction (Options Flow):**
  * Built-in option to schedule a daily automatic statistic overwrite after 1:00 PM to fix delayed or missing hourly data reported by Genesis.
* 🎁 **Advanced Power Shout Management:**
  * Sensors for **Eligibility**, **Balance (Hours)**, and **Offers Available** (`binary_sensor.genesis_energy_power_shout_offers_available`).
  * **Retroactive Bookings:** Book free Power Shout hours for past dates (up to 31 days prior).
  * **Top 5 Recommended Past Hours:** Exposes `recommended_hours`, `recommended_hours_count`, and `top_recommended_hour` attributes on your balance sensor, pinpointing the highest-cost hours to redeem for maximum savings.
* 🌿 **Real-Time Eco Tracker:**
  * Live monitoring of New Zealand’s real-time national grid generation eco-mix (`Grid Generation Eco-Friendly`), tracking generation percentages across Hydro, Wind, Geothermal, Solar, Gas, and Coal.
* ⚡ **Dynamic Tariff & EV Plan Sensors:**
  * Pulls active pricing plans directly from the API: `EV Low Day`, `EV Low Night`, `Daily Fixed`, and `Gas Variable`.
  * For EV plans: Tracks daily Day (Peak) vs. Night (Off-Peak) usage/costs and calculates your daily savings compared to the standard rate.
* 💳 **Billing Cycle Sensors (v2 API):**
  * `Electricity Used ($)`, `Gas Used ($)`, `Total Used ($)`, `Estimated Total Bill ($)`, and `Estimated Future Use ($)`.
* 🍾 **LPG (Bottled Gas) Details:**
  * Detects bottled gas accounts and exposes order status, full delivery history, and statistics like average days between deliveries via `sensor.genesis_energy_lpg_details`.
* 🏠 **Multi-Property & Multi-Account Support:**
  * Automatically respects your active property selection (`webSelectedSite`) from the Genesis web portal across sensors and Power Shout bookings.
* ⚡ **Electricity Forecast Sensors:**
  * Exposes `Today's Forecast Usage (kWh)` and `Today's Forecast Cost ($)`.
  * Extra attributes provide predicted high/low ranges and full 7-day forecast data.
* 🏷️ **Usage Breakdown Sensors:**
  * Categorizes electricity consumption by `Appliances`, `Electronics`, `Lighting`, and `Other` (in kWh).
* 🔒 **Modern Architecture & Concurrency:**
  * **Azure AD B2C with PKCE:** Secure authentication with permanent 90-day background token rotation—no session drops or verification code prompts on restart.
  * **Two-Step Verification:** Built-in fallback flow in Home Assistant if Genesis requests a two-step code.
  * **Service-Aware Polling:** Only queries endpoints matching your active services, cutting hourly API calls by up to 80%.
  * **Concurrency Throttling:** Throttles concurrent API requests to avoid Cloudflare `500`/`502` connection drops.
* 🎴 **Built-in Lovelace Card (`custom:genesisenergy-powershout-card`):**
  * **Auto-Registered**: No manual JavaScript resource copying or manual Lovelace resource URLs needed—loads automatically on boot.
  * **Interactive Power Shout Engine**: Book upcoming sessions, cancel scheduled/in-progress sessions to refund hours, or claim top-saving past hours from the last 31 days with 1-click confirmation dialogs.
  * **Animated Status Banners**: Pulsing glowing banners for active free power sessions, available bonus offers to claim, and expiring hours warnings.
  * **Recent Usage Stacked Graph**: Recreates the Genesis portal’s daily stacked bar chart (Electricity in Orange, Gas in Plum) with cycle progress tracking and hover tooltips.
  * **Detailed Analytics (Monthly & Daily)**: Dedicated charts for Electricity, Natural Gas usage with date navigator and instant click-to-drilldown from Monthly to Daily.
  * **Current Bill & Direct Debit Tracker**: Displays current invoice totals, due dates, and direct debit notifications.

---

## 💾 Installation

### Option 1: HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Click the button below to open the repository in HACS:  
   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DDahya&repository=ha-genesisenergy&category=integration)  
   *(Or add `https://github.com/ddahya/ha-genesisenergy` as a Custom Repository under HACS > Integrations).*
3. Click **Download** and **restart Home Assistant**.

### Option 2: Manual Installation

1. Download this repository.
2. Copy the `custom_components/genesisenergy` folder into your Home Assistant `<config_dir>/custom_components/` directory.
3. **Restart Home Assistant.**

---

## ⚙️ Configuration & Options

1. Go to **Settings > Devices & Services**.
2. Click **+ Add Integration** and search for **Genesis Energy**.
3. Enter your Genesis Energy account **Email** and **Password** (the same credentials used for [Genesis My Account](https://myaccount.genesisenergy.co.nz/)).
4. If prompted for two-step verification, enter the code sent to your email.
5. Click **Submit**.

### Integration Options (Auto-Correction)
1. Go to **Settings > Devices & Services > Genesis Energy**.
2. Click **Configure**.
3. Toggle **Enable Auto-Correction**. When enabled, the integration performs a daily statistics check after 1:00 PM to correct any delayed or revised hourly data reported by Genesis.

## 🎴 The Custom Lovelace Card

The integration serves and auto-registers `powershout-card.js`. No separate script or helper automations are required, all booking, cancelling, and offer redemptions run natively inside the card.


![Energy Dashboard Reporting](/Power_Shout_Card.png "Energy Dashboard Reporting")

### Quick Start (Add to Dashboard)

In your dashboard, click **Add Card**, search for **Genesis Energy - Power Shout & Account Card**, or select **Manual**, and paste:
```yaml
type: custom:genesisenergy-powershout-card
Full Configuration Options

type: custom:genesisenergy-powershout-card

# --- Display & Behavior ---
title: "My Home"              # Custom card title override (default: "Genesis Energy")
show_powershout: auto         # 'auto' (detects eligibility), 'true' (force on), or 'false' (force off)
default_tab: usage            # Tab to open by default: 'shout', 'usage', 'past', 'forecast', or 'summary'
chart_days: 17                # Number of days in the top Recent Usage chart (default: 17)

# --- Entity ID Overrides (Optional - auto-discovered by default) ---
entity_balance: sensor.genesis_energy_power_shout_balance
entity_eligible: sensor.genesis_energy_power_shout_eligible
entity_offers_available: binary_sensor.genesis_energy_power_shout_offers_available
entity_account_details: sensor.genesis_energy_account_details
entity_bill_total_used: sensor.genesis_energy_genesis_bill_total_used
entity_estimated_bill: sensor.genesis_energy_genesis_bill_estimated_total
entity_forecast_cost: sensor.genesis_energy_today_s_forecast_cost
entity_forecast_usage: sensor.genesis_energy_today_s_forecast_usage
entity_lpg: sensor.genesis_energy_lpg_details
```
---

## 📈 Energy Dashboard Setup

To add Genesis Energy data to your Home Assistant Energy Dashboard:

1. Go to **Settings > Dashboards > Energy**.
2. Under **Electricity Grid**, click **Add Consumption** and select:
   * `Genesis Electricity Consumption Daily` (`sensor.genesis_energy_electricity_consumption_daily`)
3. Under **Gas Consumption**, click **Add Gas Source** and select:
   * `Genesis Gas Consumption Daily` (`sensor.genesis_energy_gas_consumption_daily`)

---

## 🛠️ Actions & Services

This integration provides four actions/services to manage your account and statistics.

### 1. `genesisenergy.backfill_statistics`
Imports historical usage data from Genesis into Home Assistant's long-term statistics database.

| Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `days_to_fetch` | `integer` | **Required.** Number of past days to retrieve (1–730). | `90` |
| `fuel_type` | `select` | **Required.** `electricity`, `gas`, or `both`. | `both` |
| `force_overwrite` | `boolean` | **Required.** `true` to re-fetch and overwrite existing statistics; `false` to only fill missing dates. | `false` |

---

### 2. `genesisenergy.add_powershout_booking`
Books a Power Shout session directly from Home Assistant. Automatically detects and uses your currently selected property (`isSelectedSite`).

| Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `start_datetime` | `datetime` | **Required.** Local start date and time for the booking. | `"2026-08-15 18:00:00"` |
| `duration_hours` | `integer` | **Required.** Duration in hours (1–4). | `1` |

---

### 3. `genesisenergy.accept_powershout_offer`
Accepts an available Power Shout offer using the offer GUID.

| Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `offer_id` | `string` | **Required.** The unique GUID/ID of the offer. | `"12345678-abcd-1234-abcd-1234567890ab"` |

> [!IMPORTANT]
> **Usage Note:** This service cannot be easily called directly from Developer Tools because it requires the exact `offer_id` GUID from Genesis. It is designed to be called via a script (like `script.accept_all_power_shout_offers` below) which automatically extracts the `offer_id` from your Power Shout balance attributes.

---

### 4. `genesisenergy.force_update`
Triggers an immediate poll of the Genesis Energy API for all sensors.

| Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `fuel_type` | `select` | **Required.** `electricity`, `gas`, or `both`. | `both` |


---

## 🐛 Debugging

To enable verbose debug logging for this integration, add the following to your `configuration.yaml`:

    logger:
      default: info
      logs:
        custom_components.genesisenergy: debug

---

## 📄 Disclaimer

This custom integration is developed for the Home Assistant community with Artificial Intelligence (AI) assistance. It interacts with private web APIs used by Genesis Energy NZ. Use of this integration is at your own risk. The maintainers are not responsible for any issues with your Genesis Energy account, billing, or bookings.
