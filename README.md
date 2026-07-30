# Genesis Energy Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)

A custom integration for Home Assistant to connect with Genesis Energy (New Zealand). It automatically retrieves hourly electricity and gas usage, daily costs, forecasts, category breakdowns, LPG details, EV plan savings, Power Shout balances/offers, and billing information.

![Energy Dashboard Reporting](/homeassistant-energy-graph.png "Energy Dashboard Reporting")

---

## ✨ Features

* 📊 **Energy Dashboard Integration:**
  * Tracks **Electricity Consumption (kWh)** and **Gas Consumption (kWh)** for long-term statistics.
  * Tracks daily **Electricity Cost (NZD)** and **Gas Cost (NZD)** for detailed budget monitoring.
* 🛠️ **Automatic Data Correction (Options Flow):**
  * Built-in option to schedule a daily automatic statistic overwrite after 1:00 PM to fix delayed or missing hourly data reported by Genesis.
* 🏠 **Multi-Property & Multi-Account Support:**
  * Automatically respects your active property selection (`webSelectedSite`) from the Genesis web portal across sensors and Power Shout bookings.
* 🍾 **LPG (Bottled Gas) Details:**
  * Detects LPG accounts and exposes order status, delivery history, and usage summary statistics via `sensor.genesis_energy_lpg_details`.
* ⚡ **Electricity Forecast Sensors:**
  * Exposes `Today's Forecast Usage (kWh)` and `Today's Forecast Cost ($)`.
  * Extra attributes provide predicted high/low ranges and full 7-day forecast data.
* 🔌 **EV Plan Sensors:**
  * For EV Plan accounts, creates daily sensors for **Day (Peak) Usage/Cost**, **Night (Off-Peak) Usage/Cost**, and a **Savings ($)** sensor comparing off-peak rates to standard rates.
* 🏷️ **Usage Breakdown Sensors:**
  * Categorizes electricity consumption by `Appliances`, `Electronics`, `Lighting`, and `Other` (in kWh).
* 🎁 **Power Shout Management:**
  * Sensors for **Eligibility**, **Balance (Hours)**, and **Offers Available** (`binary_sensor.genesis_energy_power_shout_offers_available`).
  * Attributes track active offers, expiring hours, and upcoming bookings.
* 💳 **Billing Cycle Sensors:**
  * `Electricity Used ($)`, `Gas Used ($)`, `Total Used ($)`, `Estimated Total Bill ($)`, and `Estimated Future Use ($)`.
* 📋 **Account Details Entity:**
  * Single comprehensive entity (`sensor.genesis_energy_account_details`) exposing billing plan information and widget data.

---

## 💾 Installation

### Option 1: HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Go to **HACS > Integrations**.
3. Click the three dots in the top right corner and select **Custom repositories**.
4. Add `https://github.com/ddahya/ha-genesisenergy` as an **Integration**.
5. Search for "Genesis Energy", click **Download**, and restart Home Assistant.

### Option 2: Manual Installation

1. Download this repository.
2. Copy the `custom_components/genesisenergy` folder into your Home Assistant `<config_dir>/custom_components/` directory.
3. **Restart Home Assistant.**

---

## ⚙️ Configuration & Options

