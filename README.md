# Genesis Energy Integration for Home Assistant

This is a custom component for Home Assistant to integrate with Genesis Energy (New Zealand). It fetches your hourly electricity and gas consumption, costs, forecasts, usage breakdowns, Power Shout details, and other account information, making it available within Home Assistant.

This integration is built by reverse-engineering the Genesis Energy web portal and is not officially supported by Genesis. It may break if Genesis changes their website or APIs.

![Energy Useage PNG](/homeassistant-energy-graph.png "Energy Dashboard Reporting")

## Features

*   **Energy Dashboard Integration:**
    *   Creates long-term statistics for **Electricity Consumption (kWh)** and **Gas Consumption (kWh)**.
    *   Also creates statistics for daily **Electricity Cost (NZD)** and **Gas Cost (NZD)** for detailed tracking.
*   **Electricity Forecast Sensors:**
    *   Integrates Genesis's daily and weekly electricity forecast.
    *   `Today's Forecast Usage (kWh)` and `Today's Forecast Cost ($)` sensors.
    *   Attributes include the predicted high/low range and the full 7-day forecast data, perfect for advanced automations.
*   **Usage Breakdown Sensors:**
    *   Shows how Genesis categorizes your electricity use from your last completed billing period.
    *   Creates sensors for `Appliances`, `Electronics`, `Lighting`, and `Other` usage (in kWh).
    *   Ideal for creating historical pie or bar charts to see where your energy goes.
*   **EV Plan Sensors:**
    *   If you're on an EV plan, it automatically creates sensors for your daily **Day (Peak) Usage/Cost** and **Night (Off-Peak) Usage/Cost**.
    *   A "Savings" sensor shows how much you saved on your last full day of usage compared to the standard rate.
*   **Power Shout Sensors:**
    *   Sensors for Power Shout **Eligibility** and current **Balance** (in hours).
    *   Attributes include details on upcoming bookings, active offers, and expiring hours.
*   **Billing Cycle Sensors:**
    *   Provides sensors for costs within your current billing cycle: `Electricity Used ($)`, `Gas Used ($)`, `Total Used ($)`, `Estimated Total Bill ($)`, and `Estimated Future Use ($)`.
*   **Detailed Account Sensor:**
    *   A single `sensor.genesis_energy_account_details` entity with a wealth of information in its attributes, including your billing plans, account IDs, and raw data from various dashboard widgets.
*   **Powerful Services:**
    *   `genesisenergy.add_powershout_booking`: Book your Power Shouts from automations or scripts.
    *   `genesisenergy.backfill_statistics`: A powerful tool to import historical usage data into Home Assistant.
    *   `genesisenergy.force_update`: Trigger an immediate data refresh.

## Installation

### HACS (recommended)