1. Go to **Settings > Devices & Services**.
2. Click **+ Add Integration** and search for **Genesis Energy**.
3. Enter your Genesis Energy **Email** and **Password** (same credentials used for [Genesis My Account](https://myaccount.genesisenergy.co.nz/)).
4. Click **Submit**.

### Integration Options (Auto-Correction)
To enable automatic statistics correction:
1. Go to **Settings > Devices & Services > Genesis Energy**.
2. Click **CONFIGURE**.
3. Toggle **Enable Auto-Correction**. When enabled, the integration will perform a daily statistic overwrite after 1:00 PM to correct any delayed hourly usage data from Genesis.

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

## 🤖 Helper Automation Scripts

To make the most of the integration on your dashboard, add these two helper scripts under **Settings > Automations & Scenes > Scripts**:

### Script 1: Accept All Power Shout Offers

This script automatically loops through and accepts all pending Power Shout offers when triggered.

    alias: Accept All Power Shout Offers
    sequence:
      - condition: template
        value_template: >-
          {{ state_attr('sensor.genesis_energy_power_shout_balance', 'active_offers_count') > 0 }}
      - repeat:
          for_each: >-
            {{ state_attr('sensor.genesis_energy_power_shout_balance', 'active_offers') }}
          sequence:
            - data:
                offer_id: "{{ repeat.item.loyaltyOffer.guid }}"
              action: genesisenergy.accept_powershout_offer
            - delay:
                seconds: 2
    icon: mdi:auto-fix
    description: "Accepts all available Power Shout offers from Genesis Energy."

### Script 2: Book a Power Shout (Interactive Form)

This script provides UI selectors (`datetime` picker and a 1-4 hour dropdown) when tapped on your dashboard:

    alias: Book a Power Shout
    sequence:
      - data:
          start_datetime: "{{ start_time }}"
          duration_hours: "{{ duration }}"
        action: genesisenergy.add_powershout_booking
    fields:
      start_time:
        name: Start Time
        description: Select the date and the start hour for your Power Shout.
        required: true
        selector:
          datetime: {}
      duration:
        name: Duration
        description: Select the duration of the Power Shout.
        required: true
        selector:
          select:
            options:
              - label: 1 Hour
                value: "1"
              - label: 2 Hours
                value: "2"
              - label: 3 Hours
                value: "3"
              - label: 4 Hours
                value: "4"
    mode: single
    icon: mdi:flash-alert
    description: "Allows interactive selection of start time and duration to book a Power Shout."

---

## 🎨 Dashboard Cards & Templates

Below are pre-built Lovelace cards designed for your dashboard.

### 1. Genesis Summary & Billing Markdown Card

Add a **Markdown** card and paste this Jinja2 template to display your live bill summary, usage breakdown, eco tracker, and active tariffs:

    type: markdown
    content: >-
      {% set sidekick_raw = state_attr('sensor.genesis_energy_account_details', 'widget_sidekick') %}
      {% set plans_raw = state_attr('sensor.genesis_energy_account_details', 'billing_plans') %}
      {% set eco_raw = state_attr('sensor.genesis_energy_account_details', 'eco_tracker') %}
      {% set ps_dash_raw = state_attr('sensor.genesis_energy_account_details', 'dashboard_powershout') %}
      {% set ps_active = is_state('binary_sensor.power_shout_active', 'on') %}

      {% if sidekick_raw is not none and plans_raw is not none %}
      {% set sidekick = sidekick_raw | from_json %}
      {% set plans = plans_raw | from_json %}

      {% if ps_active %}
      # <font color='#9c27b0'>FREE POWER ACTIVE</font>
      *Your current usage is covered by a Power Shout booking.*
      {% else %}
      ### {{ sidekick.titleArea.title }}
      {% endif %}

      # <font color='{{ "#9c27b0" if ps_active else "#00adef" }}'>${{ sidekick.titleArea.value }}</font>

      **Billing Period:** {{ sidekick.barArea.leftText }}

      **Status:** {{ sidekick.barArea.rightText }}

      ---
      ### {{ sidekick.billArea.title }}
      *Forecasted total for this period based on your usage patterns.*

      ---
      ### Usage Breakdown
      | Service | Cost |
      | :--- | :--- |
      {% for supply in sidekick.supplyTypesArea.supplyTypes -%}
      | {{ supply.text }} | ${{ supply.value }} |
      {% endfor %}

      {% if eco_raw is not none %}
      {% set eco = eco_raw | from_json %}
      ---
      ### Eco Tracker
      <font color='#4caf50'>**{{ eco.percentage }}%**</font> of NZ's power is currently being generated from **{{ eco.source }}**.
      {% endif %}

      {% if ps_dash_raw is not none %}
      {% set ps_dash = ps_dash_raw | from_json %}
      ---
      ### Power Shout Balance
      {{ ps_dash.message.description | replace('{{0}}', ps_dash.message.descriptionSubstrings[0].text) }}
      {% endif %}

      ---
      ### Active Tariffs
      {% for site in plans.billingAccountSites -%}
      {% for supply in site.supplyPoints -%}
      **{{ supply.supplyTypeDisplay }} ({{ supply.plan }})**
      {% for tariff in supply.tariffs -%}
      * {{ tariff.name }}: {{ tariff.value }} {{ tariff.unit }}
      {% endfor %}
      {% endfor %}
      {% endfor %}
      {% else %}
      ### Genesis Data Unavailable
      The integration is currently fetching fresh data from the Genesis API. Please wait a moment for the initial sync to complete.
      {% endif %}

---

### 2. Accept Power Shout Button (Blinking Alert)

A conditional button card using `custom:button-card` that flashes blue when a Power Shout offer is available:

    type: conditional
    conditions:
      - condition: state
        entity: binary_sensor.genesis_energy_power_shout_offers_available
        state: "on"
    card:
      type: custom:button-card
      entity: binary_sensor.genesis_energy_power_shout_offers_available
      name: Accept Power Shout Offer(s)
      icon: mdi:auto-fix
      show_icon: true
      styles:
        card:
          - background-color: "#1c6e9e"
          - animation: blink 2s ease infinite
        name:
          - color: white
        icon:
          - color: "#fdd835"
      tap_action:
        action: call-service
        service: script.accept_all_power_shout_offers
    grid_options:
      columns: 6
      rows: 2

---

### 3. Book Power Shout Interactive Card

Tapping this button triggers `script.book_a_power_shout`, prompting you with a pop-up dialog to pick the start date/time and duration:

    type: custom:button-card
    entity: binary_sensor.power_shout_active
    name: |
      [[[ 
        const balance = states['sensor.genesis_energy_power_shout_balance'].state;
        return `Book Power Shout`; 
      ]]]
    icon: mdi:flash-alert
    show_icon: true
    state:
      - value: "on"
        styles:
          card:
            - background-color: "#9c27b0"
            - animation: blink 2s ease infinite
          name:
            - color: white
          icon:
            - color: "#fdd835"
      - value: "off"
        styles:
          card:
            - background-color: var(--card-background-color)
          icon:
            - color: var(--paper-item-icon-color)
    tap_action:
      action: more-info
      entity: script.book_a_power_shout

---

### 4. Expiring Power Shouts Warning Card

Displays a mushroom template card when Power Shout hours are approaching expiration:

    type: custom:mushroom-template-card
    primary: Expiring Power Shouts
    icon: mdi:timer-sand
    icon_color: yellow
    features_position: bottom
    entity: sensor.genesis_energy_power_shout_balance
    secondary: >-
      {{ state_attr('sensor.genesis_energy_power_shout_balance', 'expiring_hours_message') }}
    visibility:
      - condition: state
        entity: binary_sensor.power_shout_hours_expiring
        state: "on"

---

### 5. Quick Account Details Grid Stack

A vertical stack grid displaying current rates, Power Shout balance, and billing cycle status:

    type: vertical-stack
    cards:
      - type: grid
        columns: 2
        square: false
        cards:
          - type: entity
            entity: sensor.genesis_energy_electricity_ev_low_day
            name: Current Rate
            icon: mdi:currency-usd
          - type: entity
            entity: sensor.genesis_energy_power_shout_balance
            name: Power Shout
            icon: mdi:lightning-bolt
      - type: entities
        entities:
          - entity: sensor.genesis_billing_cycle
            name: Current Bill Period
            secondary_info: last-changed

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