1. [Install HACS](https://www.hacs.xyz/docs/use/download/download/), if you did not already
2. [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DDahya&repository=ha-genesisenergy&category=integration)
3. Install the Genesis Energy integration
4. Restart Home Assistant

### Manual Installation

1.  Copy the `genesisenergy` folder from this repository into your Home Assistant `custom_components` folder.
    (Path: `<config_dir>/custom_components/genesisenergy/`)
2.  **Restart Home Assistant.**

## Configuration

1.  Go to **Settings > Devices & Services**.
2.  Click **+ ADD INTEGRATION** and search for "Genesis Energy".
3.  Enter your Genesis Energy **Email** and **Password**. These are the same credentials you use for the [Genesis Energy My Account portal](https://myaccount.genesisenergy.co.nz/).
4.  Click **SUBMIT**. The integration will set up a device and all associated sensors.

## Using with the Energy Dashboard

This integration creates long-term statistics that can be used to populate your Energy Dashboard.

**Important:** The integration will **not** import any data on the very first startup. This is to give you a chance to run a historical backfill first. To populate your statistics for the first time, you must call either the `genesisenergy.force_update` or `genesisenergy.backfill_statistics` service.

To configure the Energy Dashboard:
1.  Go to **Settings > Dashboards > Energy**.
2.  Under **Electricity grid**, click **ADD CONSUMPTION**.
3.  Select the following statistic:
    *   `Genesis Electricity Consumption Daily`
4.  Under **Gas consumption**, click **ADD GAS SOURCE**.
5.  Select the following statistic:
    *   `Genesis Gas Consumption Daily`

The underlying statistic IDs created by this integration are:
*   `sensor.genesis_energy_electricity_consumption_daily`
*   `sensor.genesis_energy_electricity_cost_daily`
*   `sensor.genesis_energy_gas_consumption_daily`
*   `sensor.genesis_energy_gas_cost_daily`

## Services

This integration provides three powerful services to manage your account.

### Service: `genesisenergy.backfill_statistics`

This service imports historical usage data. It is most effective when run on a new installation to populate a deep history.

**Note:** This service will **not** fix or overwrite existing data. It will only add data for periods where none exists. If you have corrupted data from a previous version, you must fix it manually in **Developer Tools > Statistics**.

| Field             | Description                                                                 | Example          |
| ----------------- | --------------------------------------------------------------------------- | ---------------- |
| `days_to_fetch`   | **Required.** The total number of past days of data to retrieve.            | `365`            |
| `fuel_type`       | **Required.** Which fuel type to backfill.                                  | `electricity`    |
|                   | Options: `electricity`, `gas`, `both`                                       |                  |

**How It Works (Important!)**

This service is designed to be **safe** and **non-destructive**. It will only add data for periods where **no data currently exists** in your Home Assistant database.

*   **On a Clean Install:** When you first add the integration, your database is empty. You can run this service with a large number of days (e.g., `365`) to import a full year of history. This will work perfectly.

*   **After Data is Imported:** Once statistics exist, the service's behavior changes. It will fetch the historical data you request, but it will **only import points that are newer than the newest point already in your database.** This is a safety feature to prevent the "negative number" bug and avoid corrupting your existing history.

**What This Means for You:**

*   **The backfill service is most effective when run once, right after a clean installation.** Decide how much history you want (e.g., 90, 180, 365 days) and run it then.
*   The service **cannot** be used to "fix" or "re-import" data for a period that has already been recorded. Its primary purpose is to fill in the past from where your data currently ends.
*   If you have a gap or corrupted data from a previous version, you must fix it manually using **Developer Tools > Statistics**. The current version of this integration will prevent new corruption from occurring.


### Service: `genesisenergy.add_powershout_booking`

This service lets you book Power Shouts from automations.

| Field             | Description                                                                 | Example                    |
| ----------------- | --------------------------------------------------------------------------- | -------------------------- |
| `start_datetime`  | **Required.** The date and time for the Power Shout to begin (in your local timezone). | `"2025-07-20 19:00:00"`    |
| `duration_hours`  | **Required.** The duration in hours (e.g., 1, 2, 3).                        | `2`                        |

### Service: `genesisenergy.force_update`

This service triggers an immediate data refresh for all sensors. It has no parameters.

## Important Note for New Installations

When you first install the Genesis Energy integration, it will fetch the last 4 days of your usage data. However, to ensure Home Assistant's database is fully ready, the integration **will not automatically import this data** into the long-term statistics.

**You must manually trigger the first import.**

This gives you a critical opportunity: if you want to import a large amount of historical data, you should do it now, before any recent data is added.

**Recommended Steps for New Users:**

1.  After installing and configuring the integration, wait a minute for it to settle.
2.  **If you want a deep history:** Call the `genesisenergy.backfill_statistics` service. Choose `both` for the fuel type and set `days_to_fetch` to your desired amount (e.g., `365` for one year). This will be the first data to enter your database, creating a complete history.
3.  **If you only want recent data:** Call the `genesisenergy.force_update` service. This will trigger the import of the last 4 days of data and create your initial statistics.

Once you have performed either of these actions once, the integration will continue to update automatically every hour.

## Debugging

To enable debug logging, add the following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.genesisenergy: debug
